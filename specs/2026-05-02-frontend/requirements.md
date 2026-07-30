# Frontend — requirements

> **Anchored in:** [`specs/mission.md`](../mission.md) and
> [`specs/tech-stack.md`](../tech-stack.md). This feature owns the
> "Frontend — React + D3" block of the **Today** stack and is the
> surface that delivers the mission's promise — timeline bubble chart
> + force graph for non-technical users. The Streamlit UI is
> deprecated per `tech-stack.md` and is explicitly out of scope.

## Scope
The Node.js / React single-page app under `node-frontend/` that consumes
the FastAPI `/chat` endpoint and renders the result as both a timeline
bubble chart and a force-directed graph.

In scope:
- React 18 app, CRA toolchain (`react-scripts`).
- D3 v7 for both visualizations.
- Components:
  - `App.jsx` — page shell, chat input, history, layout.
  - `D3ForceGraph.jsx` — force-directed graph view.
  - `D3TimeLine.jsx` — timeline bubble chart view.
- HTTP layer: `axios`, base URL from `REACT_APP_API_URL` (build-time
  injected by the Docker build).
- Production serving: nginx (`node-frontend/nginx.conf`), exposed on
  port 80.

Out of scope:
- The legacy Streamlit UI under `streamlit/` (deprecated in
  `tech-stack.md`; no work happens there).
- Any direct Neo4j access from the browser.
- Authentication / session management.
- Recommendations panel and cluster overlays (future feature dirs once
  their backend endpoints exist).

## Decisions
- **Two views, one data shape.** Both `D3ForceGraph` and `D3TimeLine`
  consume the same `{nodes, links}` payload returned by `/chat`.
  Neither component fetches on its own.
- **Node coloring by label.** `Person` and `Movie` use distinct colors;
  no per-property gradients yet.
- **Double-click a node drills down via a generated query.** Double-clicking
  a `Person` node auto-generates and submits a new `/chat` query for that
  person's movie graph — `display the graph of <name> movies`. The person's
  role phrases the query: a director yields "director" framing, an actor
  "actor" framing, but both resolve to that person's movies. Role is derived
  the same way the renderer colors nodes — membership in the `directorIds`
  set built from incoming `DIRECTED` links, not a node property. The
  generated query flows through the normal `App` submit path (loading state,
  history, error handling) exactly as a typed query would; the double-click
  is only a shortcut for typing it. Double-clicking a `Movie` node is a no-op
  for now (movie-centered drilldown is a later increment).
- **Bubble size encodes centrality.** The timeline's bubble radius is
  proportional to `pageRank` (or whichever centrality the Neo4j feature
  settles on).
- **No state management library.** Local component state only; lifting
  to `App.jsx` when shared.
- **Build-time API URL.** `REACT_APP_API_URL` is baked into the bundle
  during `docker build` (see the `args` block in `docker-compose.yaml`).
  Runtime override is not supported.

## Context
- The backend is the only data source; if its response shape changes,
  this feature breaks. The shape is owned by the backend feature dir.
- The VPS deploy serves the frontend on port 80 and the backend on
  port 8000 of the same host; that's why `REACT_APP_API_URL` is set to
  `http://<vps-ip>:8000` at build time.
- The CRA toolchain is showing its age; a Vite migration is plausible
  but explicitly **not** part of this feature.