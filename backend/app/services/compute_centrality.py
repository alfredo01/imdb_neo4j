"""
Compute and store centrality scores for Movie and Person nodes.
Run this script once to initialize centrality scores, or periodically to update them.
"""

from neo4j import GraphDatabase
import os
import time
from dotenv import load_dotenv

load_dotenv()

GRAPH_NAME = "imdb-graph"

# GDS Community caps concurrency at 4 however many are asked for, and the VPS
# has 8 cores. Naming it here keeps the ask honest rather than silently clamped.
CONCURRENCY = 4

# Every property this script owns. Listed once because reset_scores() and the
# algorithms have to agree on the set: anything written by an algorithm and not
# cleared by the reset survives as a stale score on a node that a later run no
# longer projects.
CENTRALITY_PROPERTIES = (
    "pageRank",
    "eigenvectorCentrality",
    "betweennessCentrality",
    "degreeCentrality",
)


class CentralityComputer:
    def __init__(self, uri=None, user=None, password=None):
        # Default to container hostname, but allow override for host machine
        if uri is None:
            uri = os.getenv("NEO4J_URI", "bolt://neo4j:7687")
        if user is None:
            user = os.getenv("NEO4J_USERNAME", "neo4j")
        if password is None:
            password = os.getenv("NEO4J_PASSWORD")
        self.driver = GraphDatabase.driver(uri, auth=(user, password))

    def close(self):
        self.driver.close()

    # -- setup ---------------------------------------------------------------

    def reset_scores(self):
        """
        Drop the previous run's scores before recomputing.

        GDS writes only to nodes it projected, so a node that scored last time
        and falls out of the projection this time keeps its old number forever.
        That is not cosmetic: expand.py orders by `coalesce(pageRank, 0)` then
        `coalesce(degreeCentrality, 0)`, and a stale whole-graph degree of 400
        outranks a freshly computed, Movie-scoped 12.

        The `IS NOT NULL` gate is what keeps this affordable. It still scans both
        labels, but only the nodes a previous run actually wrote get a property
        write — roughly 3M rather than all 16.1M, once one scoped run has
        happened. `parallel` is safe here because each batch only ever touches
        its own nodes; there are no shared locks to deadlock on.
        """
        gate = " OR ".join(f"n.{p} IS NOT NULL" for p in CENTRALITY_PROPERTIES)
        removals = ", ".join(f"n.{p}" for p in CENTRALITY_PROPERTIES)

        with self.driver.session() as session:
            for label in ("Person", "Movie"):
                result = session.run(
                    """
                    CALL apoc.periodic.iterate(
                        $read,
                        $write,
                        {batchSize: 20000, parallel: true, concurrency: $concurrency}
                    )
                    YIELD batches, total, failedOperations, errorMessages
                    RETURN batches, total, failedOperations, errorMessages
                    """,
                    read=f"MATCH (n:{label}) WHERE {gate} RETURN n",
                    write=f"REMOVE {removals}",
                    concurrency=CONCURRENCY,
                )
                record = result.single()
                if record["failedOperations"]:
                    raise RuntimeError(
                        f"reset failed on {label}: {record['errorMessages']}"
                    )
                print(f"  {label}: cleared {record['total']:,} nodes")

    def project(self):
        """
        Project the Person/Movie subgraph once, for every algorithm to share.

        Deliberately not a native `['Person','Movie']` projection. That form
        takes every Person node — 15.4M of them — but ACTED_IN and the other
        credit types span all twelve title labels, and ~90% of Persons reach
        only Tvepisode or Short. Those nodes cannot score anything, yet each
        occupies a slot in every iteration of every algorithm and in every
        write-back. `gds.betweenness.write.estimate` asks 6.4GB against the full
        label projection versus roughly 1GB scoped this way, and that 6.4GB is
        what pinned the heap at 12GB and left the page cache with 512MB.

        A Cypher projection is the only form that can express the filter — a
        native projection cannot restrict nodes by pattern.

        The untyped `[r]` matches every Person->Movie credit type, not just
        ACTED_IN and DIRECTED. That is what expand.py's movie drill-down
        traverses (`MATCH (p:Person)-[r]->(m)`), so composers, writers and
        producers get real scores instead of coalescing to 0 and sorting below
        every actor.
        """
        with self.driver.session() as session:
            session.run("CALL gds.graph.drop($name, false)", name=GRAPH_NAME)

            result = session.run(
                """
                MATCH (p:Person)-[r]->(m:Movie)
                RETURN gds.graph.project(
                    $name, p, m,
                    {
                        sourceNodeLabels: ['Person'],
                        targetNodeLabels: ['Movie'],
                        relationshipType: type(r)
                    },
                    { undirectedRelationshipTypes: ['*'] }
                ) AS g
                """,
                name=GRAPH_NAME,
            )
            g = result.single()["g"]
            print(
                f"  {g['nodeCount']:,} nodes / {g['relationshipCount']:,} relationships"
                f" in {g['projectMillis'] / 1000:.1f}s"
            )

    def drop_projection(self):
        with self.driver.session() as session:
            session.run("CALL gds.graph.drop($name, false)", name=GRAPH_NAME)

    # -- algorithms ----------------------------------------------------------

    def compute_pagerank(self):
        """
        PageRank. More stable than eigenvector centrality, and the property the
        app orders by nearly everywhere.
        """
        with self.driver.session() as session:
            record = session.run(
                """
                CALL gds.pageRank.write($name, {
                    writeProperty: 'pageRank',
                    maxIterations: 100,
                    dampingFactor: 0.85,
                    concurrency: $concurrency
                })
                YIELD nodePropertiesWritten, ranIterations, didConverge
                RETURN nodePropertiesWritten, ranIterations, didConverge
                """,
                name=GRAPH_NAME,
                concurrency=CONCURRENCY,
            ).single()

            print(f"  {record['nodePropertiesWritten']:,} nodes written")
            print(
                f"  {record['ranIterations']} iterations,"
                f" converged: {record['didConverge']}"
            )

    def compute_eigenvector_centrality(self):
        """
        Eigenvector centrality — "prestigious" nodes connected to other
        prestigious nodes.

        Kept in the sequence even though the app never orders by it: the feature
        block in compute_embeddings_sage.py reads `m.eigenvectorCentrality`
        (alongside the other three) to build its Movie feature matrix, so
        skipping it leaves that column entirely null. It was the slowest of the
        four against the full label projection, which is why it was dropped
        before; on the scoped graph it costs about what PageRank costs. Delete
        the call in __main__ if that trade changes.
        """
        with self.driver.session() as session:
            record = session.run(
                """
                CALL gds.eigenvector.write($name, {
                    writeProperty: 'eigenvectorCentrality',
                    maxIterations: 100,
                    concurrency: $concurrency
                })
                YIELD nodePropertiesWritten, ranIterations, didConverge
                RETURN nodePropertiesWritten, ranIterations, didConverge
                """,
                name=GRAPH_NAME,
                concurrency=CONCURRENCY,
            ).single()

            print(f"  {record['nodePropertiesWritten']:,} nodes written")
            print(
                f"  {record['ranIterations']} iterations,"
                f" converged: {record['didConverge']}"
            )

    def compute_betweenness_centrality(self):
        """
        Betweenness centrality — how often a node lies on shortest paths between
        other nodes. Gives the best spread between important and minor nodes,
        which is why D3ForceGraph.jsx scales Person node radius by it.

        Sampled rather than exact: exact betweenness is O(V*E), hopeless at this
        size. Each of the `samplingSize` samples is a full traversal of the
        component, so cost tracks the projection — this is the step that gains
        most from the projection being scoped.
        """
        with self.driver.session() as session:
            record = session.run(
                """
                CALL gds.betweenness.write($name, {
                    writeProperty: 'betweennessCentrality',
                    samplingSize: 1000,
                    concurrency: $concurrency
                })
                YIELD nodePropertiesWritten
                RETURN nodePropertiesWritten
                """,
                name=GRAPH_NAME,
                concurrency=CONCURRENCY,
            ).single()

            print(f"  {record['nodePropertiesWritten']:,} nodes written")

    def compute_degree_centrality(self):
        """
        Degree centrality — simple connection count, used as the tiebreak after
        pageRank in expand.py.

        Runs on the shared projection. The previous implementation walked all
        16.1M Person and Movie nodes through apoc.periodic.iterate with
        `parallel: false`, evaluating `count { (p)--() }` per node — a
        single-threaded random walk over the entire 99.7M-relationship store,
        and the slowest thing in this file by a wide margin.

        The number it produces is not the same number. `count { (p)--() }`
        counted every relationship type across every title label, so a soap
        actor with 400 Tvepisode credits outranked a film lead on the tiebreak.
        This counts Movie credits only, consistent with pageRank and with what
        the app actually shows.
        """
        with self.driver.session() as session:
            record = session.run(
                """
                CALL gds.degree.write($name, {
                    writeProperty: 'degreeCentrality',
                    concurrency: $concurrency
                })
                YIELD nodePropertiesWritten
                RETURN nodePropertiesWritten
                """,
                name=GRAPH_NAME,
                concurrency=CONCURRENCY,
            ).single()

            print(f"  {record['nodePropertiesWritten']:,} nodes written")

    # -- reporting -----------------------------------------------------------

    def show_statistics(self):
        """Show statistics about computed centrality scores."""
        with self.driver.session() as session:
            print("\n" + "=" * 60)
            print("CENTRALITY STATISTICS")
            print("=" * 60)

            # Eigenvector - Top People
            print("\nTop 10 People by Eigenvector Centrality:")
            result = session.run("""
                MATCH (p:Person)
                WHERE p.eigenvectorCentrality IS NOT NULL
                RETURN p.name AS name, p.eigenvectorCentrality AS score
                ORDER BY score DESC
                LIMIT 10
            """)
            for i, record in enumerate(result, 1):
                print(f"  {i}. {record['name']}: {record['score']:.6f}")

            # Eigenvector - Top Movies
            print("\nTop 10 Movies by Eigenvector Centrality:")
            result = session.run("""
                MATCH (m:Movie)
                WHERE m.eigenvectorCentrality IS NOT NULL
                RETURN m.title AS title, m.year AS year, m.eigenvectorCentrality AS score
                ORDER BY score DESC
                LIMIT 10
            """)
            for i, record in enumerate(result, 1):
                print(f"  {i}. {record['title']} ({record['year']}): {record['score']:.6f}")

            # PageRank - Top People
            print("\nTop 10 People by PageRank:")
            result = session.run("""
                MATCH (p:Person)
                WHERE p.pageRank IS NOT NULL
                RETURN p.name AS name, p.pageRank AS score
                ORDER BY score DESC
                LIMIT 10
            """)
            for i, record in enumerate(result, 1):
                print(f"  {i}. {record['name']}: {record['score']:.6f}")

            # Betweenness - Top People
            print("\nTop 10 People by Betweenness Centrality:")
            result = session.run("""
                MATCH (p:Person)
                WHERE p.betweennessCentrality IS NOT NULL
                RETURN p.name AS name, p.betweennessCentrality AS score
                ORDER BY score DESC
                LIMIT 10
            """)
            for i, record in enumerate(result, 1):
                print(f"  {i}. {record['name']}: {record['score']:.2f}")

            # Degree - Statistics
            print("\nDegree Centrality Statistics:")
            result = session.run("""
                MATCH (p:Person)
                WHERE p.degreeCentrality IS NOT NULL
                RETURN
                    count(p) AS scored,
                    min(p.degreeCentrality) AS min,
                    max(p.degreeCentrality) AS max,
                    avg(p.degreeCentrality) AS avg,
                    percentileCont(p.degreeCentrality, 0.5) AS median,
                    percentileCont(p.degreeCentrality, 0.9) AS p90
            """)
            record = result.single()
            print(
                f"  People scored: {record['scored']:,}"
                f" - Min: {record['min']}, Max: {record['max']},"
                f" Avg: {record['avg']:.2f}, Median: {record['median']:.2f},"
                f" 90th: {record['p90']:.2f}"
            )


