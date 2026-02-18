import re
from langchain.prompts.prompt import PromptTemplate

from app.services.llm import llm
from app.services.graph import enhanced_graph as graph
from app.services.tools.entity_mapper import map_entities

CYPHER_GENERATION_TEMPLATE = """You are a Cypher expert. Always generate Cypher queries using graph patterns like (a)-[r]->(b).
Return nodes and relationships that can be visualized as a graph.

Schema:
{schema}

CRITICAL - ALWAYS LIMIT RESULTS:
All queries MUST include ORDER BY ... LIMIT 60 to prevent overloading the visualization.
Use betweennessCentrality or degreeCentrality to order by importance.
Always return graph patterns (nodes + relationships), not just nodes.
NEVER generate a query without a LIMIT clause.

IMPORTANT - Exclude the central node from results:
When a query is about a specific person or movie (e.g. "Alfred Hitchcock's movies", "actors in Titanic"),
do NOT return the central/queried entity itself in the results. Only return the connected nodes and their relationships.
For example, if the question is about Alfred Hitchcock's movies, return the movies and their connections to other people, but exclude Alfred Hitchcock himself.

Examples with graph patterns:

# Specific movie query - still limit results
MATCH (p:Person)-[r:ACTED_IN]->(m:Movie {{title: "Titanic"}})
WITH p, r, m
ORDER BY p.betweennessCentrality DESC
LIMIT 60
RETURN p, r, m

# Broad query - filter by centrality for top results
MATCH (p:Person)-[r:ACTED_IN]->(m:Movie)
WHERE m.title CONTAINS "Action"
WITH p, r, m
ORDER BY p.betweennessCentrality DESC, m.betweennessCentrality DESC
LIMIT 60
RETURN p, r, m

# Year-based query - filter most important movies
MATCH (p:Person)-[r:ACTED_IN]->(m:Movie)
WHERE m.year = "1995"
WITH p, r, m
ORDER BY m.betweennessCentrality DESC
LIMIT 60
RETURN p, r, m

# Multiple relationship types with filtering
MATCH (p:Person)-[r:ACTED_IN|DIRECTED]->(m:Movie)
WHERE m.year >= "2000"
WITH p, r, m
ORDER BY p.betweennessCentrality DESC
LIMIT 60
RETURN p, r, m

Question:
{question}

Cypher Query:"""

CYPHER_GENERATION_PROMPT = PromptTemplate(
    input_variables=["schema", "question"], template=CYPHER_GENERATION_TEMPLATE
)


schema = graph.schema


def cypher_qa_tool(question: str, schema=schema) -> str:
    """
    Generate Cypher with LLM, run it on Neo4j. No second LLM call.
    """
    # Step 0: Map entities (fix misspellings via full-text index)
    if isinstance(question, list):
        # question is a list of message dicts from the chat API
        last_user_msg = question[-1]["content"]
        corrected = map_entities(last_user_msg)
        if corrected != last_user_msg:
            question[-1]["content"] = corrected
    else:
        question = map_entities(question)

    # Step 1: Generate Cypher
    prompt = CYPHER_GENERATION_PROMPT.format(schema=schema, question=question)
    response = llm.invoke(prompt)
    cypher = response.content.strip()
    # Remove markdown code fences if present
    cypher = re.sub(r"^```(?:cypher)?\s*", "", cypher)
    cypher = re.sub(r"\s*```$", "", cypher)
    # Safety: ensure LIMIT exists
    if not re.search(r"\bLIMIT\b", cypher, re.IGNORECASE):
        cypher = cypher.rstrip().rstrip(";") + "\nLIMIT 60"
    print("Generated Cypher:\n" + cypher + "\n")

    # Step 2: Run on Neo4j directly
    results = graph.query(cypher)
    print("Returned " + str(len(results)) + " records")

    return {"intermediate_steps": [{"query": cypher}, {"context": results}]}