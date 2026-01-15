from langchain_neo4j import GraphCypherQAChain
from langchain.prompts.prompt import PromptTemplate

from app.services.llm import llm
from app.services.graph import enhanced_graph as graph

CYPHER_GENERATION_TEMPLATE = """Task:Generate Cypher statement to query a graph database.
Instructions:
Use only the provided relationship types and properties in the schema.
Do not use any other relationship types or properties that are not provided.
The role attribute is only for the :ACTED_IN relationship type
Schema:
{schema}

IMPORTANT - Centrality Filtering:
All nodes have centrality scores (eigenvectorCentrality, pageRank, degreeCentrality) to identify important nodes.
When a query might return many nodes (>30), filter to the most relevant using:
- ORDER BY n.pageRank DESC LIMIT 30 (or eigenvectorCentrality or degreeCentrality)
- WHERE n.pageRank > 0.001 (adjust threshold as needed)
This ensures visualizations remain clear by showing only the most important/connected nodes.
For shortest path queries or specific entity lookups, no filtering is needed.

Note: Do not include any explanations or apologies in your responses.
Do not respond to any questions that might ask anything else than for you to construct a Cypher statement.
Do not include any text except the generated Cypher statement.
Use this writing [:rel1|rel2|rel3*] for multiple relationship types.
Examples: Here are a few examples of generated Cypher statements for particular questions:
# How many people played in Top Gun?
MATCH (m:Movie {{title:"Top Gun"}})<-[:ACTED_IN]-()
RETURN count(*) AS numberOfActors

# How are p1 and p2t connected? Give the shortest path.
MATCH p= shortestPath((p1:Person)-[*]-(p2:Person))
RETURN p

#How are Alfred Hitchcock and François Truffaut connected? give the shortest path.
MATCH p= shortestPath((p1:Person {{name:"Alfred Hitchcock"}})-[:ACTED_IN|DIRECTED*]-(p2:Person {{name:"François Truffaut"}}))
RETURN p

# Who are the most important actors in action movies? (example with centrality filtering)
MATCH (p:Person)-[:ACTED_IN]->(m:Movie)
WHERE m.title CONTAINS 'Action' OR m.title CONTAINS 'War'
WITH DISTINCT p
ORDER BY p.pageRank DESC
LIMIT 30
RETURN p

# What movies did Tom Hanks act in? (return only most important movies)
MATCH (p:Person {{name:"Tom Hanks"}})-[:ACTED_IN]->(m:Movie)
RETURN m
ORDER BY m.pageRank DESC
LIMIT 30

The question is:
{question}"""

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