if __name__ == "__main__":
    computer = CentralityComputer()

    # Every step is timed. A run that dies halfway is otherwise a black box —
    # you cannot tell a step that is slow from one that is wedged, which is
    # exactly the position a timeout leaves you in.
    steps = [
        ("Clearing previous scores", computer.reset_scores),
        ("Projecting graph", computer.project),
        ("Computing PageRank", computer.compute_pagerank),
        ("Computing Eigenvector Centrality", computer.compute_eigenvector_centrality),
        ("Computing Betweenness Centrality", computer.compute_betweenness_centrality),
        ("Computing Degree Centrality", computer.compute_degree_centrality),
    ]

    try:
        print("Starting centrality computation...\n")
        started = time.monotonic()

        for name, step in steps:
            print(f"{name} ...", flush=True)
            step_started = time.monotonic()
            step()
            print(f"  done in {time.monotonic() - step_started:.1f}s\n", flush=True)

        computer.show_statistics()

        print("\n" + "=" * 60)
        print(
            "✓ All centrality scores computed and stored successfully!"
            f" ({time.monotonic() - started:.1f}s)"
        )
        print("=" * 60)

    except Exception as e:
        print(f"\n❌ Error: {e}")
        import traceback
        traceback.print_exc()
    finally:
        # The projection is heap the database cannot reclaim on its own. Leaving
        # it behind after a failure means the next run starts several GB down.
        try:
            computer.drop_projection()
        except Exception:
            pass
        computer.close()
