# Backend — requirements

> **Anchored in:** [`specs/mission.md`](../mission.md) and
> [`specs/tech-stack.md`](../tech-stack.md). This feature owns the
> "Backend — FastAPI" and "LLM / agent layer" blocks of the **Today**
> stack, including the offline model jobs (centrality, embeddings).
> The roadmap places this in Phase 1 (cinema, hardened) — work here
> must not anticipate Phase 2 (SPARQL) or Phase 3 (recommendations).

## Scope
The FastAPI server, the LLM → Cypher → D3 pipeline, and the offline jobs
that compute graph models (centrality and node embeddings).

In scope:
- HTTP surface in `backend/app/api.py`:
  - `GET /` (health),
  - `POST /chat` (the main entry point),
  - `GET /graph/json` (last subgraph).
- Pipeline modules under `backend/app/services/`:
  - `tools/cypher_to_d3.py` — LLM-driven Cypher generation with
    centrality-aware prompt.
  - `tools/neo4j_to_json.py` — Cypher rows → `{nodes, links}`.
  - `graph.py` — Neo4j driver wrapper.
  - `llm.py` — LLM client / prompt plumbing.
- Offline model jobs:
  - `services/compute_centrality.py` — PageRank, Eigenvector, Degree,
    Betweenness via GDS.
  - `services/compute_embeddings.py` and `compute_embeddings_sage.py` —
    node embeddings via GDS.
- Containerization: `backend/Dockerfile` and the `fastapi` service in
  `docker-compose.yaml`.

Out of scope:
- The Neo4j image, schema, and plugin setup (own feature dir).
- The frontend rendering (own feature dir).
- WIKIDATA / SPARQL backend (future feature).
- A `/recommend` endpoint or `/clusters` endpoint (future phases of the
  roadmap).

## Decisions
- **Single response shape.** Every query path returns a D3-shaped
  payload `{nodes, links, entities}`. No alternative formats exposed.
- **Centrality lives in the prompt.** Result-size control is done by
  the LLM via `ORDER BY ... LIMIT N` clauses, not by post-filtering in
  Python. (See `CENTRALITY_USAGE.md`.)
- **Entity resolution is fuzzy by design.** `rapidfuzz` is used to map
  free-text names to IMDB ids; exact match wins, then fuzzy fallback.
- **Open CORS in dev only.** The wildcard CORS in `api.py` is acceptable
  for the current VPS deploy and must be tightened before any public
  launch.
- **Model jobs are run manually.** `compute_centrality.py` and the
  embeddings scripts are one-shot CLI jobs, not endpoints, and not on a
  schedule.

## Context
- The backend depends on Neo4j being up with APOC and GDS plugins
  loaded; bring-up order is enforced by `docker-compose` `depends_on`.
- `latest_intermediate_steps` is a module-level cache so
  `GET /graph/json` can replay the most recent subgraph without
  re-running the LLM. This is single-process state and not safe under
  multiple workers — a known limitation while `/chat` is the only
  serious caller.
- The frontend is the only consumer of these endpoints today; the JSON
  contract is defined by what `D3ForceGraph.jsx` and `D3TimeLine.jsx`
  expect.