import json
from typing import Optional
from app.services.llm import llm
from app.services.graph import enhanced_graph as graph

EXTRACT_ENTITIES_PROMPT = """Extract person names and movie titles from the following question.
Return ONLY a JSON object with two keys: "persons" (list of person names) and "movies" (list of movie titles).
If none are found, return empty lists. Do not include any other text.

Question: {question}

JSON:"""


def _extract_entities(question: str) -> dict:
    """Use the LLM to extract person names and movie titles from the question."""
    response = llm.invoke(EXTRACT_ENTITIES_PROMPT.format(question=question))
    text = response.content.strip()
    # Remove markdown code fences if present
    if text.startswith("```"):
        text = text.split("\n", 1)[1] if "\n" in text else text[3:]
        text = text.rsplit("```", 1)[0]
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        return {"persons": [], "movies": []}


def _fuzzy_match(name: str, index_name: str, property_name: str) -> Optional[str]:
    """Query a Neo4j full-text index with fuzzy matching. Returns the best match or None."""
    results = graph.query(
        f"CALL db.index.fulltext.queryNodes('{index_name}', $query) "
        "YIELD node, score "
        f"RETURN node.{property_name} AS match, score LIMIT 1",
        {"query": name + "~"}
    )
    if results and results[0]["score"] > 0.5:
        return results[0]["match"]
    return None


def map_entities(question: str) -> str:
    """Extract entities from the question, fuzzy-match them against Neo4j, and return the corrected question."""
    entities = _extract_entities(question)
    corrected = question

    for person in entities.get("persons", []):
        match = _fuzzy_match(person, "personNameIndex", "name")
        if match and match.lower() != person.lower():
            corrected = corrected.replace(person, match)
            print(f"Entity mapped: '{person}' -> '{match}'")

    for movie in entities.get("movies", []):
        match = _fuzzy_match(movie, "movieTitleIndex", "title")
        if match and match.lower() != movie.lower():
            corrected = corrected.replace(movie, match)
            print(f"Entity mapped: '{movie}' -> '{match}'")

    if corrected != question:
        print(f"Corrected question: {corrected}")

    return corrected
