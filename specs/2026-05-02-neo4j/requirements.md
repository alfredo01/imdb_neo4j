# Neo4j — requirements

> **Anchored in:** [`specs/mission.md`](../mission.md) and
> [`specs/tech-stack.md`](../tech-stack.md). This feature owns the
> "Graph database — Neo4j" block of the **Today** stack and produces the
> centrality / embedding properties that the mission relies on for
> visual graph exploration. Anything that contradicts those two docs is
> a bug in this spec, not a license to drift.

## Scope
The graph database that stores the IMDB knowledge graph and serves as the
single source of truth for the cinema use case.

In scope:
- The Docker image `aelfred/imdb_neo4j:latest` and its bring-up via
  `docker-compose.yaml`.
- Plugin set: APOC + Graph Data Science (GDS).
- Data layout: `neo4j/data`, `neo4j/plugins`, `neo4j/raw_data`
  (DVC-tracked).
- Schema for the cinema domain: `Person` (actors/directors), `Movie`,
  and the relationships `ACTED_IN`, `DIRECTED`.
- Properties produced by GDS that downstream code reads:
  `pageRank`, `eigenvectorCentrality`, `degreeCentrality`,
  `betweennessCentrality`, plus node embeddings written by
  `compute_embeddings*.py`.

Out of scope:
- WIKIDATA/SPARQL data (handled in a future feature dir).
- Recommendation logic (a separate feature; this dir owns only the data
  Neo4j must expose for it).
- Persisted clusters (community detection lands in its own feature dir
  later in the roadmap).

## Decisions
- **Single Neo4j instance, dev posture.** Auth (`neo4j/adminadmin`) and
  the open APOC import/export flags are accepted for development. They
  must be tightened before any non-VPS deployment.
- **GDS is required, not optional.** Centrality and embeddings are part
  of the contract this feature exposes; the image already ships with the
  plugin.
- **Heavy memory settings stay.** `12G` heap and `2G` transaction max are
  sized for full IMDB; lowering them is out of scope.
- **DVC remains the data transport.** Raw dumps and plugins are tracked
  via `.dvc` files; the repo never carries the binary data directly.

## Context
- Centrality is consumed by the LLM Cypher prompt (see
  `CENTRALITY_USAGE.md`) to keep result subgraphs small enough to render.
- The FastAPI layer reads `betweennessCentrality` to enrich D3 payloads
  (`api.py::enrich_with_pagerank`); the property name discrepancy
  ("pagerank" function, "betweenness" property read) is a known wart to
  reconcile while this feature is open.
- `raw_data/` is mounted into `/var/lib/neo4j/import` so APOC import jobs
  can read fixture files directly.