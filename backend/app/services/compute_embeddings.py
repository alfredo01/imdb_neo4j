"""
Compute FastRP structural embeddings for Movie nodes and materialise the
movie-to-movie recommendation edges built from them.

Item-to-item, not user-to-item: there is no ratings or watch-history data in
this graph, so "similar" here means "grown from the same collaboration
neighbourhood". FastRP's second hop on a bipartite Person->Movie graph is
movie -> its crew -> their other movies, which is exactly that signal.

Usage (from the backend container):
    python -m app.services.compute_embeddings
"""

from neo4j import GraphDatabase
import os
import time
from dotenv import load_dotenv

load_dotenv()

GRAPH_NAME = "imdb-embeddings"

# GDS Community clamps to 4 however many are requested; naming it keeps the ask
# honest rather than silently reduced.
CONCURRENCY = 4

# 128 rather than the 32 this script used to run. The old ceiling was blamed on
# "JVM memory", but the real cause was the projection: ['Person','Movie'] takes
# all 16.1M nodes, and gds.fastRP.write.estimate asks 49GiB for that at 256d.
# Scoped to the ~3.1M nodes that actually connect to a Movie, 128d estimates at
# 4.9GiB and fits the 8GiB heap. 256d would want 9.5GiB — over budget.
EMBEDDING_DIM = 128

# Skip the node's own random vector; weight hop 1 (the crew) and hop 2 (their
# other films) equally. Hop 2 is the recommendation signal, hop 1 only exists to
# reach it — on a bipartite graph an odd hop lands on People, never on Movies.
ITERATION_WEIGHTS = [0.0, 1.0, 1.0]

# Fixed so a rerun on an unchanged graph reproduces its recommendations. FastRP
# starts from random vectors; without a seed every run silently reshuffles the
# tail of every recommendation list, and you cannot tell a real change in the
# data from run-to-run jitter.
#
# GDS only honours randomSeed at concurrency 1, so the KNN step below trades
# parallelism for reproducibility. If that step turns out to dominate the
# runtime and you would rather have the speed, raise it to CONCURRENCY and
# accept that the tail of each list shifts between runs.
RANDOM_SEED = 42

# Neighbours stored per movie. 20 leaves room to filter at query time (by year,
# or to drop the ones the caller has already seen) and still return ten.
TOP_K = 20

SIMILARITY_REL = "SIMILAR_TO"

# The credit types that mean "made this film together". SELF, ARCHIVE_FOOTAGE
# and ARCHIVE_SOUND are excluded on purpose: appearing as yourself in a
# documentary, or having a clip reused, is not collaboration, and SELF alone is
# 15M relationships of pure noise. Matches KEPT_TYPES in compute_embeddings_sage.py.
CREDIT_TYPES = ["ACTED_IN", "DIRECTED", "PRODUCED", "WROTE",
                "COMPOSED", "EDITED", "CINEMATOGRAPHER"]


