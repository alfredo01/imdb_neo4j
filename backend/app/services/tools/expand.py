"""Deterministic neighbourhood expansion around a Person or a Movie node.

The chat endpoint goes through the LLM to build Cypher; drill-down doesn't need
that. A double-click always means the same thing, so it runs a fixed query:
for a Person, their movies plus the main actors and the directors of those
movies; for a Movie, everyone involved in it.
"""

from app.services.graph import enhanced_graph as graph

# Person -> movies (ordered by importance), then for each movie the top actors
# and every director. Both sub-queries aggregate inside the CALL so a movie with
# no actors (or no known director) still yields a row instead of being dropped.
EXPAND_PERSON_CYPHER = """
MATCH (p:Person)
WHERE p.personId = $person OR p.name = $person
WITH p LIMIT 1
CALL {
    WITH p
    MATCH (p)-[r:ACTED_IN|DIRECTED]->(m:Movie)
    WITH m, collect(DISTINCT type(r)) AS roles
    RETURN m, roles
    ORDER BY coalesce(m.pageRankCentrality, 0) DESC,
             coalesce(m.degreeCentrality, 0) DESC
    LIMIT $movieLimit
}
CALL {
    WITH m
    MATCH (a:Person)-[:ACTED_IN]->(m)
    WITH a
    ORDER BY coalesce(a.pageRankCentrality, 0) DESC,
             coalesce(a.degreeCentrality, 0) DESC
    LIMIT $actorLimit
    RETURN collect(a) AS actors
}
CALL {
    WITH m
    MATCH (d:Person)-[:DIRECTED]->(m)
    RETURN collect(DISTINCT d) AS directors
}
RETURN p AS person, m AS movie, roles, actors, directors
ORDER BY coalesce(m.pageRankCentrality, 0) DESC
"""


# Movie -> every person attached to it, whatever the relationship type
# (ACTED_IN, DIRECTED, ...). The people are collected inside the CALL so the
# movie still comes back as a single row even when nobody is linked to it.
EXPAND_MOVIE_CYPHER = """
MATCH (m:Movie)
WHERE m.movieId = $movie OR m.title = $movie
WITH m LIMIT 1
CALL {
    WITH m
    MATCH (p:Person)-[r]->(m)
    WITH p, collect(DISTINCT type(r)) AS roles
    ORDER BY coalesce(p.pageRankCentrality, 0) DESC,
             coalesce(p.degreeCentrality, 0) DESC
    LIMIT $personLimit
    RETURN collect({person: p, roles: roles}) AS people
}
RETURN m AS movie, people
"""


def _person_node(props, is_center=False):
    node = {
        "id": props["personId"],
        "label": props.get("name"),
        "type": "Person",
    }
    if props.get("betweennessCentrality") is not None:
        node["betweennessCentrality"] = props["betweennessCentrality"]
    if is_center:
        node["isCenter"] = True
    return node


def _movie_node(props, is_center=False):
    node = {
        "id": props["movieId"],
        "label": props.get("title"),
        "type": "Movie",
    }
    if props.get("year") is not None:
        node["year"] = props["year"]
    if props.get("betweennessCentrality") is not None:
        node["betweennessCentrality"] = props["betweennessCentrality"]
    if is_center:
        node["isCenter"] = True
    return node


def expand_person(person: str, movie_limit: int = 10, actor_limit: int = 5) -> dict:
    """Return a D3 payload centred on `person` (personId or exact name).

    Nodes: the person, up to `movie_limit` of their movies, the top
    `actor_limit` actors of each movie and all of their directors.
    """
    records = graph.query(
        EXPAND_PERSON_CYPHER,
        {"person": person, "movieLimit": movie_limit, "actorLimit": actor_limit},
    )

    nodes = {}
    links = {}

    def add_node(node):
        # First writer wins, except that isCenter must never be lost: the
        # focused person also shows up in the actor/director lists.
        existing = nodes.get(node["id"])
        if existing is None:
            nodes[node["id"]] = node
        elif node.get("isCenter"):
            existing["isCenter"] = True

    def add_link(source, target, label):
        links[(source, target, label)] = {
            "source": source,
            "target": target,
            "label": label,
        }

    center_id = None
    center_label = None

    for record in records:
        person_props = record["person"]
        movie_props = record["movie"]
        center_id = person_props["personId"]
        center_label = person_props.get("name")

        add_node(_person_node(person_props, is_center=True))
        add_node(_movie_node(movie_props))
        for role in record["roles"]:
            add_link(center_id, movie_props["movieId"], role)

        for actor_props in record["actors"]:
            add_node(_person_node(actor_props))
            add_link(actor_props["personId"], movie_props["movieId"], "ACTED_IN")

        for director_props in record["directors"]:
            add_node(_person_node(director_props))
            add_link(director_props["personId"], movie_props["movieId"], "DIRECTED")

    return {
        "nodes": list(nodes.values()),
        "links": list(links.values()),
        "center": center_id,
        "entities": {"persons": [center_label] if center_label else [], "movies": []},
    }


def expand_movie(movie: str, person_limit: int = 200) -> dict:
    """Return a D3 payload centred on `movie` (movieId or exact title).

    Nodes: the movie plus every person linked to it — actors, directors and any
    other relationship type — capped at `person_limit`, most central first.
    """
    records = graph.query(
        EXPAND_MOVIE_CYPHER,
        {"movie": movie, "personLimit": person_limit},
    )

    nodes = []
    links = {}

    for record in records:
        movie_props = record["movie"]
        movie_id = movie_props["movieId"]
        nodes.append(_movie_node(movie_props, is_center=True))

        seen = set()
        for entry in record["people"]:
            person_props = entry["person"]
            person_id = person_props["personId"]
            if person_id not in seen:
                seen.add(person_id)
                nodes.append(_person_node(person_props))
            for role in entry["roles"]:
                links[(person_id, movie_id, role)] = {
                    "source": person_id,
                    "target": movie_id,
                    "label": role,
                }

    return {
        "nodes": nodes,
        "links": list(links.values()),
        "center": nodes[0]["id"] if nodes else None,
        "entities": {"persons": [], "movies": [nodes[0]["label"]] if nodes else []},
    }
