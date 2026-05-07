"""
Group 1 baseline evaluation for `embeddingSage`.

Spec: specs/2026-05-07-embeddings/plan.md  (group 1)

Reads (no Neo4j needed):
  - sage_embeddings.npz                  (movie_ids, embeddings)
  - neo4j/raw_data/movies.csv            (movieId:ID, title, year, :LABEL)
  - neo4j/raw_data/roles.csv             (:START_ID, role, :END_ID, :TYPE)
  - neo4j/raw_data/people_names.csv      (personId:ID, name, ...)

Writes:
  - evaluation.csv                       (one row per (anchor, neighbor) pair)

Run:
  python baseline_eval.py \
      --embeddings sage_embeddings.npz \
      --raw-data ../neo4j/raw_data \
      --out evaluation.csv

Memory note:
  np.savez_compressed cannot be memory-mapped; the embeddings array
  (11.2M x 128 float32 ~= 5.7 GB) is fully loaded. ~8 GB free RAM
  recommended.
"""

from __future__ import annotations

import argparse
import csv
import sys
import time
from pathlib import Path

import numpy as np
import pandas as pd

# ---------------------------------------------------------------------------
# Curated anchor set. 25 movies spanning eras, languages, and crew density.
# Tag is informational — actual crew density is computed at runtime and
# reported in the output CSV (anchor_crew_count column).
# Edit freely; just keep the (movieId, year, title, tag) tuple shape.
# ---------------------------------------------------------------------------
ANCHORS: list[tuple[str, int, str, str]] = [
    # mainstream / blockbuster (high crew density expected)
    ("tt0468569", 2008, "The Dark Knight",                  "blockbuster"),
    ("tt1375666", 2010, "Inception",                        "blockbuster"),
    ("tt0110912", 1994, "Pulp Fiction",                     "blockbuster"),
    ("tt0068646", 1972, "The Godfather",                    "blockbuster"),
    ("tt0076759", 1977, "Star Wars: Episode IV",            "blockbuster"),

    # classics (older, dense)
    ("tt0033467", 1941, "Citizen Kane",                     "classic"),
    ("tt0034583", 1942, "Casablanca",                       "classic"),
    ("tt0047478", 1954, "Seven Samurai",                    "classic"),
    ("tt0062622", 1968, "2001: A Space Odyssey",            "classic"),
    ("tt0046438", 1953, "Tokyo Story",                      "classic"),

    # arthouse / international
    ("tt6751668", 2019, "Parasite",                         "arthouse"),
    ("tt0245429", 2001, "Spirited Away",                    "arthouse"),
    ("tt0211915", 2001, "Amelie",                           "arthouse"),
    ("tt0118694", 2000, "In the Mood for Love",             "arthouse"),
    ("tt0056801", 1963, "8 1/2",                            "arthouse"),

    # auteur / niche
    ("tt0166924", 2001, "Mulholland Drive",                 "auteur"),
    ("tt7984734", 2019, "The Lighthouse",                   "auteur"),
    ("tt0084787", 1982, "The Thing",                        "auteur"),
    ("tt0053198", 1959, "The 400 Blows",                    "auteur"),
    ("tt1832382", 2011, "A Separation",                     "auteur"),

    # recent / mixed
    ("tt6710474", 2022, "Everything Everywhere All at Once","recent"),
    ("tt1160419", 2021, "Dune",                             "recent"),
    ("tt1392190", 2015, "Mad Max: Fury Road",               "recent"),
    ("tt0048473", 1955, "Pather Panchali",                  "obscure"),
    ("tt0060827", 1966, "Persona",                          "obscure"),
]

KEPT_ROLE_TYPES = {
    "ACTED_IN", "DIRECTED", "PRODUCED", "WROTE",
    "COMPOSED", "EDITED", "CINEMATOGRAPHER",
}
TOP_K = 10
NN_CHUNK = 1_000_000      # rows per dot-product chunk
ROLES_CHUNK = 5_000_000   # rows per pandas chunk on roles.csv


