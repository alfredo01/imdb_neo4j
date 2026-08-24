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

import numpy as np

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

# Crew kept when building the scatter-plot axes. Someone appearing in only one
# film of the result set adds a dimension orthogonal to every other film, which
# pushes that film away from all of them equally and says nothing about which
# films are near which. On a Vertigo query those one-offs are 119 of 131
# dimensions, and dropping them takes the variance captured in 2D from 25% to
# 51%. Raising this to 3 reaches 65%, but distinct films start landing on
# identical coordinates and overlap into a single dot.
MIN_SHARED_FOR_AXES = 2

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

# Crew of the films that came back, for the 2D projection. Fetched separately
# rather than collected in the query above: that one already aggregates over
# `other`, and adding a second collect of each film's own crew would multiply
# the rows it groups.
PROJECTION_CREW_CYPHER = f"""
MATCH (m:Movie)
WHERE m.movieId IN $movieIds
MATCH (m)<-[:{CREDIT_TYPES}]-(p:Person)
WHERE coalesce(p.degreeCentrality, 0) <= $maxPersonDegree
RETURN m.movieId AS movieId, collect(DISTINCT p.personId) AS crew
"""


# The seed on its own, so a film with no qualifying neighbour can still be told
# apart from a film that does not exist. Mirrors how expand_person uses `center`.
SEED_ONLY_CYPHER = """
MATCH (m:Movie)
WHERE m.movieId = $movie OR m.title = $movie
RETURN m AS seed
LIMIT 1
"""


def _project_2d(crew_by_movie):
    """Lay the films out in 2D so that on-screen distance means crew distance.

    Each film is a binary vector over crew space, and the cosine between two of
    those vectors is exactly the score RECOMMEND_MOVIE_CYPHER ranks by — so the
    plot and the ranked list are two views of one geometry rather than two
    different notions of "similar".

    This is PCA on the indicator matrix, equivalently classical MDS on the
    cosine distances. Rows are L2-normalised first so a dot product *is* the
    cosine; without that, films with large crews would sit further from the
    origin purely for having more people.

    Returns (coords_by_movieId, meta), or (None, None) when there is nothing
    worth projecting — fewer than three films, or no crew shared between any of
    them, in which case the layout would be arbitrary.
    """
    ids = sorted(crew_by_movie)
    if len(ids) < 3:
        return None, None

    counts = {}
    for crew in crew_by_movie.values():
        for person in crew:
            counts[person] = counts.get(person, 0) + 1
    people = sorted(p for p, n in counts.items() if n >= MIN_SHARED_FOR_AXES)
    if len(people) < 2:
        return None, None

    index = {person: i for i, person in enumerate(people)}
    matrix = np.zeros((len(ids), len(people)))
    for row, movie_id in enumerate(ids):
        for person in crew_by_movie[movie_id]:
            if person in index:
                matrix[row, index[person]] = 1.0

    # A film sharing nobody keeps an all-zero row. Normalising it would divide
    # by zero, so it is left at the origin of the crew space and simply lands
    # at the centroid of the plot.
    norms = np.linalg.norm(matrix, axis=1, keepdims=True)
    unit = np.divide(matrix, norms, out=np.zeros_like(matrix), where=norms > 0)

    centred = unit - unit.mean(axis=0)
    try:
        left, singular, _ = np.linalg.svd(centred, full_matrices=False)
    except np.linalg.LinAlgError:
        # SVD occasionally fails to converge. The recommendations are the point
        # of this endpoint; the plot is not worth failing the request over.
        return None, None

    kept = min(2, singular.size)
    coords = np.zeros((len(ids), 2))
    coords[:, :kept] = left[:, :kept] * singular[:kept]
    if not np.all(np.isfinite(coords)):
        return None, None

    total = float((singular ** 2).sum())
    variance = float((singular[:kept] ** 2).sum() / total) if total > 0 else 0.0

    # Kruskal-style stress: how much the 2D picture distorts the real pairwise
    # distances. Reported rather than hidden, because at ~0.4 the plot is a
    # genuine simplification and the UI should be able to say so.
    upper = np.triu_indices(len(ids), 1)
    high = np.linalg.norm(unit[:, None, :] - unit[None, :, :], axis=-1)[upper]
    low = np.linalg.norm(coords[:, None, :] - coords[None, :, :], axis=-1)[upper]
    denominator = float(np.linalg.norm(high))
    stress = float(np.linalg.norm(high - low) / denominator) if denominator > 0 else 0.0

    meta = {
        "method": "pca-crew-indicator",
        "films": len(ids),
        "crewSpace": len(people),
        "varianceExplained": round(variance, 4),
        "stress": round(stress, 4),
    }
    return {mid: (round(float(coords[i, 0]), 4), round(float(coords[i, 1]), 4))
            for i, mid in enumerate(ids)}, meta


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
            "projection": None,
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

    # Coordinates come last so a failure here cannot cost the recommendations:
    # every node is already complete, and `projection: None` simply means the
    # client draws the list without the scatter plot.
    crew_records = graph.query(
        PROJECTION_CREW_CYPHER,
        {
            "movieIds": [n["id"] for n in nodes],
            "maxPersonDegree": MAX_PERSON_DEGREE,
        },
    )
    crew_by_movie = {r["movieId"]: set(r["crew"]) for r in crew_records}
    coords, projection = _project_2d(crew_by_movie)
    if coords:
        for node in nodes:
            point = coords.get(node["id"])
            if point:
                node["x"], node["y"] = point

    return {
        "nodes": nodes,
        "links": links,
        "center": seed_id,
        "entities": {"persons": [], "movies": [seed_props.get("title")]},
        "projection": projection,
    }
