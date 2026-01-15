#import streamlit as st

# tag::graph[]
#from langchain_community.graphs import Neo4jGraph
from langchain_neo4j import Neo4jGraph

enhanced_graph = Neo4jGraph(
    url="bolt://neo4j:7687",
    username="neo4j",
    password=None,
    enhanced_schema=True)