# Backend — plan

## 1. Lock the API contract
1.1  Write down the exact JSON shape of `POST /chat` and
     `GET /graph/json` (`nodes[]`, `links[]`, `entities`) next to
     `neo4j_to_json.py`.
1.2  Add Pydantic response models for both endpoints; remove the
     untyped `dict` returns.
1.3  Document the `entities: { persons: [], movies: [] }` payload that
     today is silently passed through from the LLM step.

## 2. Harden the LLM → Cypher path
2.1  Centralize prompt assembly in one module so centrality rules,
     schema description, and few-shot exemplars live in one place.
2.2  On empty result, return a typed `{nodes: [], links: [], reason}`
     instead of an empty dict; do not 500.
2.3  Capture the generated Cypher in the response under a debug-only
     field gated by an env flag.

## 3. Stabilize centrality enrichment
3.1  Replace the hard-coded `betweennessCentrality` lookup in
     `enrich_with_pagerank` with the property name agreed in the Neo4j
     feature dir.
3.2  Skip enrichment when the property is absent on every returned
     node (avoid the unnecessary round-trip).

## 4. Smoke-test the pipeline
4.1  Add 5 canonical `POST /chat` cases under `tests/`:
     specific actor, specific movie, decade query, collaborator query,
     unanswerable query.
4.2  Assert the response is shape-valid (Pydantic) and non-empty for
     the first four.

## 5. Drill-down endpoints (shipped)
5.1  `tools/expand.py` holds the fixed Cypher — `EXPAND_PERSON_CYPHER`
     (person + filmography), `EXPAND_PERSON_CREW_CYPHER` (crew of those
     films), `EXPAND_MOVIE_CYPHER` — plus the node builders that turn
     rows into the `{nodes, links}` contract.
5.2  `GET /expand/person/{person}` (`node_limit`, default 200, clamped
     to 10–500) and `GET /expand/movie/{movie}` (`person_limit` ≤ 200,
     default 200) clamp their params in `api.py` and `404` on an
     unresolvable id/name.
5.3  The person budget is spent in Python, not in Cypher: the movie
     query is capped only by the budget, then `EXPAND_PERSON_CREW_CYPHER`
     is asked for an even per-movie share plus slack, and the fill loop
     decides who fits — directors first, then actors round-robin. Slack
     matters because dedup makes a recurring collaborator free; without
     it the graph stalls well short of the limit.
5.4  Remaining: fold these into the Pydantic response models from §1.2,
     and cover them in the §4 smoke tests (both shapes, plus a movie
     with no cast, a person with more films than the budget, and an
     unknown id).

## 6. Model-job hygiene
6.1  Add a `--dry-run` flag to `compute_centrality.py` that prints
     summary stats without writing to Neo4j.
6.2  Make the script idempotent (safe to re-run; recomputes in place).
6.3  Same treatment for `compute_embeddings.py` and `_sage.py`.

## 7. Dev posture
7.1  Replace wildcard CORS with an env-driven allowlist.
7.2  Move all Neo4j credentials to env vars; remove hard-coded values.