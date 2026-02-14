import React, { useEffect, useState } from "react";
import * as d3 from "d3";
import D3ForceGraph from "./D3ForceGraph";
import axios from "axios";

export default function App() {
  const [data, setData] = useState(null);
  const [query, setQuery] = useState("Show the graph of Alfred Hitchcock's movies, with actors between 1950 and 1960");
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState(null);
  const [messages, setMessages] = useState([]);

  async function handleSubmit(e) {
    e.preventDefault();
    if (!query.trim()) return;

    setLoading(true);
    setError(null);

    try {
      const apiUrl = process.env.REACT_APP_API_URL || "http://localhost:8000";
      const response = await axios.post(`${apiUrl}/chat`, {
        message: query,
        history: messages
      });

      const result = response.data;
      console.log("API Response:", result);

      // Update messages
      setMessages([...messages, { user: query, bot: JSON.stringify(result) }]);

      // Update graph data if nodes and links exist
      if (result.nodes && result.links) {
        console.log("Updating graph with:", result.nodes.length, "nodes and", result.links.length, "links");
        setData(result);
      } else {
        console.warn("Response missing nodes or links:", result);
      }

      // Keep query in the text box for editing
    } catch (err) {
      console.error("Failed to fetch graph data:", err);
      setError(`Failed to get response from the API: ${err.message}`);
    } finally {
      setLoading(false);
    }
  }

  function handleSelect(item) {
    console.log("selected node:", item);
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
          <D3ForceGraph data={data} onSelect={handleSelect} />
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
