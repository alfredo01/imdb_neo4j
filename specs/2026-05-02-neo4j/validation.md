# Neo4j — validation

The feature is mergeable when **all** of the following hold from a clean
checkout on the VPS (or any developer machine).

## Bring-up
- `dvc pull` followed by `docker-compose up -d neo4j` reaches a healthy
  container within 60 seconds.
- `cypher-shell -u neo4j -p $NEO4J_PASSWORD "CALL gds.version()"` returns
  a version string.
- `cypher-shell ... "RETURN apoc.version()"` returns a version string.

## Schema invariants
- `MATCH (n) WHERE n:Person OR n:Movie RETURN count(n)` returns the
  expected dataset size (record the number in `requirements.md` once
  `dvc pull` is done).
- Constraint check: creating two `Person` nodes with the same `personId`
  fails.
- `MATCH (n:Person) WHERE n.pageRank IS NULL RETURN count(n)` returns 0
  after `python -m app.services.compute_centrality`. Same for `Movie`.

## Centrality property name
- The property name written by `compute_centrality.py`, the property
  name read by `api.py::enrich_with_pagerank`, and the property name
  used in the LLM Cypher prompt are **identical** — verified by `grep`.

## Embeddings
- After running `compute_embeddings.py` (and/or `_sage.py`), every node
  in the targeted projection has a non-null embedding vector of the
  expected dimensionality.

## Backwards compatibility
- The existing `POST /chat` smoke queries from the backend feature
  continue to return non-empty subgraphs after this work merges.
