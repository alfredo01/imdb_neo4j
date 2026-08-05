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
- Clicking a node selects it (drag temporarily pins non-movie nodes).

## Double-click drilldown
- Double-clicking a person node calls `/expand/person/{id}` (verify in the
  Network tab — no `/chat` request is made) and re-renders with that
  person's movies, their actors and directors; the focused node is ringed.
- Double-clicking a movie node calls `/expand/movie/{id}` and re-renders
  with everyone involved in it; directors keep their distinct color, which
  confirms the link labels survived the round-trip.
- A descriptive label lands in the input box ("movies, co-actors and
  directors around X" / "everyone involved in Y").
- Drill-downs chain: expanding a node from an expanded graph works
  repeatedly without stale nodes leaking between views.
- Double-click never triggers a zoom; the graph stays put apart from the
  re-render.
- Expanding a node whose id the backend can't resolve shows the inline
  error and leaves the current graph visible.

## Back / Forward
- After search → person drill-down → movie drill-down, **Back** returns to
  each previous graph in order, restoring the query text with it; the depth
  counter decrements.
- **Forward** replays those steps in order and is greyed out at the tip.
- Both are disabled on the very first graph (nothing to go back to) and
  while a request is in flight.
- Running a new search from a rewound position clears Forward.
- History entries are independent: going back and re-expanding the same
  node produces the same graph, with no leftover state from the branch
  that was discarded.

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