def log(msg: str) -> None:
    print(f"[{time.strftime('%H:%M:%S')}] {msg}", flush=True)


def load_embeddings(path: Path) -> tuple[np.ndarray, np.ndarray]:
    log(f"loading embeddings from {path} ...")
    data = np.load(path, allow_pickle=True)
    movie_ids = np.asarray(data["movie_ids"]).astype(str)
    embeddings = data["embeddings"].astype(np.float32, copy=False)
    log(f"  {len(movie_ids):,} ids, dim={embeddings.shape[1]}")

    # L2-normalize so dot product == cosine similarity.
    norms = np.linalg.norm(embeddings, axis=1, keepdims=True)
    norms[norms == 0] = 1.0
    embeddings /= norms
    return movie_ids, embeddings


def load_movie_meta(path: Path) -> dict[str, tuple[str, str]]:
    log(f"loading movie metadata from {path} ...")
    df = pd.read_csv(
        path, sep="\t",
        usecols=["movieId:ID", "title", "year"],
        dtype=str, na_filter=False,
    )
    meta = dict(zip(df["movieId:ID"].values,
                    zip(df["title"].values, df["year"].values)))
    log(f"  {len(meta):,} movies")
    return meta


def resolve_anchors(
    movie_ids: np.ndarray,
    id_to_idx: dict[str, int],
) -> list[tuple[str, int, str, str, int]]:
    """Return (movieId, year, title, tag, embed_index). Drop missing ones."""
    resolved = []
    missing = []
    for mid, year, title, tag in ANCHORS:
        idx = id_to_idx.get(mid)
        if idx is None:
            missing.append(f"{mid} ({title})")
            continue
        resolved.append((mid, year, title, tag, idx))
    if missing:
        log(f"  WARNING: {len(missing)} anchors missing from embeddings:")
        for m in missing:
            log(f"    - {m}")
    log(f"  {len(resolved)} anchors resolved")
    return resolved


