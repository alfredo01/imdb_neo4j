import React, { useEffect, useRef, useState } from "react";
import * as d3 from "d3";
import { displayLabel } from "./titles";
import { t } from "./i18n";

// Scatter plot of a /recommend/movie payload.
//
// The backend projects the films into 2D with PCA over their crew-membership
// vectors, and the cosine between those same vectors is what the ranking sorts
// by — so proximity here means the same thing as position in the list. The seed
// film's nearest neighbour on screen is its top recommendation.
//
// The axes are deliberately unlabelled. They are principal components, not
// quantities: PC1 on a Hitchcock query happens to sort by crew generation, but
// that is an emergent property of one result set, not something to name on a
// tick. What the axes mean is exactly "distance = shared crew", which is what
// the caption says.

const MARGIN = { top: 48, right: 32, bottom: 44, left: 32 };
const SEED_COLOR = "#E74C3C";
const MOVIE_COLOR = "#8E44AD";

function RecommendationPlot({ payload, title, onSelect = () => {}, onClose = () => {} }) {
  const containerRef = useRef();
  const svgRef = useRef();
  const [size, setSize] = useState({ width: 0, height: 0 });

  // App re-creates onSelect on every render; holding it in a ref keeps it out
  // of the draw effect's dependencies, which would otherwise redraw the plot on
  // every parent render. Same reasoning as D3ForceGraph.
  const onSelectRef = useRef(onSelect);
  onSelectRef.current = onSelect;

  // Match D3ForceGraph: measure the container rather than assuming a size, so
  // the plot reflows when the info panel opens beside it.
  useEffect(() => {
    if (typeof ResizeObserver === "undefined" || !containerRef.current) return;
    const observer = new ResizeObserver(entries => {
      const box = entries[0].contentRect;
      setSize({ width: box.width, height: box.height });
    });
    observer.observe(containerRef.current);
    return () => observer.disconnect();
  }, []);

  useEffect(() => {
    const svg = d3.select(svgRef.current);
    svg.selectAll("*").remove();

    const { width, height } = size;
    const points = (payload?.nodes || []).filter(
      n => Number.isFinite(n.x) && Number.isFinite(n.y)
    );
    if (!width || !height || points.length === 0) return;

    // Equal scaling on both axes. A separate d3.extent per axis would stretch
    // whichever direction happens to have less spread, and distance is the only
    // thing this chart is claiming to show — distorting it would be a lie.
    const xs = points.map(p => p.x);
    const ys = points.map(p => p.y);
    const spread = Math.max(
      d3.max(xs) - d3.min(xs),
      d3.max(ys) - d3.min(ys),
      1e-6
    ) * 1.15;
    const cx = (d3.max(xs) + d3.min(xs)) / 2;
    const cy = (d3.max(ys) + d3.min(ys)) / 2;
    const plotW = Math.max(width - MARGIN.left - MARGIN.right, 10);
    const plotH = Math.max(height - MARGIN.top - MARGIN.bottom, 10);
    const side = Math.min(plotW, plotH);
    const offsetX = MARGIN.left + (plotW - side) / 2;
    const offsetY = MARGIN.top + (plotH - side) / 2;

    const xScale = d3.scaleLinear()
      .domain([cx - spread / 2, cx + spread / 2])
      .range([offsetX, offsetX + side]);
    const yScale = d3.scaleLinear()
      .domain([cy - spread / 2, cy + spread / 2])
      .range([offsetY + side, offsetY]);

    const root = svg.append("g");

    // Faint crosshair through the centroid: gives the eye a reference for
    // "which side" without implying the axes carry units.
    const guides = root.append("g").attr("stroke", "#e5e5e5").attr("stroke-width", 1);
    guides.append("line")
      .attr("x1", offsetX).attr("x2", offsetX + side)
      .attr("y1", yScale(cy)).attr("y2", yScale(cy));
    guides.append("line")
      .attr("x1", xScale(cx)).attr("x2", xScale(cx))
      .attr("y1", offsetY).attr("y2", offsetY + side);

    const seedId = payload.center;
    const groups = root.selectAll("g.point")
      .data(points, d => d.id)
      .join("g")
      .attr("class", "point")
      .attr("transform", d => `translate(${xScale(d.x)}, ${yScale(d.y)})`)
      .style("cursor", "pointer")
      .on("click", (event, d) => onSelectRef.current(d));

    groups.append("circle")
      .attr("r", d => (d.id === seedId ? 9 : 6))
      .attr("fill", d => (d.id === seedId ? SEED_COLOR : MOVIE_COLOR))
      .attr("stroke", "#fff")
      .attr("stroke-width", 2);

    groups.append("title")
      .text(d => {
        const name = displayLabel(d);
        if (d.id === seedId) return name;
        const shared = d.sharedWith?.length
          ? ` — ${d.sharedWith.join(", ")}`
          : "";
        return `${name}\n${t("sharedCrew", { count: d.sharedCount ?? 0 })}${shared}`;
      });

    groups.append("text")
      .text(d => displayLabel(d))
      .attr("x", 0)
      .attr("y", d => (d.id === seedId ? -15 : -11))
      .attr("text-anchor", "middle")
      .style("font-size", d => (d.id === seedId ? "13px" : "11px"))
      .style("font-weight", d => (d.id === seedId ? 700 : 400))
      .style("fill", "#222")
      .style("paint-order", "stroke")
      .style("stroke", "#fff")
      .style("stroke-width", "3px")
      .style("pointer-events", "none");
  }, [payload, size]);

  const projection = payload?.projection;
  const points = (payload?.nodes || []).filter(n => Number.isFinite(n.x));
  const empty = points.length === 0;

  return (
    <div style={{
      position: "absolute",
      inset: 0,
      background: "#fff",
      display: "flex",
      flexDirection: "column",
      zIndex: 5
    }}>
      <div style={{
        padding: "10px 20px",
        borderBottom: "1px solid #ddd",
        display: "flex",
        justifyContent: "space-between",
        alignItems: "center",
        gap: "16px"
      }}>
        <div style={{ minWidth: 0 }}>
          <div style={{ fontSize: "17px", fontWeight: 600, color: "#222" }}>
            {t("similarTo", { title })}
          </div>
          {projection && (
            <div style={{ fontSize: "12px", color: "#777", marginTop: "2px" }}>
              {t("projectionNote", {
                variance: Math.round(projection.varianceExplained * 100)
              })}
            </div>
          )}
        </div>
        <button
          onClick={onClose}
          style={{
            padding: "8px 16px",
            background: "#8E44AD",
            color: "white",
            border: "none",
            borderRadius: "4px",
            cursor: "pointer",
            fontWeight: "bold",
            flexShrink: 0
          }}
        >
          {t("close")}
        </button>
      </div>

      <div ref={containerRef} style={{ flex: 1, minHeight: 0, position: "relative" }}>
        {empty ? (
          <div style={{
            display: "flex", alignItems: "center", justifyContent: "center",
            height: "100%", color: "#777"
          }}>
            {t("noRecommendations")}
          </div>
        ) : (
          <svg ref={svgRef} width={size.width} height={size.height} />
        )}
      </div>
    </div>
  );
}

export default RecommendationPlot;
