# Backend — validation

The feature is mergeable when all the following hold against a healthy
Neo4j (the Neo4j feature's bring-up checks pass first).

## API surface
- `GET /` returns `200` with `{"data": "hello world"}`.
- `POST /chat` with the 5 canonical messages returns a Pydantic-valid
  body for each. The four "should resolve" cases return at least one
  node and one link. The "unanswerable" case returns
  `{nodes: [], links: [], reason: ...}` and HTTP `200`.
- `GET /graph/json` after a successful `/chat` returns the same payload
  the chat call returned (modulo the LLM debug field).

## Pipeline behavior
- The Cypher generated for "all actors in 1990s action movies" includes
  an `ORDER BY ... LIMIT` clause — verified by enabling the debug field.
- Removing the centrality property from one node does not break the
  response: enrichment is a no-op when the property is missing.

## Model jobs
- `python -m app.services.compute_centrality --dry-run` prints
  distribution stats and writes nothing.
- A real `compute_centrality` run completes within 5 minutes on the
  full IMDB graph and leaves zero `Person`/`Movie` nodes with a NULL
  centrality property.
- `compute_embeddings.py` and `compute_embeddings_sage.py` complete
  successfully and produce vectors of the documented dimensionality
  for every node in the projection.

## Dev posture
- `grep` shows no hard-coded Neo4j password in `backend/app/`.
- Wildcard CORS is gated behind an env flag whose default is "off".

## Regression
- Existing frontend (force graph + timeline) renders unchanged against
  the new responses — verified visually with a known query.