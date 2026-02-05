"""
Compute and store centrality scores for Movie and Person nodes.
Run this script once to initialize centrality scores, or periodically to update them.
"""

from neo4j import GraphDatabase
import os
from dotenv import load_dotenv

load_dotenv()

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

    def compute_eigenvector_centrality(self):
        """
        Compute eigenvector centrality for all nodes.
        This identifies "prestigious" nodes connected to other prestigious nodes.
        """
        with self.driver.session() as session:
            print("Computing Eigenvector Centrality...")

            # Drop existing graph projection if it exists
            session.run("CALL gds.graph.drop('imdb-graph', false)")

            # Create graph projection
            session.run("""
                CALL gds.graph.project(
                    'imdb-graph',
                    ['Person', 'Movie'],
                    {
                        ACTED_IN: {orientation: 'UNDIRECTED'},
                        DIRECTED: {orientation: 'UNDIRECTED'}
                    }
                )
            """)
            print("Graph projection created.")

            # Compute eigenvector centrality
            result = session.run("""
                CALL gds.eigenvector.write('imdb-graph', {
                    writeProperty: 'eigenvectorCentrality',
                    maxIterations: 20,
                    concurrency: 1
                })
                YIELD nodePropertiesWritten, ranIterations
                RETURN nodePropertiesWritten, ranIterations
            """)

            record = result.single()
            print(f"✓ Eigenvector centrality computed for {record['nodePropertiesWritten']} nodes")
            print(f"  Iterations: {record['ranIterations']}")

            # Drop the graph projection
            session.run("CALL gds.graph.drop('imdb-graph')")

    def compute_pagerank(self):
        """
        Compute PageRank for all nodes.
        More stable than eigenvector centrality, works well for importance ranking.
        """
        with self.driver.session() as session:
            print("\nComputing PageRank...")

            # Drop existing graph projection if it exists
            session.run("CALL gds.graph.drop('imdb-graph', false)")

            # Create graph projection
            session.run("""
                CALL gds.graph.project(
                    'imdb-graph',
                    ['Person', 'Movie'],
                    {
                        ACTED_IN: {orientation: 'UNDIRECTED'},
                        DIRECTED: {orientation: 'UNDIRECTED'}
                    }
                )
            """)

            # Compute PageRank
            result = session.run("""
                CALL gds.pageRank.write('imdb-graph', {
                    writeProperty: 'pageRank',
                    maxIterations: 20,
                    dampingFactor: 0.85,
                    concurrency: 1
                })
                YIELD nodePropertiesWritten, ranIterations
                RETURN nodePropertiesWritten, ranIterations
            """)

            record = result.single()
            print(f"✓ PageRank computed for {record['nodePropertiesWritten']} nodes")
            print(f"  Iterations: {record['ranIterations']}")

            # Drop the graph projection
            session.run("CALL gds.graph.drop('imdb-graph')")

    def compute_degree_centrality(self):
        """
        Compute degree centrality (simple connection count).
        Fast and easy to interpret. Uses batching to avoid transaction memory limits.
        """
        with self.driver.session() as session:
            print("\nComputing Degree Centrality...")

            # For Person nodes - process in batches
            session.run("""
                CALL apoc.periodic.iterate(
                    'MATCH (p:Person) RETURN p',
                    'SET p.degreeCentrality = count { (p)--() }',
                    {batchSize: 10000, parallel: false}
                )
            """)

            # For Movie nodes - process in batches
            session.run("""
                CALL apoc.periodic.iterate(
                    'MATCH (m:Movie) RETURN m',
                    'SET m.degreeCentrality = count { (m)--() }',
                    {batchSize: 10000, parallel: false}
                )
            """)

            print("✓ Degree centrality computed for all nodes")

    def show_statistics(self):
        """Show statistics about computed centrality scores."""
        with self.driver.session() as session:
            print("\n" + "="*60)
            print("CENTRALITY STATISTICS")
            print("="*60)

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

            # Degree - Statistics
            print("\nDegree Centrality Statistics:")
            result = session.run("""
                MATCH (p:Person)
                WHERE p.degreeCentrality IS NOT NULL
                RETURN
                    min(p.degreeCentrality) AS min,
                    max(p.degreeCentrality) AS max,
                    avg(p.degreeCentrality) AS avg,
                    percentileCont(p.degreeCentrality, 0.5) AS median,
                    percentileCont(p.degreeCentrality, 0.9) AS p90
            """)
            record = result.single()
            print(f"  People - Min: {record['min']}, Max: {record['max']}, Avg: {record['avg']:.2f}, Median: {record['median']:.2f}, 90th: {record['p90']:.2f}")


if __name__ == "__main__":
    computer = CentralityComputer()

    try:
        print("Starting centrality computation...\n")

        # Compute all centrality metrics
        computer.compute_eigenvector_centrality()
        computer.compute_pagerank()
        computer.compute_degree_centrality()

        # Show results
        computer.show_statistics()

        print("\n" + "="*60)
        print("✓ All centrality scores computed and stored successfully!")
        print("="*60)

    except Exception as e:
        print(f"\n❌ Error: {e}")
        import traceback
        traceback.print_exc()
    finally:
        computer.close()