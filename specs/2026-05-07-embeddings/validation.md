# Embeddings — validation

The feature is mergeable when the embeddings beat the current ones on
a frozen evaluation set, the pipeline runs outside a notebook, and the
Neo4j-side artifact is well-formed.

## Quality bar (the headline check)
- A frozen `evaluation.csv` exists in this directory listing 20–30
  anchor movies and their human-labeled top-10 neighbors under the
  **baseline** `embeddingSage` (recorded in group 1 of `plan.md`).
- After the new run, the same anchors are re-scored against the
  **new** `embeddingSage` with the same labeling rules.
- **Aggregate precision@10 must improve by ≥10 absolute points.**
- **Per-bucket check (by co-crew degree of the anchor):** the
  low-degree bucket (0–5 co-crew edges) — where the "too far"
  complaint is concentrated — must improve by ≥10 absolute points
  too. A model that only fixes the head-of-distribution does not
  ship.
- **Median crew overlap** between an anchor and its top-10 neighbors
  must be strictly higher than the baseline.

## Artifact correctness
- After `python -m app.services.compute_embeddings_sage --push-neo4j`:
  - `MATCH (m:Movie) WHERE m.embeddingSage IS NULL RETURN count(m)`
    returns `0`.
  - Every vector has length `128`.
  - Random sample of 100 vectors: no NaN, no Inf, L2 norm in a sane
    band (e.g. `[0.5, 5.0]` or all `1.0` if the model normalizes
    output).
  - `MATCH (m:Movie) WHERE m.embeddingSageV1 IS NOT NULL RETURN
    count(m) > 0` — old vectors archived (only the run that
    successfully replaces them archives the previous version).

## Pipeline reproducibility
- The training code lives in
  `backend/app/services/compute_embeddings_sage.py` and is invokable
  as `python -m app.services.compute_embeddings_sage` with a `--help`
  that lists all hyperparameters.
- The Colab notebook imports from that module and contains no model
  code of its own.
- Re-running with the same seed and config produces vectors whose
  pairwise cosine ranking on the 30 anchors is identical (the
  embeddings themselves can differ up to floating-point noise).

## Operational
- A full run on Colab A100 (or equivalent) completes in under 90
  minutes wall-clock for 10 epochs.
- The `.npz` artifact is < 2 GB (current run is 1.6 GB — keep it in
  that range or smaller).
- The Neo4j write completes within 60 minutes against the VPS.

## Documentation
- `requirements.md §Context` lists which of the seven hypotheses
  turned out to be the load-bearing cause of "too far," confirmed
  with numbers from group 2 of `plan.md`. A spec that improves
  quality without explaining *why* is not done.
