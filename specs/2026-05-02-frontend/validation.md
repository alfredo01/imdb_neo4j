# Frontend — validation

Run against a backend that already passes its own validation checks.

## Smoke
- `docker-compose up frontend` serves the app on port 80; the page
  loads with no console errors.
- The chat input accepts a query, shows a loading state, then renders
  both a force graph and a timeline.

## Force graph
- Querying two related prompts back-to-back keeps overlapping nodes in
  approximately the same screen position (no full re-layout flicker).
- `Person` and `Movie` nodes are visibly different colors; legend is
  visible.
- Hovering an edge shows the relationship type.
- Click pins a node; double-click releases it.

## Timeline
- The x-axis spans the year range of returned movies.
- Bubble radius visibly varies with the centrality property — verify
  the highest-centrality node has the largest bubble.
- Hovering a node in the force graph highlights the same node in the
  timeline, and vice versa.
- An "unanswerable" query yields the empty-state placeholder, not a
  blank screen or a stack trace.

## Failure modes
- Stopping the backend mid-session produces an inline error message in
  the chat area; neither D3 component crashes the page.
- A malformed response (manually injected via dev tools) is rejected
  with the same inline error; the previous visualization stays
  visible.

## Build
- A clean `docker build` of `node-frontend/` produces a bundle whose
  network calls go to the `REACT_APP_API_URL` baked at build time —
  verified in DevTools Network tab.
- The nginx container serves `/` and any sub-route as `index.html`
  (SPA history fallback works).