class EmbeddingComputer:
    def __init__(self, uri=None, user=None, password=None):
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

    def reset(self):
        """
        Drop the previous run's embeddings and recommendation edges.

        Both have to go. A stale `embedding` on a node that falls out of the
        projection would be silently mixed with fresh vectors from a different
        random basis, and cosine between two unrelated bases is noise. Stale
        SIMILAR_TO edges would simply be wrong recommendations that never expire.
        """
        with self.driver.session() as session:
            record = session.run(
                f"""
                CALL apoc.periodic.iterate(
                    'MATCH ()-[r:{SIMILARITY_REL}]->() RETURN r',
                    'DELETE r',
                    {{batchSize: 50000, parallel: false}}
                )
                YIELD total, failedOperations, errorMessages
                RETURN total, failedOperations, errorMessages
                """
            ).single()
            if record["failedOperations"]:
                raise RuntimeError(f"edge reset failed: {record['errorMessages']}")
            print(f"  removed {record['total']:,} old {SIMILARITY_REL} edges")

            for label in ("Person", "Movie"):
                record = session.run(
                    """
                    CALL apoc.periodic.iterate(
                        $read,
                        'REMOVE n.embedding',
                        {batchSize: 20000, parallel: true, concurrency: $concurrency}
                    )
                    YIELD total, failedOperations, errorMessages
                    RETURN total, failedOperations, errorMessages
                    """,
                    read=f"MATCH (n:{label}) WHERE n.embedding IS NOT NULL RETURN n",
                    concurrency=CONCURRENCY,
                ).single()
                if record["failedOperations"]:
                    raise RuntimeError(
                        f"embedding reset failed on {label}: {record['errorMessages']}"
                    )
                print(f"  {label}: cleared {record['total']:,} embeddings")

    def project(self):
        """
        Project the Person/Movie collaboration graph, scoped to the credit types
        that mean people actually worked together.

        Same reasoning as compute_centrality.py: a native ['Person','Movie']
        projection carries 15.4M Person nodes when ~90% of them only ever reach
        a Tvepisode or a Short and can contribute nothing to a movie embedding.

        Persons are projected too, and that is not waste — they are the bridge.
        Two movies are only connected through the crew they share, so removing
        the People would leave 748k isolated nodes and every embedding identical.
        Their vectors are computed and then discarded at write time.
        """
        types = "|".join(CREDIT_TYPES)
        with self.driver.session() as session:
            session.run("CALL gds.graph.drop($name, false)", name=GRAPH_NAME)

            g = session.run(
                f"""
                MATCH (p:Person)-[r:{types}]->(m:Movie)
                RETURN gds.graph.project(
                    $name, p, m,
                    {{
                        sourceNodeLabels: ['Person'],
                        targetNodeLabels: ['Movie'],
                        relationshipType: type(r)
                    }},
                    {{ undirectedRelationshipTypes: ['*'] }}
                ) AS g
                """,
                name=GRAPH_NAME,
            ).single()["g"]

            print(
                f"  {g['nodeCount']:,} nodes / {g['relationshipCount']:,} relationships"
                f" in {g['projectMillis'] / 1000:.1f}s"
            )

    def drop_projection(self):
        with self.driver.session() as session:
            session.run("CALL gds.graph.drop($name, false)", name=GRAPH_NAME)

    # -- pipeline ------------------------------------------------------------

    def compute_embeddings(self):
        """
        FastRP into the in-memory graph.

        `mutate`, not `write`: KNN needs the vectors inside the projection to
        compare them, and a property written to the database is not visible
        there. They are persisted separately once KNN is done.
        """
        with self.driver.session() as session:
            record = session.run(
                """
                CALL gds.fastRP.mutate($name, {
                    embeddingDimension: $dim,
                    iterationWeights: $weights,
                    randomSeed: $seed,
                    mutateProperty: 'embedding',
                    concurrency: $concurrency
                })
                YIELD nodePropertiesWritten, computeMillis
                RETURN nodePropertiesWritten, computeMillis
                """,
                name=GRAPH_NAME,
                dim=EMBEDDING_DIM,
                weights=ITERATION_WEIGHTS,
                seed=RANDOM_SEED,
                concurrency=CONCURRENCY,
            ).single()

            print(
                f"  {record['nodePropertiesWritten']:,} vectors ({EMBEDDING_DIM}d)"
                f" in {record['computeMillis'] / 1000:.1f}s"
            )

    def build_recommendations(self):
        """
        KNN over the movie embeddings, materialised as SIMILAR_TO edges.

        `nodeLabels: ['Movie']` is what makes this a movie recommender: People
        are in the projection as connective tissue, and comparing an actor to a
        film is meaningless. KNN is approximate — it samples and refines rather
        than doing all 748k^2 pairs — so `didConverge` is worth reading.
        """
        with self.driver.session() as session:
            record = session.run(
                """
                CALL gds.knn.write($name, {
                    nodeLabels: ['Movie'],
                    nodeProperties: ['embedding'],
                    topK: $topK,
                    writeRelationshipType: $relType,
                    writeProperty: 'score',
                    randomSeed: $seed,
                    concurrency: 1,  # see RANDOM_SEED: determinism over speed
                    sampleRate: 0.5,
                    deltaThreshold: 0.001
                })
                YIELD nodesCompared, relationshipsWritten, didConverge,
                      ranIterations, similarityDistribution
                RETURN nodesCompared, relationshipsWritten, didConverge,
                       ranIterations, similarityDistribution
                """,
                name=GRAPH_NAME,
                topK=TOP_K,
                relType=SIMILARITY_REL,
                seed=RANDOM_SEED,
            ).single()

            dist = record["similarityDistribution"]
            print(f"  {record['nodesCompared']:,} movies compared")
            print(f"  {record['relationshipsWritten']:,} {SIMILARITY_REL} edges written")
            print(
                f"  {record['ranIterations']} iterations,"
                f" converged: {record['didConverge']}"
            )
            print(
                f"  similarity  mean {dist['mean']:.3f}"
                f"  p50 {dist['p50']:.3f}  p95 {dist['p95']:.3f}  max {dist['max']:.3f}"
            )

    def persist_embeddings(self):
        """
        Copy the vectors from the projection to the Movie nodes.

        Only Movies: the Person vectors did their job as the bridge between
        films and are 15x the volume. Persisting them would cost far more disk
        and page cache than anything reads back.
        """
        with self.driver.session() as session:
            record = session.run(
                """
                CALL gds.graph.nodeProperties.write($name, ['embedding'], ['Movie'])
                YIELD propertiesWritten
                RETURN propertiesWritten
                """,
                name=GRAPH_NAME,
            ).single()
            print(f"  {record['propertiesWritten']:,} movie embeddings persisted")

    # -- reporting -----------------------------------------------------------

    def show_statistics(self, samples=("tt0052357", "tt0055913", "tt0047396")):
        """Show what the recommender actually returns, for films worth judging."""
        with self.driver.session() as session:
            print("\n" + "=" * 62)
            print("RECOMMENDATION SAMPLES")
            print("=" * 62)

            record = session.run(
                """
                MATCH (m:Movie) WHERE m.embedding IS NOT NULL
                WITH m LIMIT 1
                RETURN size(m.embedding) AS dim
                """
            ).single()
            if record:
                print(f"\nStored dimension: {record['dim']}")

            for movie_id in samples:
                record = session.run(
                    "MATCH (m:Movie {movieId: $id}) RETURN m.title AS t, m.year AS y",
                    id=movie_id,
                ).single()
                if not record:
                    print(f"\n{movie_id}: not found")
                    continue

                print(f"\n{record['t']} ({record['y']}) — top 10 similar:")
                rows = session.run(
                    f"""
                    MATCH (m:Movie {{movieId: $id}})-[s:{SIMILARITY_REL}]->(rec:Movie)
                    RETURN rec.title AS title, rec.year AS year, s.score AS score
                    ORDER BY s.score DESC
                    LIMIT 10
                    """,
                    id=movie_id,
                )
                found = False
                for i, row in enumerate(rows, 1):
                    found = True
                    print(f"  {i:2}. {row['score']:.4f}  {row['title']} ({row['year']})")
                if not found:
                    print("  (no SIMILAR_TO edges — KNN found no neighbours)")


if __name__ == "__main__":
    computer = EmbeddingComputer()

    steps = [
        ("Clearing previous run", computer.reset),
        ("Projecting collaboration graph", computer.project),
        ("Computing FastRP embeddings", computer.compute_embeddings),
        ("Building recommendation edges", computer.build_recommendations),
        ("Persisting movie embeddings", computer.persist_embeddings),
    ]

    try:
        print("Starting embedding computation...\n")
        started = time.monotonic()

        for name, step in steps:
            print(f"{name} ...", flush=True)
            step_started = time.monotonic()
            step()
            print(f"  done in {time.monotonic() - step_started:.1f}s\n", flush=True)

        computer.show_statistics()

        print("\n" + "=" * 62)
        print(f"Done in {time.monotonic() - started:.1f}s")
        print("=" * 62)

    except Exception as e:
        print(f"\nError: {e}")
        import traceback
        traceback.print_exc()
    finally:
        # The projection is heap the database will not reclaim on its own.
        try:
            computer.drop_projection()
        except Exception:
            pass
        computer.close()
