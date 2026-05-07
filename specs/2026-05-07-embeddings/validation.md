# Embeddings — validation

The feature is mergeable when the embeddings beat the current ones on
a frozen evaluation set, the pipeline runs outside a notebook, and the
Neo4j-side artifact is well-formed.

## Frozen baseline (2026-05-07)

Computed from `evaluation.csv` (25 anchors × 10 neighbors = 250 rows,
fully labeled). Labels: `relevant` vs everything else
(`irrelevant` / `unrelated` collapsed). All future runs are measured
against these numbers.

- **Mean precision@10:**   **0.116**
- **Median precision@10:** **0.100**
- **Median shared_crew_count across all 250 (anchor, neighbor) rows:**
  **0**
- **Mean shared_crew_count across all 250 rows:** **0.49**

Headline split — the dominant failure mode:

| neighbor's `shared_crew_count` | rows |  relevant  | precision |
|--------------------------------|-----:|-----------:|----------:|
| `== 0`                         |  218 |          0 |    **0%** |
| `>  0`                         |   32 |         29 | **90.6%** |

Coverage failures:

- Anchors with **≥1 shared-crew neighbor anywhere in top-10:** 15 / 25
- Anchors with **0 relevant neighbors in top-10:** 12 / 25
- Anchors with **median shared_crew_count == 0 in top-10:** 25 / 25

By tag (mean P@10 across the anchors in each tag):

| tag         | n | mean P@10 |
|-------------|--:|----------:|
| classic     | 5 |  0.240    |
| blockbuster | 5 |  0.180    |
| obscure     | 2 |  0.150    |
| arthouse    | 5 |  0.060    |
| auteur      | 5 |  0.040    |
| recent      | 3 |  0.000    |

## Quality bar (the headline check)
- The frozen `evaluation.csv` in this directory is the baseline. A
  new run re-scores the same 25 anchors with the same labeling rules.
- **Mean P@10 must reach ≥ 0.30** (vs baseline 0.116). A ≥10-pt
  absolute lift is the floor; the bar is set higher because the
  baseline is so weak that small gains aren't meaningful.
- **The shared_crew_count split is the load-bearing test.** The new
  embeddings must produce **median shared_crew_count ≥ 1 in top-10
  for ≥ 18 / 25 anchors** (baseline: 0 / 25). Without this, no real
  fix has occurred — the model would just be reshuffling noise.
- **Top-10 coverage of crew-anchored neighbors must rise.** Across
  the 250 (anchor, neighbor) rows, fraction with `shared_crew_count
  > 0` must reach **≥ 50%** (baseline: 32 / 250 = 12.8%).
- **Tag floor:** every tag (`classic`, `blockbuster`, `obscure`,
  `arthouse`, `auteur`, `recent`) must reach mean P@10 ≥ 0.20. The
  current `recent = 0.000` and `auteur = 0.040` rows are the
  acceptance test for whether the long-tail fix actually generalizes
  beyond well-connected mainstream movies.

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
