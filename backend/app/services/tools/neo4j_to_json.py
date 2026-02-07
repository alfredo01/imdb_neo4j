def to_d3_format(results):
    nodes = {}
    links = []

    for record in results:
        for key in record:
            value = record[key]

            # Add nodes
            if isinstance(value, dict) and ("personId" in value or "movieId" in value):
                node_id = value.get("personId") or value.get("movieId")
                if node_id not in nodes:
                    node = {
                        "id": node_id,
                        "label": value.get("name") or value.get("title"),
                        "type": "Person" if "personId" in value else "Movie"
                    }
                    if node["type"] == "Movie" and "year" in value:
                        node["year"] = value["year"]
                    if "eigenvectorCentrality" in value:
                        node["eigenvectorCentrality"] = value["eigenvectorCentrality"]
                    nodes[node_id] = node

            # Add relationships
            elif isinstance(value, tuple) and len(value) == 3:
                src, rel, tgt = value
                src_id = src.get("personId") or src.get("movieId")
                tgt_id = tgt.get("personId") or tgt.get("movieId")
                links.append({
                    "source": src_id,
                    "target": tgt_id,
                    "label": rel
                })

    return {
        "nodes": list(nodes.values()),
        "links": links
    }
