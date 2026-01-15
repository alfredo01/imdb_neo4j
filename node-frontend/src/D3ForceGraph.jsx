import React, { useEffect, useRef, useState } from "react";
import * as d3 from "d3";

function D3ForceGraph({ data, onSelect = () => {} }) {
  const svgRef = useRef();
  const containerRef = useRef();
  const simulationRef = useRef();
  const [dimensions, setDimensions] = useState({ width: 0, height: 0 });
  const [showControls, setShowControls] = useState(true);

  // Force parameters state
  const [linkDistance, setLinkDistance] = useState(100);
  const [chargeStrength, setChargeStrength] = useState(-200);
  const [collideRadius, setCollideRadius] = useState(30);
  const [positionStrength, setPositionStrength] = useState(0.3);

  useEffect(() => {
    const updateDimensions = () => {
      if (containerRef.current) {
        setDimensions({
          width: containerRef.current.offsetWidth,
          height: containerRef.current.offsetHeight
        });
      }
    };

    updateDimensions();
    window.addEventListener('resize', updateDimensions);
    return () => window.removeEventListener('resize', updateDimensions);
  }, []);

  useEffect(() => {
    if (!data || !data.nodes || !data.links || dimensions.width === 0) return;

    const svg = d3.select(svgRef.current);
    svg.selectAll("*").remove();

    const width = dimensions.width;
    const height = dimensions.height;
    const margin = { left: 50, right: 50, top: 40, bottom: 80 };

    // Extract years from movies
    const years = data.nodes
      .filter(d => d.type === "Movie")
      .map(d => +d.year)
      .filter(d => !isNaN(d));

    // Create timeline scale
    const xScale = d3.scaleLinear()
      .domain([d3.min(years) - 1, d3.max(years) + 1])
      .range([margin.left, width - margin.right]);

    // Set initial positions
    data.nodes.forEach(d => {
      if (d.type === "Movie") {
        d.fx = xScale(+d.year); // Fixed x position for movies
        d.y = height / 2;
      } else {
        // People start distributed around center
        d.x = Math.random() * (width - margin.left - margin.right) + margin.left;
        d.y = Math.random() > 0.5 ? height / 2 - 150 : height / 2 + 150;
      }
    });

    // Create force simulation with state-driven parameters
    const simulation = d3.forceSimulation(data.nodes)
      .force("link", d3.forceLink(data.links).id(d => d.id).distance(linkDistance))
      .force("charge", d3.forceManyBody().strength(chargeStrength))
      .force("x", d3.forceX(d => d.type === "Movie" ? xScale(+d.year) : width / 2).strength(positionStrength))
      .force("y", d3.forceY(height / 2).strength(positionStrength * 0.33))
      .force("collide", d3.forceCollide().radius(collideRadius));

    // Store simulation reference
    simulationRef.current = simulation;

    // Create a container group for all graph elements (for zoom/pan)
    const container = svg.append("g");

    // Add zoom and pan behavior
    const zoom = d3.zoom()
      .scaleExtent([0.1, 4])  // Min and max zoom levels
      .filter((event) => {
        // Allow zoom on wheel, prevent on drag (so node dragging works)
        return !event.button && event.type !== 'dblclick';
      })
      .on("zoom", (event) => {
        container.attr("transform", event.transform);
      });

    svg.call(zoom);

    // Draw links
    const link = container.append("g")
      .attr("class", "links")
      .selectAll("line")
      .data(data.links)
      .enter().append("line")
      .attr("stroke", "#999")
      .attr("stroke-opacity", 0.6)
      .attr("stroke-width", 2);

    // Draw nodes
    const node = container.append("g")
      .attr("class", "nodes")
      .selectAll("g")
      .data(data.nodes)
      .enter().append("g")
      .call(d3.drag()
        .on("start", dragstarted)
        .on("drag", dragged)
        .on("end", dragended))
      .on("click", (event, d) => onSelect(d));

    node.append("circle")
      .attr("r", d => d.type === "Movie" ? 35 : 15)
      .attr("fill", d => d.type === "Movie" ? "#f39c12" : "#3498db")
      .attr("stroke", "#fff")
      .attr("stroke-width", 2)
      .style("cursor", "pointer");

    node.append("text")
      .attr("dy", d => d.type === "Movie" ? -40 : -20)
      .attr("text-anchor", "middle")
      .style("font-size", d => d.type === "Movie" ? "16px" : "12px")
      .style("font-weight", d => d.type === "Movie" ? "bold" : "normal")
      .style("pointer-events", "none")
      .text(d => d.label);

    // Draw timeline axis (inside container so it pans/zooms with graph)
    const axis = d3.axisBottom(xScale).tickFormat(d3.format("d"));
    container.append("g")
      .attr("class", "axis")
      .attr("transform", `translate(0,${height - margin.bottom})`)
      .call(axis);

    // Add axis label
    container.append("text")
      .attr("x", width / 2)
      .attr("y", height - margin.bottom + 40)
      .attr("text-anchor", "middle")
      .style("font-size", "14px")
      .style("font-weight", "bold")
      .text("Year");

    // Update positions on simulation tick
    simulation.on("tick", () => {
      link
        .attr("x1", d => d.source.x)
        .attr("y1", d => d.source.y)
        .attr("x2", d => d.target.x)
        .attr("y2", d => d.target.y);

      node.attr("transform", d => `translate(${d.x},${d.y})`);
    });

    // Drag functions
    function dragstarted(event, d) {
      if (!event.active) simulation.alphaTarget(0.3).restart();
      d.fx = d.x;
      d.fy = d.y;
    }

    function dragged(event, d) {
      d.fx = event.x;
      d.fy = event.y;
    }

    function dragended(event, d) {
      if (!event.active) simulation.alphaTarget(0);
      // Keep movies fixed on timeline
      if (d.type !== "Movie") {
        d.fx = null;
        d.fy = null;
      }
    }

    return () => {
      simulation.stop();
    };
  }, [data, onSelect, dimensions, linkDistance, chargeStrength, collideRadius, positionStrength]);

  return (
    <div style={{
      display: "flex",
      flexDirection: "column",
      height: "100%",
      width: "100%",
      margin: 0,
      padding: 0,
      overflow: "hidden"
    }}>
      <div style={{
        padding: "10px 20px",
        background: "#f5f5f5",
        borderBottom: "1px solid #ddd",
        display: "flex",
        justifyContent: "space-between",
        alignItems: "center"
      }}>
        <h2 style={{ margin: 0 }}>Movie Timeline Graph</h2>
        <div style={{ display: "flex", gap: "20px", alignItems: "center" }}>
          <div style={{ display: "flex", alignItems: "center", gap: "5px" }}>
            <div style={{ width: "20px", height: "20px", borderRadius: "50%", background: "#f39c12" }}></div>
            <span>Movies</span>
          </div>
          <div style={{ display: "flex", alignItems: "center", gap: "5px" }}>
            <div style={{ width: "20px", height: "20px", borderRadius: "50%", background: "#3498db" }}></div>
            <span>People</span>
          </div>
          <button
            onClick={() => setShowControls(!showControls)}
            style={{
              padding: "8px 16px",
              background: "#3498db",
              color: "white",
              border: "none",
              borderRadius: "4px",
              cursor: "pointer",
              fontWeight: "bold"
            }}
          >
            {showControls ? "Hide" : "Show"} Force Controls
          </button>
        </div>
      </div>

      {showControls && (
        <div style={{
          padding: "15px 20px",
          background: "#ffffff",
          borderBottom: "1px solid #ddd",
          display: "grid",
          gridTemplateColumns: "repeat(auto-fit, minmax(250px, 1fr))",
          gap: "20px"
        }}>
          <div style={{ display: "flex", flexDirection: "column", gap: "5px" }}>
            <label style={{ fontWeight: "bold", fontSize: "14px" }}>
              Link Distance: <span style={{ color: "#3498db" }}>{linkDistance}</span>
            </label>
            <input
              type="range"
              min="10"
              max="300"
              step="10"
              value={linkDistance}
              onChange={(e) => setLinkDistance(Number(e.target.value))}
              style={{ width: "100%" }}
            />
          </div>

          <div style={{ display: "flex", flexDirection: "column", gap: "5px" }}>
            <label style={{ fontWeight: "bold", fontSize: "14px" }}>
              Charge Strength: <span style={{ color: "#3498db" }}>{chargeStrength}</span>
            </label>
            <input
              type="range"
              min="-1000"
              max="0"
              step="10"
              value={chargeStrength}
              onChange={(e) => setChargeStrength(Number(e.target.value))}
              style={{ width: "100%" }}
            />
          </div>

          <div style={{ display: "flex", flexDirection: "column", gap: "5px" }}>
            <label style={{ fontWeight: "bold", fontSize: "14px" }}>
              Collision Radius: <span style={{ color: "#3498db" }}>{collideRadius}</span>
            </label>
            <input
              type="range"
              min="5"
              max="100"
              step="5"
              value={collideRadius}
              onChange={(e) => setCollideRadius(Number(e.target.value))}
              style={{ width: "100%" }}
            />
          </div>

          <div style={{ display: "flex", flexDirection: "column", gap: "5px" }}>
            <label style={{ fontWeight: "bold", fontSize: "14px" }}>
              Position Force: <span style={{ color: "#3498db" }}>{positionStrength.toFixed(2)}</span>
            </label>
            <input
              type="range"
              min="0"
              max="1"
              step="0.05"
              value={positionStrength}
              onChange={(e) => setPositionStrength(Number(e.target.value))}
              style={{ width: "100%" }}
            />
          </div>
        </div>
      )}
      <div ref={containerRef} style={{ flex: 1, overflow: "hidden" }}>
        <svg
          ref={svgRef}
          width={dimensions.width}
          height={dimensions.height}
          style={{ display: "block" }}
        />
      </div>
    </div>
  );
}

export default D3ForceGraph;
