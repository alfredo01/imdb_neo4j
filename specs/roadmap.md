# Roadmap

Phases are sliced by **use case**, not by architectural layer. Each phase
ships end-to-end (data → API → UI) before the next one starts. Sub-steps are
deliberately small.

## Phase 1 — Cinema, hardened (current focus)
Make the IMDB experience reliable enough that a new user can land on the
frontend and explore without help.

- 1.1  Lock the `{nodes, links}` JSON contract between FastAPI and the
       React components; document it next to `neo4j_to_json.py`.
- 1.2  Stabilize the LLM → Cypher path: deterministic centrality filtering,
       graceful failure when the query returns nothing.
- 1.3  Polish `D3TimeLine.jsx` — readable axis, bubble sizing tied to
       `pageRank`, hover/click parity with the force graph.
- 1.4  Polish `D3ForceGraph.jsx` — stable layout on re-query, node coloring
       by type (Person vs Movie), edge labels for relationship type.
- 1.5  Add a thin smoke-test suite that hits `/chat` with 5 canonical
       queries and asserts shape of the response.
- 1.6  Tighten dev posture: remove the wildcard CORS in non-dev, move the
       Neo4j password out of `docker-compose.yaml`.
- 1.7  Exploration without typing (done): double-click drill-down on both
       `Person` and `Movie` nodes via the deterministic `/expand/*`
       endpoints, plus Back/Forward over the resulting trail. This is the
       click-through interaction Phase 3 will reuse for recommendations
       (3.4), so the history stacks are worth keeping generic.

## Phase 2 — Music via WIKIDATA / SPARQL
Prove the visualization idiom works on a second domain without re-ingesting
data into Neo4j.

- 2.1  Define the SPARQL query set for music: artist ↔ band, band ↔ album,
       artist ↔ artist collaboration, with date attributes for the timeline.
- 2.2  Build a SPARQL adapter in `backend/app/services/` that returns the
       same `{nodes, links}` shape as the Cypher path.
- 2.3  Route requests by domain: a single `/chat` endpoint dispatches to
       Cypher (cinema) or SPARQL (music) based on detected intent.
- 2.4  Extend the LLM prompt with SPARQL exemplars; reuse the centrality
       idea where WIKIDATA exposes equivalents (e.g. sitelinks, statements
       count) as a popularity proxy.
- 2.5  Verify the React components render music data unchanged; only adjust
       legends/colors for the new node types.

## Phase 3 — Recommendations
Turn the graph into a recommendation surface, layered on the existing
visualization.

- 3.1  Define the recommendation primitive: "given node X, return top-N
       related nodes with a reason path." Reason paths must be renderable
       in the force graph.
- 3.2  Implement collaborator-based recommendation in Cypher (cinema first)
       using shared neighbors and centrality.
- 3.3  Add an embedding-based path using vectors from
       `compute_embeddings_sage.py`; expose a `/recommend` endpoint.
- 3.4  Surface recommendations in the UI as a side panel with click-through
       that re-centers the graph on the chosen recommendation.
- 3.5  Port the recommendation layer to the SPARQL/music adapter.

## Phase 4 — Cluster detection
Make communities a first-class exploration layer.

- 4.1  Run GDS Louvain (and/or Leiden) over the IMDB graph; persist
       `communityId` on nodes.
- 4.2  Expose clusters in the API (`/clusters`, plus `communityId` on every
       node returned by `/chat`).
- 4.3  Color nodes by cluster in both the timeline and the force graph;
       add a cluster filter.
- 4.4  Repeat 4.1–4.3 for the music dataset (run clustering on the
       SPARQL-fetched subgraph at query time, since there is no persistent
       store for music).