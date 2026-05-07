# Embeddings — plan

Numbered task groups. Earlier groups establish a measurement floor
before later groups change the model — otherwise we cannot tell
whether a change actually helps.

## 1. Establish a recommendation quality baseline
1.1  Pick 20–30 anchor movies that span eras, languages, and crew
     density (a few mainstream, a few arthouse, a few obscure).
1.2  For each anchor, compute top-10 nearest neighbors with the
     **current** `embeddingSage` using cosine similarity.
1.3  Manually label each neighbor as `relevant` / `loose` /
     `unrelated`. Record in `evaluation.csv` next to the notebook.
1.4  Define two metrics off this set: **precision@10** (relevant
     fraction) and **median crew overlap** (count of crew shared
     between anchor and each neighbor).
1.5  Freeze these baseline numbers in `validation.md` so later runs
     are measured against a fixed bar.

## 2. Diagnose the dominant failure mode
2.1  Bucket the 30 anchors by co-crew degree (0, 1–5, 6–20, 20+) and
     recompute precision@10 per bucket. This tells us whether the
     "too far" complaint is universal or concentrated in low-degree
     movies.
2.2  Compare cosine vs. dot-product ranking on the same anchors. If
     cosine is materially better, magnitude is leaking into the
     score and we have to normalize.
2.3  Sanity-check feature contribution: re-rank using **only** the
     12-d feature matrix (no GNN). If GNN ranking is barely better
     than feature-only, the message-passing step is contributing
     little and group 4/5 changes become high-priority.

## 3. Productionize the notebook
Even if the model needs work, the orchestration must move out of a
notebook so iterations are reproducible.
3.1  Port `notebooks/graphsage_colab.ipynb` into
     `backend/app/services/compute_embeddings_sage.py` as a CLI:
     `python -m app.services.compute_embeddings_sage --epochs N
     --device cuda`.
3.2  Keep the Colab notebook as a thin runner that imports the same
     module — single source of truth for the training code.
3.3  Externalize hyperparameters (embed dim, neighbors, edge cap,
     supervision filters) into a small dataclass / YAML.
3.4  Idempotent Neo4j write: clear `embeddingSage` then re-write,
     wrapped in a single transactional helper, callable from the
     CLI with `--push-neo4j`.

## 4. Improve supervision (most likely lever)
4.1  Switch from random negatives to **hard negatives**: for each
     positive movie pair `(a, b)`, sample negatives from movies
     within ±N years of `a` that **do not** share crew. This forces
     the model to separate look-alike-but-unrelated pairs.
4.2  Raise the supervision sample from 10M → 30M edges (or train on
     all 40M with smaller batches if VRAM allows).
4.3  Tighten the eligibility filter: drop persons with > 25 movies
     (current cap is 50) — mega-collaborators add noise.
4.4  Reweight positives by **role rarity** (a shared composer is
     more discriminative than a shared producer); use IDF over
     person→movie counts.

## 5. Improve the model
5.1  Replace `GCNConv` with `SAGEConv` (true GraphSAGE — the file
     name's promise). Mean aggregator, then try max.
5.2  L2-normalize embeddings before the loss; switch BCE on
     dot-product to either **InfoNCE** (temperature 0.1) or **margin
     ranking** on cosine. This addresses the magnitude leak from
     hypothesis 5.
5.3  Widen the neighborhood: `num_neighbors=[15, 10, 5]` (3 hops),
     and add a third conv layer.
5.4  Stronger features for the cold-start tail: add a learnable
     embedding lookup per movie (id-embedding concatenated with the
     12-d structural features). For movies with no edges, this lets
     the GNN at least learn something rather than collapsing to the
     year prior.

## 6. Re-evaluate and decide what ships
6.1  Re-run the baseline (group 1) on the new embeddings.
6.2  Compare precision@10 and median crew overlap, per bucket from
     2.1. We need a meaningful lift on the **low-degree** bucket —
     that's where "too far" lives.
6.3  If lift holds: push to Neo4j as `embeddingSage`, archive the
     old vectors as `embeddingSageV1` for one cycle, then drop.
6.4  If lift doesn't hold: write up the dead end in this dir,
     identify which hypothesis from `requirements.md §Context` was
     actually responsible, and open a follow-up spec.
