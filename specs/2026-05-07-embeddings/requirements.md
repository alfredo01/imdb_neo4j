# Embeddings — requirements

> **Anchored in:** [`specs/mission.md`](../mission.md) and
> [`specs/tech-stack.md`](../tech-stack.md). Maps to roadmap **Phase 3
> — Recommendations** (`specs/roadmap.md`). The mission frames
> recommendations as derived from "shared collaborators
> (artist↔artist, actor↔actor, director↔actor)"; this feature owns the
> embedding space that powers that.

## Scope
The pipeline that learns 128-dimensional movie embeddings from the
IMDB graph and writes them back to Neo4j as
`Movie.embeddingSage`, so a downstream `/recommend` endpoint can
return nearest-neighbor movies based on shared crew.

In scope:
- The notebook `notebooks/graphsage_colab.ipynb` (current home of the
  pipeline) and its productionization path into
  `backend/app/services/compute_embeddings_sage.py`.
- Inputs: the IMDB CSV dumps (`movies.csv`, `people_names.csv`,
  `roles.csv`) and the centrality scores already on `Movie` nodes
  (Neo4j feature dir).
- The supervision graph: movie↔movie co-crew pairs, weighted by
  creative role.
- The model: a 2-layer GNN producing 128-d vectors.
- The output artifact: `sage_embeddings.npz` and the Neo4j write that
  populates `Movie.embeddingSage`.

Out of scope:
- The `/recommend` HTTP endpoint and its UI surface (those land in
  the backend / frontend feature dirs once embeddings are good
  enough).
- Person embeddings, band/album embeddings, and any non-cinema use
  case (Phase 2/3 follow-up).
- Cluster detection (Phase 4 — different feature dir).
- Hosting / scheduling the training run. It runs manually on Colab
  GPU; automation is not part of this feature.

## Decisions
- **Co-crew supervision, not person↔movie link prediction.** The loss
  must directly push movies sharing creative crew toward each other;
  the current notebook already adopts this and we keep it.
- **Crew-weighted, role-aware.** Director / writer / composer /
  cinematographer get higher edge weights than actor. The role count
  vector is part of the feature matrix.
- **Movie-only feature matrix.** Person nodes are not surfaced at
  inference time; only the 11.2M movies receive an embedding.
- **128 dimensions.** Big enough to encode crew structure, small
  enough to fit on every movie node and to query at scale. We do not
  retune this without a separate decision.
- **Stored on the node, not in a vector index.** `Movie.embeddingSage`
  is the source of truth. A Neo4j vector index can be layered later;
  no external vector DB.
- **Manual run, manual ingest.** The notebook trains on Colab; the
  resulting `.npz` is uploaded and pushed to the VPS Neo4j with the
  notebook's final cell. Productionizing this into a CLI script is
  part of this feature; scheduling it is not.

## Context — why the current embeddings recommend "too far"

The user's headline pain: recommended movies feel unrelated to the
seed. Working hypotheses, to be confirmed/refuted by the plan:

1. **GCN, not GraphSAGE.** The class is named `MovieGCNEncoder` and
   uses `GCNConv`. Despite the file name, this is GCN, which
   normalizes by degree and behaves differently from GraphSAGE on
   skewed-degree graphs like co-crew.
2. **Random negatives are too easy.** `neg_sampling_ratio=1.0` with
   uniform negatives in an 11M-node graph means most negatives are
   trivially far. The loss converges fast without ever pulling
   positives tightly together.
3. **Subsampled supervision.** Training uses 10M of the 40M co-crew
   edges. Many positive pairs are never seen.
4. **Sparse features.** The 12-d feature vector is mostly zero for
   most movies (only ~6% of movies have centrality; many have no
   role counts). Movies with no co-crew edges effectively get an
   embedding determined by year alone.
5. **Unnormalized dot-product loss.** BCE on raw dot-product means
   embedding magnitude can substitute for direction. Cosine recall
   on the resulting vectors is then noisy.
6. **2-hop neighborhood may be too narrow.** `num_neighbors=[10, 5]`
   on the dense co-crew graph likely undersamples context.
7. **Long-tail movies dominate.** ~75% of movies have zero co-crew
   pair (no eligible shared person ≥2 in the supervision graph) and
   thus learn from features alone; their nearest neighbors are
   essentially "movies from the same year" — exactly the "too far"
   complaint.

The plan addresses these directly.
