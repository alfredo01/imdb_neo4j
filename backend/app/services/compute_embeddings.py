"""
Compute and store FastRP graph structural embeddings for Movie and Person nodes.
Run this script once to initialize embeddings, or again to recompute them.

Usage (from backend container):
    python -m app.services.compute_embeddings
"""

from neo4j import GraphDatabase
import os
from dotenv import load_dotenv

load_dotenv()

GRAPH_NAME = "imdb-embeddings"


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

    def compute_fastrp_embeddings(self, dimension=128):
        """
        Compute FastRP embeddings using all relationship types.
        FastRP learns structural embeddings from random walks on the graph.
        Movies/persons sharing many collaborators will be close in vector space.
        """
        with self.driver.session() as session:
            print("Computing FastRP Embeddings...")

            # Drop existing graph projection if it exists
            session.run(f"CALL gds.graph.drop('{GRAPH_NAME}', false)")

            # Create graph projection filtered by pageRank > 2
            print("Creating graph projection (nodes with pageRank > 2)...")
            session.run(f"""
                CALL gds.graph.project.cypher(
                    '{GRAPH_NAME}',
                    'MATCH (n) WHERE n.pageRank > 2 RETURN id(n) AS id',
                    'MATCH (n)-[r]-(m)
                     WHERE n.pageRank > 2 AND m.pageRank > 2
                     RETURN id(n) AS source, id(m) AS target, type(r) AS type'
                )
            """)

            # Count projected nodes
            result = session.run(f"""
                CALL gds.graph.list('{GRAPH_NAME}')
                YIELD nodeCount, relationshipCount
                RETURN nodeCount, relationshipCount
            """)
            record = result.single()
            print(f"Graph projection created: {{record['nodeCount']}} nodes, {{record['relationshipCount']}} relationships")

            # Compute FastRP embeddings
            # iterationWeights: [0.0, 1.0, 1.0]
            #   - 0.0: skip self (node's own features)
            #   - 1.0: weight 1-hop neighbors (direct collaborators)
            #   - 1.0: weight 2-hop neighbors (collaborators of collaborators)
            print(f"Running FastRP with dimension={dimension}...")
            result = session.run(f"""
                CALL gds.fastRP.write('{GRAPH_NAME}', {{
                    embeddingDimension: {dimension},
                    iterationWeights: [0.0, 1.0, 1.0],
                    writeProperty: 'embedding',
                    concurrency: 1
                }})
                YIELD nodePropertiesWritten
                RETURN nodePropertiesWritten
            """)

            record = result.single()
            print(f"Embeddings computed for {record['nodePropertiesWritten']} nodes")

            # Drop the graph projection
            session.run(f"CALL gds.graph.drop('{GRAPH_NAME}')")

    def show_statistics(self):
        """Verify embeddings and show sample similarities."""
        with self.driver.session() as session:
            print("\n" + "=" * 60)
            print("EMBEDDING STATISTICS")
            print("=" * 60)

            # Count nodes with embeddings
            result = session.run("""
                MATCH (m:Movie)
                WHERE m.embedding IS NOT NULL
                RETURN count(m) AS movieCount
            """)
            movie_count = result.single()["movieCount"]

            result = session.run("""
                MATCH (p:Person)
                WHERE p.embedding IS NOT NULL
                RETURN count(p) AS personCount
            """)
            person_count = result.single()["personCount"]

            print(f"\nMovies with embeddings: {movie_count}")
            print(f"Persons with embeddings: {person_count}")

            # Show embedding dimension
            result = session.run("""
                MATCH (m:Movie)
                WHERE m.embedding IS NOT NULL
                RETURN size(m.embedding) AS dim
                LIMIT 1
            """)
            record = result.single()
            if record:
                print(f"Embedding dimension: {record['dim']}")

            # Sample similarity: find movies most similar to a well-known movie
            print("\nTop 5 movies most similar to 'Titanic' (by cosine similarity):")
            result = session.run("""
                MATCH (m1:Movie {title: 'Titanic'})
                WHERE m1.embedding IS NOT NULL AND m1.year = '1997'
                MATCH (m2:Movie)
                WHERE m2.embedding IS NOT NULL AND m1 <> m2
                WITH m1, m2,
                     gds.similarity.cosine(m1.embedding, m2.embedding) AS similarity
                ORDER BY similarity DESC
                LIMIT 5
                RETURN m2.title AS title, m2.year AS year, similarity
            """)
            for i, record in enumerate(result, 1):
                print(f"  {i}. {record['title']} ({record['year']}): {record['similarity']:.4f}")

            # Sample similarity for a person
            print("\nTop 5 persons most similar to 'Steven Spielberg':")
            result = session.run("""
                MATCH (p1:Person {name: 'Steven Spielberg'})
                WHERE p1.embedding IS NOT NULL
                MATCH (p2:Person)
                WHERE p2.embedding IS NOT NULL AND p1 <> p2
                WITH p1, p2,
                     gds.similarity.cosine(p1.embedding, p2.embedding) AS similarity
                ORDER BY similarity DESC
                LIMIT 5
                RETURN p2.name AS name, similarity
            """)
            for i, record in enumerate(result, 1):
                print(f"  {i}. {record['name']}: {record['similarity']:.4f}")


if __name__ == "__main__":
    computer = EmbeddingComputer()

    try:
        print("Starting FastRP embedding computation...\n")

        computer.compute_fastrp_embeddings(dimension=128)
        computer.show_statistics()

        print("\n" + "=" * 60)
        print("All embeddings computed and stored successfully!")
        print("=" * 60)

    except Exception as e:
        print(f"\nError: {e}")
        import traceback
        traceback.print_exc()
    finally:
        computer.close()
