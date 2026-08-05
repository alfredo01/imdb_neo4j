import React, { useEffect, useRef, useState } from "react";
import * as d3 from "d3";
import D3ForceGraph from "./D3ForceGraph";
import axios from "axios";

// Back/Forward share one look; only the disabled state differs.
function navButtonStyle(disabled) {
  return {
    padding: "10px 18px",
    fontSize: "14px",
    background: "#7f8c8d",
    color: "white",
    border: "none",
    borderRadius: "4px",
    cursor: disabled ? "not-allowed" : "pointer",
    fontWeight: "bold",
    whiteSpace: "nowrap",
    opacity: disabled ? 0.5 : 1
  };
}

export default function App() {
  const [data, setData] = useState(null);
  const [entities, setEntities] = useState(null);
  const [query, setQuery] = useState("Show the graph of Alfred Hitchcock movies, with actors between 1950 and 1960");
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState(null);
  const [messages, setMessages] = useState([]);
  // Stack of previously displayed graphs, so Back can step out of a drill-down
  // chain one level at a time. Each entry is a full snapshot of what the view
  // was showing; the current graph is never in here.
  const [history, setHistory] = useState([]);
  // Views stepped back out of, waiting to be replayed by Forward. Browser
  // semantics: a fresh query or drill-down discards them.
  const [future, setFuture] = useState([]);
  // What is on screen right now. `query` state can't stand in for this: the
  // input is controlled, so it already holds whatever the user has typed next,
  // not the text that produced the visible graph.
  const displayedRef = useRef(null);

  // Apply a stored snapshot to the view.
  function restore(view) {
    displayedRef.current = view;
    setData(view.data);
    setEntities(view.entities);
    setQuery(view.query);
    setError(null);
  }

  // Single entry point for replacing the graph: archives the outgoing view
  // first, so nothing is pushed on the very first query.
  // The outgoing view is read into a local before any setState: the updaters run
  // later, by which point displayedRef.current already points at the new view.
  function showGraph(nextData, nextEntities, nextQuery) {
    const outgoing = displayedRef.current;
    if (outgoing) setHistory(prev => [...prev, outgoing]);
    setFuture([]);
    displayedRef.current = { data: nextData, entities: nextEntities, query: nextQuery };
    setData(nextData);
    setEntities(nextEntities);
    setQuery(nextQuery);
  }

  function handleBack() {
    if (!history.length || loading) return;
    const outgoing = displayedRef.current;
    if (outgoing) setFuture(prev => [...prev, outgoing]);
    setHistory(history.slice(0, -1));
    restore(history[history.length - 1]);
  }

  function handleForward() {
    if (!future.length || loading) return;
    const outgoing = displayedRef.current;
    if (outgoing) setHistory(prev => [...prev, outgoing]);
    setFuture(future.slice(0, -1));
    restore(future[future.length - 1]);
  }

  async function runQuery(queryText) {
    const trimmed = queryText.trim();
    if (!trimmed || loading) return;

    setQuery(trimmed);
    setLoading(true);
    setError(null);

    try {
      const apiUrl = process.env.REACT_APP_API_URL || "http://localhost:8000";
      const response = await axios.post(`${apiUrl}/chat`, {
        message: trimmed,
        history: messages
      });

      const result = response.data;
      console.log("API Response:", result);

      // Update messages
      setMessages([...messages, { user: trimmed, bot: JSON.stringify(result) }]);

      // Update graph data if nodes and links exist
      if (result.nodes && result.links) {
        console.log("Updating graph with:", result.nodes.length, "nodes and", result.links.length, "links");
        showGraph(result, result.entities || entities, trimmed);
      } else {
        console.warn("Response missing nodes or links:", result);
        if (result.entities) setEntities(result.entities);
      }

      // Keep query in the text box for editing
    } catch (err) {
      console.error("Failed to fetch graph data:", err);
      setError(`Failed to get response from the API: ${err.message}`);
    } finally {
      setLoading(false);
    }
  }

  function handleSubmit(e) {
    e.preventDefault();
    runQuery(query);
  }

  function handleSelect(item) {
    console.log("selected node:", item);
  }

  // Double-click a node: drill down into its neighbourhood. A Person expands to
  // their movies plus the main actors and the directors of those movies; a Movie
  // expands to everyone involved in it.
  // This bypasses the LLM: each expansion is always the same shape, so it hits
  // a fixed backend query instead of paying for a Cypher generation round-trip.
  async function handleNodeActivate(node) {
    if (!node || loading) return;
    if (node.type !== "Person" && node.type !== "Movie") return;

    const isPerson = node.type === "Person";
    const path = isPerson ? "person" : "movie";
    const params = isPerson
      ? { movie_limit: 10, actor_limit: 5 }
      : { person_limit: 200 };

    setLoading(true);
    setError(null);

    try {
      const apiUrl = process.env.REACT_APP_API_URL || "http://localhost:8000";
      const response = await axios.get(
        `${apiUrl}/expand/${path}/${encodeURIComponent(node.id)}`,
        { params }
      );

      const result = response.data;
      console.log("Expanded", node.label, "->", result.nodes.length, "nodes");

      if (result.nodes && result.links) {
        showGraph(
          result,
          result.entities || entities,
          isPerson
            ? `movies, co-actors and directors around ${node.label}`
            : `everyone involved in ${node.label}`
        );
      } else if (result.entities) {
        setEntities(result.entities);
      }
    } catch (err) {
      console.error("Failed to expand node:", err);
      setError(`Failed to expand ${node.label}: ${err.message}`);
    } finally {
      setLoading(false);
    }
  }

  return (
    <div style={{ margin: 0, padding: 0, height: "100vh", width: "100vw", overflow: "hidden", display: "flex", flexDirection: "column" }}>
      {/* Chat Input */}
      <div style={{
        padding: "15px 20px",
        background: "#2c3e50",
        borderBottom: "2px solid #34495e",
        display: "flex",
        gap: "10px",
        alignItems: "center"
      }}>
        <form onSubmit={handleSubmit} style={{ display: "flex", gap: "10px", width: "100%" }}>
          <button
            type="button"
            onClick={handleBack}
            disabled={loading || history.length === 0}
            title={history.length ? "Back to the previous graph" : "No previous graph"}
            style={navButtonStyle(loading || history.length === 0)}
          >
            ← Back{history.length > 1 ? ` (${history.length})` : ""}
          </button>
          <button
            type="button"
            onClick={handleForward}
            disabled={loading || future.length === 0}
            title={future.length ? "Forward to the graph you came back from" : "No graph ahead"}
            style={navButtonStyle(loading || future.length === 0)}
          >
            Forward →{future.length > 1 ? ` (${future.length})` : ""}
          </button>
          <input
            type="text"
            value={query}
            onChange={(e) => setQuery(e.target.value)}
            placeholder="Show the graph of Alfred Hitchcock's movies , with actors between 1950 and 1960"
            disabled={loading}
            style={{
              flex: 1,
              padding: "10px 15px",
              fontSize: "14px",
              border: "1px solid #34495e",
              borderRadius: "4px",
              outline: "none"
            }}
          />
          <button
            type="submit"
            disabled={loading || !query.trim()}
            style={{
              padding: "10px 25px",
              fontSize: "14px",
              background: "#3498db",
              color: "white",
              border: "none",
              borderRadius: "4px",
              cursor: loading ? "not-allowed" : "pointer",
              fontWeight: "bold",
              opacity: loading || !query.trim() ? 0.6 : 1
            }}
          >
            {loading ? "Searching..." : "Search"}
          </button>
        </form>
      </div>

      {/* Error Message */}
      {error && (
        <div style={{
          padding: "10px 20px",
          background: "#e74c3c",
          color: "white",
          fontSize: "14px"
        }}>
          {error}
        </div>
      )}

      {/* Graph Visualization */}
      <div style={{ flex: 1, overflow: "hidden" }}>
        {data ? (
          <D3ForceGraph data={data} entities={entities} onSelect={handleSelect} onNodeActivate={handleNodeActivate} />
        ) : (
          <div style={{
            display: "flex",
            alignItems: "center",
            justifyContent: "center",
            height: "100%",
            width: "100%"
          }}>
            <p>Click Search to explore the graph</p>
          </div>
        )}
      </div>
    </div>
  );
}
