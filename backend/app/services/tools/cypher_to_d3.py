from langchain_neo4j import GraphCypherQAChain
from langchain.prompts.prompt import PromptTemplate

from app.services.llm import llm
from app.services.graph import enhanced_graph as graph

CYPHER_GENERATION_TEMPLATE = """You are a Cypher expert. Always generate Cypher queries using graph patterns like (a)-[r]->(b).
Return nodes and relationships that can be visualized as a graph.

Schema:
{schema}

IMPORTANT - Centrality Filtering for Clean Visualizations:
All nodes have centrality scores (eigenvectorCentrality, pageRank, degreeCentrality) to identify important/relevant nodes.
When queries might return many nodes (>30), filter to keep visualizations clean using ORDER BY with LIMIT.
Always return graph patterns (nodes + relationships), not just nodes.

IMPORTANT - Exclude the central node from results:
When a query is about a specific person or movie (e.g. "Alfred Hitchcock's movies", "actors in Titanic"),
do NOT return the central/queried entity itself in the results. Only return the connected nodes and their relationships.
For example, if the question is about Alfred Hitchcock's movies, return the movies and their connections to other people, but exclude Alfred Hitchcock himself.

Examples with graph patterns:

# Specific query - no filtering needed
MATCH (p:Person)-[r:ACTED_IN]->(m:Movie {{title: "Titanic"}})
RETURN p, r, m

# Broad query - filter by centrality for top results
MATCH (p:Person)-[r:ACTED_IN]->(m:Movie)
WHERE m.title CONTAINS "Action"
WITH p, r, m
ORDER BY p.eigenvectorCentrality DESC, m.eigenvectorCentrality DESC
LIMIT 30
RETURN p, r, m

# Year-based query - filter most important movies
MATCH (p:Person)-[r:ACTED_IN]->(m:Movie)
WHERE m.year = "1995"
WITH p, r, m
ORDER BY m.eigenvectorCentrality DESC
LIMIT 30
RETURN p, r, m

# Multiple relationship types with filtering
MATCH (p:Person)-[r:ACTED_IN|DIRECTED]->(m:Movie)
WHERE m.year >= "2000"
WITH p, r, m
ORDER BY p.eigenvectorCentrality DESC
LIMIT 30
RETURN p, r, m

Question:
{question}

Cypher Query:"""

CYPHER_GENERATION_PROMPT = PromptTemplate(
    input_variables=["schema", "question"], template=CYPHER_GENERATION_TEMPLATE
)


cypher_qa = GraphCypherQAChain.from_llm(
    llm=llm, 
    graph=graph, 
    verbose=True,
    allow_dangerous_requests=True,
    cypher_prompt=CYPHER_GENERATION_PROMPT,
    top_k=100,
    return_intermediate_steps=True
)
schema = graph.schema
def cypher_qa_tool(question: str, schema=schema) -> str:
    """
    Function to generate a Cypher query based on the provided question and schema.
    """
    return cypher_qa.invoke({"query": question,"schema": schema})