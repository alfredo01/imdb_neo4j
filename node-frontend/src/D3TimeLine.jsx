import React, { useEffect, useRef } from "react";
import * as d3 from "d3";

function D3Timeline({ data = [], onSelect = () => {} }) {
  const ref = useRef();

  useEffect(() => {
    const svg = d3.select(ref.current);
    svg.selectAll("*").remove(); // Clear previous render

    if (!data.length) return;

    const width = 800;
    const height = 200;
    const margin = { left: 50, right: 50, top: 20, bottom: 40 };

    // xScale for numeric years
    const xScale = d3.scaleLinear()
      .domain(d3.extent(data, d => d.year))
      .range([margin.left, width - margin.right]);

    // axis
    svg.append("g")
      .attr("transform", `translate(0, ${height - margin.bottom})`)
      .call(d3.axisBottom(xScale).tickFormat(d3.format("d")));

    // circles with join and key function
    svg.selectAll("circle")
      .data(data, d => d.id)
      .join("circle")
      .attr("cx", d => xScale(d.year))
      .attr("cy", height / 2)
      .attr("r", 8)
      .attr("fill", "#3498db")
      .style("cursor", "pointer")
      .on("click", (event, d) => onSelect(d));

    // optional labels
    svg.selectAll("text.label")
      .data(data, d => d.id)
      .join("text")
      .attr("class", "label")
      .attr("x", d => xScale(d.year))
      .attr("y", height / 2 - 14)
      .attr("text-anchor", "middle")
      .text(d => d.label ?? d.year)
      .style("font-size", "11px");

  }, [data, onSelect]);

  return <svg ref={ref} width={800} height={200} />;
}

export default D3Timeline;
