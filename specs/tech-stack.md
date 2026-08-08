# Tech stack

Two columns: what is wired up **today** (in this repo, runnable via
`docker-compose`) and what is **planned** (named, scoped, not yet built).
Anything not in either column is out of scope until added here.

## Today

### Graph database — Neo4j
- Image: `aelfred/imdb_neo4j:latest` (preloaded IMDB dump).
- Plugins: **APOC** and **Graph Data Science (GDS)**.
- Bolt on `7687`, HTTP on `7474`. Auth: `neo4j/adminadmin` (dev only).
- Volumes: `neo4j/data`, `neo4j/plugins`, `neo4j/raw_data` (DVC-tracked).
- GDS is used for centrality (PageRank, Eigenvector, Degree) and node
  embeddings (`compute_embeddings.py`, `compute_embeddings_sage.py`).

### Backend — FastAPI
- `backend/app/api.py` exposes `POST /chat` and `GET /graph/json`.
- Pipeline: user message → LLM → Cypher → Neo4j → D3-shaped JSON.
  - `services/tools/cypher_to_d3.py` — LLM-driven Cypher generation with
    centrality-aware prompt (see `CENTRALITY_USAGE.md`).
  - `services/tools/neo4j_to_json.py` — Cypher rows → `{nodes, links}`.
  - `services/graph.py` — Neo4j driver wrapper.
  - `services/compute_centrality.py` — one-shot job to write
    `pageRank` / `eigenvectorCentrality` / `degreeCentrality` onto nodes.
- CORS is fully open (dev posture).
- Deps: `fastapi`, `uvicorn`, `pydantic`, `pandas`, `rapidfuzz`,
  `scikit-learn`, `mlflow`.

### Frontend — React + D3
- `node-frontend/` (CRA, React 18, D3 v7, axios).
- Components: `D3ForceGraph.jsx` (force-directed graph),
  `D3TimeLine.jsx` (timeline bubble chart), `NodeInfoPanel.jsx` (selected
  node's photo + Wikipedia lead), composed in `App.jsx`.
- Served via nginx in production (`nginx.conf`, port 80 → 3000).

### Wikipedia (read-only, browser-side)
- `{lang}.wikipedia.org/api/rest_v1/page/summary/{title}` for the lead
  paragraph and thumbnail; `w/api.php?action=query&list=search` to
  resolve a label to an article title when the direct hit misses;
  `prop=langlinks` to follow an English title to its counterpart in the
  reader's language.
- `{lang}` comes from `navigator.languages`, with `en` as the fallback.
- No key, no quota agreement, CORS-open — called straight from the
  browser, never proxied through FastAPI.
- Strictly decorative: every failure mode degrades to a message in the
  panel, never to a broken graph.

### LLM / agent layer
- `services/llm.py` + `services/tools/cypher_to_d3.py` drive
  natural-language → Cypher with the centrality-filtering prompt.
- Entity resolution uses `rapidfuzz` for fuzzy matching against IMDB names.

### Tooling
- `docker-compose.yaml` orchestrates `neo4j`, `fastapi`, `frontend`.
- `notebooks/` holds exploratory work.
- `tests/` holds the test suite.
- DVC tracks raw Neo4j data (`*.dvc` files).

### Deployment workflow
- Source of truth is a **GitHub repository**; development happens locally
  and is pushed there.
- A **VPS** hosts the running stack. Deploys are a manual `git pull` on the
  VPS followed by `docker-compose up -d --build`.
- The frontend is built with `REACT_APP_API_URL` pointing at the VPS public
  IP (see `docker-compose.yaml`), so the browser bundle calls the VPS
  FastAPI directly.
- No CI/CD pipeline yet; pull-based deploy is intentional for now.

## Planned

### SPARQL adapter for WIKIDATA (and similar)
- A second query backend, parallel to the Cypher path, that targets WIKIDATA
  and other SPARQL endpoints.
- Same output contract: a D3-shaped `{nodes, links}` payload so the existing
  React components render music data with no frontend changes.
- First domain: music (artists, bands, albums, collaborations).

### Recommendation service
- Content-oriented recommendations driven by shared collaborators
  (e.g. "actors who often work with the same directors").
- Backed by graph traversal + node embeddings already produced by
  `compute_embeddings*.py`.

### Cluster detection
- Community detection (GDS Louvain / Leiden) surfaced as a visualization
  layer — color/group nodes by cluster, expose cluster IDs in the API.

## Removed / deprecated
- **Streamlit frontend** (`streamlit/`) — superseded by the React/D3 frontend
  and not part of the active stack. Kept in the repo only as reference; not
  brought up by `docker-compose` (its service block is commented out).