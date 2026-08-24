"""Movie-to-movie recommendations from shared crew.

Item-to-item, not user-to-item: the graph holds no ratings and no watch
history, so the only available notion of "similar" is "made by overlapping
people". Two movies are related here when the same crew worked on both.

This deliberately does not use the FastRP embeddings. At 128 dimensions over
~726k movies the random-projection noise floor swamps the signal — the cosine
between two Hitchcock films that genuinely share five crew came out at 0.378,
while unrelated pairs reached 0.36 by chance alone. Fixing that needs ~512
dimensions, which does not fit the heap. The two-hop count below is exact,
cheap, and explainable, and it beat the embeddings on every seed tried.
"""

from app.services.graph import enhanced_graph as graph
# Imported rather than duplicated so a recommendation node is byte-identical to
# an expansion node: the frontend's displayLabel and localised titles depend on
# that shape, and a second copy of the builder would drift from it.
from app.services.tools.expand import _movie_node

# The credit types that mean people actually made a film together. SELF,
# ARCHIVE_FOOTAGE and ARCHIVE_SOUND are excluded: without this filter, Vertigo
# recommends "My Name Is Alfred Hitchcock" and "Alfred Hitchcock: Master of
# Suspense" — documentaries that reuse its footage, not films like it.
CREDIT_TYPES = "ACTED_IN|DIRECTED|PRODUCED|WROTE|COMPOSED|EDITED|CINEMATOGRAPHER"

# Cost guard, not a quality filter. Expansion from the seed costs the sum of its
# crew's credit counts, so one hyper-prolific member could dominate the whole
# query. Person degree runs p99=40, p99.9=125, max=1958, so this excludes 82
# people out of 2.4M and never binds on an ordinary film.
MAX_PERSON_DEGREE = 400

# One shared crew member is mostly coincidence — a jobbing editor, a composer
# who scored half the decade. Two is where the lists start being about the film.
MIN_SHARED = 2

# Sorted by cosine over the crew sets: shared / sqrt(deg(seed) * deg(other)).
#
# The normalisation is what makes this work. On the raw count, films with big
# crews dominate every list; worse, Vertigo's tail filled with 1990s French TV
# movies that share exactly two people with it — Boileau and Narcejac, who wrote
# the novel it was adapted from and whose other novels were adapted decades
# later. Dividing by sqrt(deg * deg) drops those from the list entirely while
# leaving the Hitchcock cluster untouched.
#
# `shared_with` travels back with each row so the UI can say *why* a film was
# recommended. It is capped at four names because that is all a tooltip needs.
RECOMMEND_MOVIE_CYPHER = f"""
MATCH (m:Movie)
WHERE m.movieId = $movie OR m.title = $movie
WITH m LIMIT 1
MATCH (m)<-[:{CREDIT_TYPES}]-(p:Person)
WHERE coalesce(p.degreeCentrality, 0) <= $maxPersonDegree
WITH m, collect(DISTINCT p) AS crew
WITH m, crew, toFloat(size(crew)) AS seedDegree
UNWIND crew AS member
MATCH (member)-[:{CREDIT_TYPES}]->(other:Movie)
WHERE other.movieId <> m.movieId
WITH m, seedDegree, other,
     count(DISTINCT member) AS shared,
     collect(DISTINCT member.name)[0..4] AS sharedWith
WHERE shared >= $minShared
RETURN m AS seed,
       other AS movie,
       shared,
       sharedWith,
       shared / sqrt(seedDegree * toFloat(coalesce(other.degreeCentrality, 1)))
           AS score
ORDER BY score DESC, other.pageRank DESC
LIMIT $limit
"""

# The seed on its own, so a film with no qualifying neighbour can still be told
# apart from a film that does not exist. Mirrors how expand_person uses `center`.
SEED_ONLY_CYPHER = """
MATCH (m:Movie)
WHERE m.movieId = $movie OR m.title = $movie
RETURN m AS seed
LIMIT 1
"""


def recommend_movie(movie: str, limit: int = 10) -> dict:
    """Return a D3 payload of the movies most similar to `movie`.

    `movie` is a movieId (e.g. tt0052357) or an exact title. The payload is the
    same shape the /expand endpoints return, so the graph view renders it with
    no special casing: the seed is the centre, each recommendation hangs off it
    by a SIMILAR link carrying the score.

    Unlike expand_person, the subject *is* in the graph. There it was dropped
    because linking to everything made it an uninformative hub; here the star
    shape is the whole point — every edge means "similar to this one film", and
    the recommendations are not claimed to be similar to each other.
    """
    records = graph.query(
        RECOMMEND_MOVIE_CYPHER,
        {
            "movie": movie,
            "maxPersonDegree": MAX_PERSON_DEGREE,
            "minShared": MIN_SHARED,
            "limit": max(1, limit),
        },
    )

    if not records:
        # Either the title is unknown or it has no crew overlap worth showing.
        # The caller needs to tell a 404 from an empty-but-valid result.
        seed_records = graph.query(SEED_ONLY_CYPHER, {"movie": movie})
        if not seed_records:
            return {"nodes": [], "links": [], "center": None,
                    "entities": {"persons": [], "movies": []}}
        seed_props = seed_records[0]["seed"]
        return {
            "nodes": [_movie_node(seed_props, is_center=True)],
            "links": [],
            "center": seed_props["movieId"],
            "entities": {"persons": [], "movies": [seed_props.get("title")]},
        }

    seed_props = records[0]["seed"]
    seed_id = seed_props["movieId"]
    nodes = [_movie_node(seed_props, is_center=True)]
    links = []

    for record in records:
        movie_props = record["movie"]
        node = _movie_node(movie_props)
        # Why this film is here, carried on the node so a list view can show it
        # without re-reading the links.
        node["score"] = round(record["score"], 4)
        node["sharedCount"] = record["shared"]
        node["sharedWith"] = record["sharedWith"]
        nodes.append(node)

        links.append({
            "source": seed_id,
            "target": movie_props["movieId"],
            "label": "SIMILAR",
            "score": round(record["score"], 4),
        })

    return {
        "nodes": nodes,
        "links": links,
        "center": seed_id,
        "entities": {"persons": [], "movies": [seed_props.get("title")]},
    }
