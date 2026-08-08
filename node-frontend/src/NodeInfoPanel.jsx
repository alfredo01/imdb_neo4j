import React, { useEffect, useState } from "react";

// Wikipedia's REST summary endpoint is CORS-open and needs no key: it returns
// the lead paragraph plus a thumbnail, which is exactly the "essential" of an
// article. The search endpoint is the fallback when a label isn't an article
// title (disambiguation, or a movie whose page is "Title (film)").
const WIKI_REST = "https://en.wikipedia.org/api/rest_v1/page/summary/";
const WIKI_SEARCH = "https://en.wikipedia.org/w/api.php";

async function fetchSummary(title, signal) {
  const res = await fetch(WIKI_REST + encodeURIComponent(title.replace(/ /g, "_")), {
    signal,
    headers: { Accept: "application/json" }
  });
  if (!res.ok) return null;
  return res.json();
}

// Ask Wikipedia's search for the best article title for this node. Movies get a
// "film" hint (and their year when known) so "Blow" resolves to the movie, not
// the noun.
async function searchTitle(node, signal) {
  const hint = node.type === "Movie"
    ? `${node.label} ${node.year || ""} film`
    : `${node.label} actor director`;
  const params = new URLSearchParams({
    action: "query",
    list: "search",
    srsearch: hint.trim(),
    srlimit: "1",
    format: "json",
    origin: "*"
  });
  const res = await fetch(`${WIKI_SEARCH}?${params}`, { signal });
  if (!res.ok) return null;
  const body = await res.json();
  const hit = body?.query?.search?.[0];
  return hit ? hit.title : null;
}

// A movie's direct hit is only trusted if the article is actually about a film.
// Bare titles collide with ordinary words — "Nine" resolves to the number, and
// "Sahara" to the desert — so those fall through to the search fallback.
function plausible(node, summary) {
  if (!summary || summary.type === "disambiguation" || !summary.extract) return false;
  if (node.type !== "Movie") return true;
  const blob = `${summary.description || ""} ${summary.extract.slice(0, 200)}`.toLowerCase();
  return blob.includes("film") || blob.includes("movie");
}

// Direct hit first, then search. A disambiguation page counts as a miss: it has
// no useful extract, so fall through to search rather than showing "X may refer
// to...".
async function lookup(node, signal) {
  const direct = await fetchSummary(node.label, signal);
  if (plausible(node, direct)) {
    return direct;
  }
  const title = await searchTitle(node, signal);
  if (title) {
    const found = await fetchSummary(title, signal);
    if (plausible(node, found)) return found;
  }
  // Deliberately not falling back to the rejected direct hit: an honest "no
  // article found" beats confidently showing the Sahara desert under a movie.
  return null;
}

export default function NodeInfoPanel({ node, onClose }) {
  const [summary, setSummary] = useState(null);
  const [status, setStatus] = useState("idle");

  useEffect(() => {
    if (!node || !node.label) return;

    // Clicking through the graph quickly fires overlapping requests; abort the
    // previous one so a slow early response can't overwrite a newer node.
    const controller = new AbortController();
    setStatus("loading");
    setSummary(null);

    lookup(node, controller.signal)
      .then(result => {
        if (controller.signal.aborted) return;
        setSummary(result);
        setStatus(result && result.extract ? "ready" : "empty");
      })
      .catch(err => {
        if (err.name === "AbortError") return;
        console.error("Wikipedia lookup failed:", err);
        setStatus("error");
      });

    return () => controller.abort();
  }, [node]);

  if (!node) return null;

  const isMovie = node.type === "Movie";
  const accent = isMovie ? "#8E44AD" : "#D4A843";

  return (
    <aside style={{
      width: "340px",
      flexShrink: 0,
      height: "100%",
      background: "#ffffff",
      borderLeft: "1px solid #ddd",
      boxShadow: "-2px 0 8px rgba(0,0,0,0.15)",
      display: "flex",
      flexDirection: "column",
      overflow: "hidden"
    }}>
      <header style={{
        padding: "12px 15px",
        borderBottom: `3px solid ${accent}`,
        display: "flex",
        alignItems: "flex-start",
        gap: "10px"
      }}>
        <div style={{ flex: 1 }}>
          <div style={{ fontSize: "17px", fontWeight: "bold", lineHeight: 1.25 }}>
            {node.label}
          </div>
          <div style={{ fontSize: "12px", color: "#777", marginTop: "3px" }}>
            {isMovie ? "Movie" : "Person"}
            {node.year ? ` · ${node.year}` : ""}
          </div>
        </div>
        <button
          onClick={onClose}
          title="Close"
          style={{
            border: "none",
            background: "transparent",
            fontSize: "20px",
            lineHeight: 1,
            cursor: "pointer",
            color: "#888",
            padding: 0
          }}
        >
          ×
        </button>
      </header>

      <div style={{ padding: "15px", overflowY: "auto", flex: 1, fontSize: "14px" }}>
        {status === "loading" && <p style={{ color: "#888" }}>Loading…</p>}

        {status === "error" && (
          <p style={{ color: "#c0392b" }}>
            Could not reach Wikipedia. The graph is unaffected.
          </p>
        )}

        {status === "empty" && (
          <p style={{ color: "#888" }}>
            No Wikipedia article found for “{node.label}”.
          </p>
        )}

        {status === "ready" && summary && (
          <>
            {summary.thumbnail && (
              <img
                src={summary.thumbnail.source}
                alt={node.label}
                style={{
                  width: "100%",
                  maxHeight: "260px",
                  objectFit: "cover",
                  borderRadius: "4px",
                  marginBottom: "12px",
                  background: "#f0f0f0"
                }}
              />
            )}

            {summary.description && (
              <div style={{
                fontStyle: "italic",
                color: "#666",
                marginBottom: "10px",
                fontSize: "13px"
              }}>
                {summary.description}
              </div>
            )}

            <p style={{ lineHeight: 1.5, margin: 0 }}>{summary.extract}</p>

            {summary.content_urls?.desktop?.page && (
              <a
                href={summary.content_urls.desktop.page}
                target="_blank"
                rel="noreferrer"
                style={{
                  display: "inline-block",
                  marginTop: "12px",
                  color: "#3498db",
                  fontSize: "13px"
                }}
              >
                Read on Wikipedia →
              </a>
            )}
          </>
        )}

        <div style={{
          marginTop: "18px",
          paddingTop: "12px",
          borderTop: "1px solid #eee",
          fontSize: "12px",
          color: "#999"
        }}>
          Double-click the node in the graph to explore its connections.
        </div>
      </div>
    </aside>
  );
}