def topk_neighbors(
    anchor_idx: list[int],
    embeddings: np.ndarray,
    k: int,
) -> dict[int, list[tuple[int, float]]]:
    """For each anchor index, return list of (neighbor_idx, cosine) of length k.
    Anchor itself is excluded.
    """
    log(f"computing top-{k} cosine neighbors for {len(anchor_idx)} anchors ...")
    n_total = embeddings.shape[0]
    anchor_vecs = embeddings[anchor_idx]   # (A, D)

    # Score in chunks to keep memory flat.
    scores = np.empty((len(anchor_idx), n_total), dtype=np.float32)
    for start in range(0, n_total, NN_CHUNK):
        end = min(start + NN_CHUNK, n_total)
        scores[:, start:end] = anchor_vecs @ embeddings[start:end].T
        if (start // NN_CHUNK) % 4 == 0:
            log(f"  scored {end:,} / {n_total:,}")

    # argpartition for k+1, then drop self, then sort descending by score.
    out: dict[int, list[tuple[int, float]]] = {}
    for row, a_idx in enumerate(anchor_idx):
        row_scores = scores[row]
        # take a few extras to safely drop self
        cand = np.argpartition(-row_scores, k + 1)[:k + 1]
        cand = cand[cand != a_idx][:k]
        cand = cand[np.argsort(-row_scores[cand])]
        out[a_idx] = [(int(i), float(row_scores[i])) for i in cand]
    return out


def collect_crew(
    roles_path: Path,
    movie_set: set[str],
) -> dict[str, set[tuple[str, str]]]:
    """Stream roles.csv once, return {movie_id: {(person_id, role_type), ...}}.
    Only rows whose :END_ID is in movie_set and :TYPE in KEPT_ROLE_TYPES.
    """
    log(f"collecting crew for {len(movie_set):,} movies (single pass) ...")
    crew: dict[str, set[tuple[str, str]]] = {m: set() for m in movie_set}
    seen = 0
    iter_ = pd.read_csv(
        roles_path, sep="\t",
        usecols=[":START_ID", ":END_ID", ":TYPE"],
        dtype=str, na_filter=False,
        chunksize=ROLES_CHUNK,
    )
    for i, chunk in enumerate(iter_):
        m = chunk[":END_ID"].isin(movie_set) & chunk[":TYPE"].isin(KEPT_ROLE_TYPES)
        sub = chunk.loc[m]
        for end_id, start_id, t in zip(
            sub[":END_ID"].values,
            sub[":START_ID"].values,
            sub[":TYPE"].values,
        ):
            crew[end_id].add((start_id, t))
        seen += len(chunk)
        log(f"  chunk {i}: read {len(chunk):,} (total {seen:,}); "
            f"matched {len(sub):,}")
    return crew


def load_person_names(
    people_path: Path,
    person_set: set[str],
) -> dict[str, str]:
    log(f"loading names for {len(person_set):,} persons ...")
    df = pd.read_csv(
        people_path, sep="\t",
        usecols=["personId:ID", "name"],
        dtype=str, na_filter=False,
    )
    df = df[df["personId:ID"].isin(person_set)]
    return dict(zip(df["personId:ID"].values, df["name"].values))


def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--embeddings", required=True, type=Path)
    p.add_argument("--raw-data", required=True, type=Path,
                   help="Directory containing movies.csv / roles.csv / people_names.csv")
    p.add_argument("--out", required=True, type=Path)
    p.add_argument("--top-k", type=int, default=TOP_K)
    args = p.parse_args()

    movies_csv = args.raw_data / "movies.csv"
    roles_csv = args.raw_data / "roles.csv"
    people_csv = args.raw_data / "people_names.csv"
    for f in (args.embeddings, movies_csv, roles_csv, people_csv):
        if not f.exists():
            log(f"missing input: {f}")
            return 2

    movie_ids, embeddings = load_embeddings(args.embeddings)
    id_to_idx = {mid: i for i, mid in enumerate(movie_ids)}

    anchors = resolve_anchors(movie_ids, id_to_idx)
    if not anchors:
        log("no anchors resolved; aborting")
        return 1

    nn = topk_neighbors([a[4] for a in anchors], embeddings, args.top_k)

    movie_meta = load_movie_meta(movies_csv)

    # Set of movies we need crew for: anchors + their neighbors.
    movie_set: set[str] = set()
    for _, _, _, _, a_idx in anchors:
        movie_set.add(str(movie_ids[a_idx]))
        for n_idx, _ in nn[a_idx]:
            movie_set.add(str(movie_ids[n_idx]))

    crew = collect_crew(roles_csv, movie_set)

    # Person names for the crew sets we'll display.
    person_set: set[str] = set()
    for s in crew.values():
        for pid, _ in s:
            person_set.add(pid)
    name_of = load_person_names(people_csv, person_set)

    log(f"writing {args.out} ...")
    with args.out.open("w", newline="") as fh:
        w = csv.writer(fh)
        w.writerow([
            "anchor_id", "anchor_title", "anchor_year",
            "anchor_tag", "anchor_crew_count",
            "rank",
            "neighbor_id", "neighbor_title", "neighbor_year",
            "cosine_sim",
            "shared_crew_count", "shared_crew_sample",
            "label", "notes",
        ])
        for mid, year, title, tag, a_idx in anchors:
            a_crew = crew.get(mid, set())
            a_persons = {pid for pid, _ in a_crew}
            for rank, (n_idx, sim) in enumerate(nn[a_idx], start=1):
                n_mid = str(movie_ids[n_idx])
                n_title, n_year = movie_meta.get(n_mid, ("?", "?"))
                n_crew = crew.get(n_mid, set())
                n_persons = {pid for pid, _ in n_crew}
                shared = a_persons & n_persons
                sample_names = sorted(
                    {name_of.get(pid, pid) for pid in list(shared)[:5]}
                )
                w.writerow([
                    mid, title, year, tag, len(a_crew),
                    rank,
                    n_mid, n_title, n_year,
                    f"{sim:.4f}",
                    len(shared), "; ".join(sample_names),
                    "", "",
                ])
    log("done.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
