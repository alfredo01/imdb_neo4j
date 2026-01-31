import os

# tag::graph[]
#from langchain_community.graphs import Neo4jGraph
from langchain_neo4j import Neo4jGraph

enhanced_graph = Neo4jGraph(
    url=os.getenv("NEO4J_URI", "neo4j://localhost:7687"),
    username=os.getenv("NEO4J_USERNAME", "neo4j"),
    password=os.getenv("NEO4J_PASSWORD"),
    enhanced_schema=True)