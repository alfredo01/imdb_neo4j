# Neo4j — plan

## 1. Lock the schema contract
1.1  Document node labels (`Person`, `Movie`) and relationships
     (`ACTED_IN`, `DIRECTED`) with their property sets in this directory.
1.2  Enumerate the GDS-derived properties the rest of the system depends
     on (`pageRank`, `eigenvectorCentrality`, `degreeCentrality`,
     `betweennessCentrality`, embedding vectors).
1.3  Add Cypher constraints/indices for `Person.personId` and
     `Movie.movieId` so lookups in `api.py::enrich_with_pagerank` stay
     O(1).

## 2. Reconcile the centrality property naming
2.1  Decide on a single property name for the centrality score the
     backend consumes (current code mixes `pageRank` vs.
     `betweennessCentrality`).
2.2  Update `compute_centrality.py` to write the agreed name.
2.3  Update `api.py::enrich_with_pagerank` and the Cypher prompt to read
     the same name.

## 3. Make the bring-up reproducible
3.1  Verify `docker-compose up neo4j` from a clean checkout reaches a
     healthy state with APOC + GDS loaded.
3.2  Add a one-line health check: `CALL gds.version()` and
     `RETURN apoc.version()` succeed.
3.3  Document the `dvc pull` step required before first bring-up.

## 4. Tighten dev posture (non-blocking, but tracked here)
4.1  Move `NEO4J_AUTH` to an env var sourced from `.env`.
4.2  Restrict APOC `*_file_enabled` flags to `true` only in dev compose
     overrides.
