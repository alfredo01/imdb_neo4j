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
2.4  Click a node to select/pin it (drag already pins temporarily).
2.5  Double-click a node to drill down (shipped). Superseded the original
     "generate a query and resubmit through `/chat`" approach — it calls
     the deterministic `/expand/*` endpoints instead.
     - `.on("dblclick", ...)` on the node `<g>` in `D3ForceGraph.jsx`
       calls `onNodeActivate(node)`, passing the whole node; `App`
       dispatches on `node.type` to `/expand/person/{id}` or
       `/expand/movie/{id}` and sets a descriptive label in the query box.
     - Both node types are live; the movie case was the later increment
       and is now done.
     - The handlers are held in refs inside `D3ForceGraph` so `App`
       re-rendering them doesn't tear down and restart the simulation.
     - The D3 zoom `filter` excludes `dblclick`, so drilldown never
       fights zoom.
     - Remaining: a spinner or dimming on the graph itself during the
       fetch (today only the header button shows the loading state).

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
4.4  Back / Forward navigation over the exploration trail (shipped).
     - `history` and `future` stacks of `{data, entities, query}` in
       `App.jsx`; `showGraph()` is the only way to replace the graph, so
       every path — typed query and drill-down alike — is recorded.
     - A `displayedRef` holds the on-screen snapshot. Read it into a local
       *before* any `setState`: functional updaters run later, by which
       point the ref already points at the incoming view, so archiving
       `displayedRef.current` from inside an updater stores the wrong
       snapshot.
     - Buttons sit left of the search input, disabled when their stack is
       empty or a request is in flight, with a depth counter past 1.
     - Remaining: keyboard shortcuts (Alt+←/→) and optionally restoring
       zoom/pan alongside the graph.

## 5. Build & deploy
5.1  Confirm `docker build` picks up `REACT_APP_API_URL` correctly and
     the resulting bundle calls the VPS backend.
5.2  Verify the nginx config serves the SPA correctly (history-mode
     fallback to `index.html`).