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

            # Create graph projection with ALL nodes and all relationship types
            print("Creating graph projection (full graph)...")
            session.run(f"""
                CALL gds.graph.project(
                    '{GRAPH_NAME}',
                    ['Person', 'Movie'],
                    {{
                        ACTED_IN: {{orientation: 'UNDIRECTED'}},
                        DIRECTED: {{orientation: 'UNDIRECTED'}},
                        PRODUCED: {{orientation: 'UNDIRECTED'}},
                        WROTE: {{orientation: 'UNDIRECTED'}},
                        COMPOSED: {{orientation: 'UNDIRECTED'}},
                        EDITED: {{orientation: 'UNDIRECTED'}},
                        CINEMATOGRAPHER: {{orientation: 'UNDIRECTED'}}
                    }}
                )
            """)
            print("Graph projection created.")

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
                    concurrency: 1,
                    sudo: true
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

            # Check Titanic's embedding
            print("\nChecking Titanic (1997) embedding:")
            result = session.run("""
                MATCH (m:Movie {title: 'Titanic', year: '1997'})
                WHERE m.embedding IS NOT NULL
                WITH m, m.embedding AS emb,
                     reduce(s = 0.0, x IN m.embedding | s + x*x) AS norm
                RETURN m.title AS title, size(emb) AS dim, norm
            """)
            record = result.single()
            if record:
                print(f"  dim={record['dim']}, norm={record['norm']:.6f}")
                if record['norm'] == 0.0:
                    print("  WARNING: Titanic has a zero embedding (isolated node in projection)")
            else:
                print("  Titanic (1997) not found or has no embedding")

            # Sample similarity: filter out zero-norm embeddings
            print("\nTop 5 movies most similar to 'Titanic' (by cosine similarity):")
            result = session.run("""
                MATCH (m1:Movie {title: 'Titanic', year: '1997'})
                WHERE m1.embedding IS NOT NULL
                MATCH (m2:Movie)
                WHERE m2.embedding IS NOT NULL AND m1 <> m2
                WITH m1, m2,
                     gds.similarity.cosine(m1.embedding, m2.embedding) AS similarity
                WHERE similarity IS NOT NULL AND NOT isNaN(similarity)
                ORDER BY similarity DESC
                LIMIT 5
                RETURN m2.title AS title, m2.year AS year, similarity
            """)
            for i, record in enumerate(result, 1):
                print(f"  {i}. {record['title']} ({record['year']}): {record['similarity']:.4f}")

            # Sample similarity for a person (filter to notable persons with pageRank > 1)
            print("\nTop 5 notable persons most similar to 'Steven Spielberg':")
            result = session.run("""
                MATCH (p1:Person {name: 'Steven Spielberg'})
                WHERE p1.embedding IS NOT NULL
                MATCH (p2:Person)
                WHERE p2.embedding IS NOT NULL AND p1 <> p2
                  AND p2.pageRank > 1
                WITH p1, p2,
                     gds.similarity.cosine(p1.embedding, p2.embedding) AS similarity
                WHERE similarity IS NOT NULL AND NOT isNaN(similarity)
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

        computer.compute_fastrp_embeddings(dimension=32)
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
