"""Deterministic neighbourhood expansion around a Person or a Movie node.

The chat endpoint goes through the LLM to build Cypher; drill-down doesn't need
that. A double-click always means the same thing, so it runs a fixed query:
for a Person, their movies plus the main actors and the directors of those
movies; for a Movie, everyone involved in it.
"""

from app.services.graph import enhanced_graph as graph
from app.services.tools.titles import localised_titles

# Step 1 of the person expansion: the person and their complete filmography,
# most central first. Movies own the node budget, so this is capped only by the
# budget itself, not by a small fixed limit. The CALL aggregates, so a person
# with no films still comes back as a row.
EXPAND_PERSON_CYPHER = """
MATCH (p:Person)
WHERE p.personId = $person OR p.name = $person
WITH p LIMIT 1
CALL {
    WITH p
    MATCH (p)-[r:ACTED_IN|DIRECTED]->(m:Movie)
    WITH m, collect(DISTINCT type(r)) AS roles
    ORDER BY coalesce(m.pageRank, 0) DESC,
             coalesce(m.degreeCentrality, 0) DESC
    LIMIT $movieLimit
    RETURN collect({movie: m, roles: roles}) AS movies
}
RETURN p AS person, movies
"""

# Step 2: the crew of those movies. Every director (there are few, and a
# co-director is more informative than one more actor) plus the top actors of
# each. `actorLimit` is the per-movie allowance the caller computed from what is
# left of the node budget; the caller then decides who actually fits.
EXPAND_PERSON_CREW_CYPHER = """
MATCH (m:Movie)
WHERE m.movieId IN $movieIds
CALL {
    WITH m
    MATCH (d:Person)-[:DIRECTED]->(m)
    RETURN collect(DISTINCT d) AS directors
}
CALL {
    WITH m
    MATCH (a:Person)-[:ACTED_IN]->(m)
    WITH a
    ORDER BY coalesce(a.pageRank, 0) DESC,
             coalesce(a.degreeCentrality, 0) DESC
    LIMIT $actorLimit
    RETURN collect(a) AS actors
}
RETURN m.movieId AS movieId, directors, actors
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
    ORDER BY coalesce(p.pageRank, 0) DESC,
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


def _movie_node(props, is_center=False, roles=None):
    node = {
        "id": props["movieId"],
        "label": props.get("title"),
        "type": "Movie",
    }
    if roles:
        # e.g. ["DIRECTED"] — what the expanded person did on this film.
        node["subjectRoles"] = roles
    if props.get("year") is not None:
        node["year"] = props["year"]
    titles = localised_titles(props)
    if titles:
        node["titles"] = titles
    if props.get("betweennessCentrality") is not None:
        node["betweennessCentrality"] = props["betweennessCentrality"]
    if is_center:
        node["isCenter"] = True
    return node


def expand_person(person: str, node_limit: int = 200) -> dict:
    """Return a D3 payload centred on `person` (personId or exact name).

    The whole filmography comes first: every movie the person acted in or
    directed is a node, so nothing important is cut by a small fixed limit.
    Whatever is left of `node_limit` then goes to the people around those
    movies — directors first, then actors spread evenly across the films, so a
    prolific career doesn't hand the entire budget to its first few titles.
    Co-actors that don't fit are a double-click away on the movie itself.

    The subject is deliberately *not* in the graph. They would link to every
    single movie, which is a hub that says nothing — the whole view is already
    "their films" — while dragging the layout into a starburst and hiding the
    connections that do carry information, the ones between films. Their name
    still travels in `entities` and `center` so the UI can title the view.
    """
    movie_cap = max(1, node_limit)
    records = graph.query(
        EXPAND_PERSON_CYPHER,
        {"person": person, "movieLimit": movie_cap},
    )
    if not records:
        return {"nodes": [], "links": [], "center": None,
                "entities": {"persons": [], "movies": []}}

    nodes = {}
    links = {}

    def add_node(node):
        nodes.setdefault(node["id"], node)

    def add_link(source, target, label):
        links[(source, target, label)] = {
            "source": source,
            "target": target,
            "label": label,
        }

    def add_related(props, movie_id, label):
        """Attach a crew member to a movie, respecting the node budget.

        Someone already on the graph is free to link — only a new node spends
        budget. Returns False once the graph is full.
        """
        person_id = props["personId"]
        if person_id not in nodes:
            if len(nodes) >= node_limit:
                return False
            add_node(_person_node(props))
        add_link(person_id, movie_id, label)
        return True

    record = records[0]
    person_props = record["person"]
    center_id = person_props["personId"]
    center_label = person_props.get("name")

    movie_ids = []
    for entry in record["movies"]:
        movie_props = entry["movie"]
        movie_id = movie_props["movieId"]
        # What the subject did on this film is kept on the movie itself, since
        # the link that used to carry it is gone with them.
        add_node(_movie_node(movie_props, roles=entry["roles"]))
        movie_ids.append(movie_id)

    remaining = node_limit - len(nodes)
    if movie_ids and remaining > 0:
        # Ask for a little more than the even share: crew members recur across a
        # filmography, and a duplicate costs no budget, so the surplus is what
        # keeps the graph filling up to the limit rather than stalling short.
        per_movie = max(1, remaining // len(movie_ids) + 2)
        crew_records = graph.query(
            EXPAND_PERSON_CREW_CYPHER,
            {"movieIds": movie_ids, "actorLimit": per_movie},
        )
        crew = {r["movieId"]: r for r in crew_records}

        # Directors of every movie first.
        for movie_id in movie_ids:
            for director_props in crew.get(movie_id, {}).get("directors", []):
                if director_props["personId"] == center_id:
                    continue
                add_related(director_props, movie_id, "DIRECTED")

        # Then actors round-robin: one per movie per pass, so the budget is
        # shared across the filmography instead of being drained by movie #1.
        depth = max((len(r["actors"]) for r in crew_records), default=0)
        for rank in range(depth):
            if len(nodes) >= node_limit:
                break
            for movie_id in movie_ids:
                actors = crew.get(movie_id, {}).get("actors", [])
                if rank >= len(actors):
                    continue
                actor_props = actors[rank]
                if actor_props["personId"] == center_id:
                    continue
                add_related(actor_props, movie_id, "ACTED_IN")

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
