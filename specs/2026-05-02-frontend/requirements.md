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
  - `App.jsx` — page shell, chat input, exploration history
    (Back/Forward), drill-down dispatch, selection, layout.
  - `D3ForceGraph.jsx` — force-directed graph view.
  - `D3TimeLine.jsx` — timeline bubble chart view.
  - `NodeInfoPanel.jsx` — side panel with the selected node's photo and
    Wikipedia lead paragraph.
- HTTP layer: `axios`, base URL from `REACT_APP_API_URL` (build-time
  injected by the Docker build). The one exception is the Wikipedia
  lookup, which the panel calls directly with `fetch`.
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
- **Single click opens an info panel; the content comes from Wikipedia.**
  The graph answers "who is connected to whom" but says nothing about who
  a person actually is, and the IMDB dump carries no biography or image.
  Wikipedia's REST summary endpoint (`/api/rest_v1/page/summary/{title}`)
  supplies both: it is CORS-open, needs no key, and returns exactly the
  lead paragraph plus a thumbnail. Called straight from the browser — a
  backend proxy would add a hop and a cache to maintain for data that is
  neither private nor tied to our graph. Actors and directors are the
  target; `Movie` nodes use the same path for free.
- **Wikipedia titles are matched, not assumed.** A node label is not an
  article title. People usually resolve directly (verified: Penélope Cruz,
  Antonio Banderas, Javier Bardem, Pedro Almodóvar, Woody Allen, Jane
  Birkin). Bare movie titles collide with ordinary words — "Nine" is a
  number, "Sahara" a desert — so a `Movie` hit is accepted only when the
  description or lead mentions a film; otherwise the search API resolves
  it (`Blow` → `Blow (film)`, `Nine` → `Nine (2009 live-action film)`).
  When nothing plausible is found the panel says so rather than
  displaying the wrong article, which is the failure users would not
  catch.
- **The article follows the reader's language, English when it doesn't
  exist.** `navigator.languages` is reduced to base subtags (`fr-CA` →
  `fr`) and tried in order against the matching Wikipedia edition, with
  `en` always appended last — it is the largest edition, so it is the
  best fallback when the reader's own has no article. Two consequences
  shape the implementation:
  - The "is this a film?" check and the search hint are language-specific
    (`película` in Spanish, `фильм` in Russian), so a per-language word
    list backs both. Unknown languages fall back to "film", which many
    editions borrow anyway.
  - Our labels are IMDB's English titles, which are not the local article
    titles. So when only English resolves, one `langlinks` hop asks
    English for its translated counterpart — the only way to reach
    `Tout sur ma mère` or `Todo sobre mi madre` from "All About My
    Mother". Verified end to end for `fr` and `es` readers.
  Cost is 1–2 requests for a person in their own language, up to 4 for a
  movie that needs the English hop. Acceptable for a click-driven panel;
  it would not be for anything on the render path.
- **Selection is click, exploration is double-click.** Both gestures live
  on the same node, and a double-click necessarily emits two clicks, so
  the select is held 250 ms and dropped if the second click arrives —
  otherwise every drill-down would also fire a Wikipedia request.
- **Double-click a node drills down via a dedicated endpoint, not the
  LLM.** Superseded the original design, which generated a natural-language
  query and pushed it back through `/chat`. An expansion always means the
  same thing, so it hits fixed backend Cypher instead: `Person` →
  `GET /expand/person/{id}` (their whole filmography, then as much crew as
  fits, `node_limit=200`), `Movie` → `GET /expand/movie/{id}` (everyone
  involved in it, `person_limit=200`). Both views are therefore bounded at
  200 nodes, which is the practical ceiling for a readable force layout. This removes a Cypher-generation round-trip and
  makes the result reproducible — the same node always expands to the same
  graph. `D3ForceGraph` stays presentation-only: it reports the whole node
  via `onNodeActivate(node)` and `App` decides which endpoint to call.
- **Back/Forward navigate the exploration trail.** Drill-downs chain, so
  the view keeps a `history` stack and a `future` stack of `{data,
  entities, query}` snapshots, with browser semantics: a new query or
  drill-down clears `future`. Every graph replacement goes through one
  `showGraph()` function so no path can bypass the history. The snapshot's
  query text is tracked in a ref rather than read from the `query` state —
  the input is controlled, so that state already holds whatever the user
  has typed next, not the text that produced the visible graph.
  Deliberately *not* rewound: the `messages` chat history sent to the LLM.
  Back is view navigation; silently rolling back conversational context
  would change what a follow-up question means.
- **Bubble size encodes centrality.** The timeline's bubble radius is
  proportional to `pageRank` (or whichever centrality the Neo4j feature
  settles on).
- **No state management library.** Local component state only; lifting
  to `App.jsx` when shared.
- **Build-time API URL.** `REACT_APP_API_URL` is baked into the bundle
  during `docker build` (see the `args` block in `docker-compose.yaml`).
  Runtime override is not supported.

## Context
- The backend owns everything the graph draws; if its response shape
  changes, this feature breaks. The shape is owned by the backend feature
  dir. Wikipedia is the one other source, and it is strictly decorative:
  the panel failing leaves the graph fully usable.
- The VPS deploy serves the frontend on port 80 and the backend on
  port 8000 of the same host; that's why `REACT_APP_API_URL` is set to
  `http://<vps-ip>:8000` at build time. The page is plain HTTP while
  Wikipedia is HTTPS — allowed in that direction (mixed-content rules
  block the reverse), so no proxy is needed for the panel to work.
- The CRA toolchain is showing its age; a Vite migration is plausible
  but explicitly **not** part of this feature.