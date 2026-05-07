# Frontend — plan

## 1. Pin the data contract
1.1  Add a tiny `types.js` (or JSDoc block) describing the
     `{nodes, links, entities}` shape consumed from `/chat`.
1.2  Reject malformed responses defensively in `App.jsx` (show an
     inline error, do not crash either D3 component).

## 2. Polish the force graph
2.1  Stable layout on re-query: re-use existing node positions when
     ids overlap between successive responses.
2.2  Color nodes by label (`Person` vs `Movie`); legend in a corner.
2.3  Edge label on hover showing the relationship type.
2.4  Click a node to pin it; double-click to release.

## 3. Polish the timeline
3.1  Time axis driven by `Movie.year` for cinema; bubble radius from
     the agreed centrality property.
3.2  Hover parity with the force graph: hovering a node in one view
     highlights it in the other.
3.3  Empty-result placeholder ("No matches — try rephrasing.").

## 4. Chat UX
4.1  Persist conversation history in component state across queries
     (already partly there in `App.jsx` — confirm and tidy).
4.2  Show a loading state while `/chat` is in flight; disable submit.
4.3  Surface the backend's `entities` field as a small chips row above
     the visualizations.

## 5. Build & deploy
5.1  Confirm `docker build` picks up `REACT_APP_API_URL` correctly and
     the resulting bundle calls the VPS backend.
5.2  Verify the nginx config serves the SPA correctly (history-mode
     fallback to `index.html`).