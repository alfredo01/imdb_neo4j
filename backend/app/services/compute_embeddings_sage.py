"""
Compute 128-d GraphSAGE movie embeddings with PyTorch Geometric.

Unlike FastRP (limited to 32d by JVM memory), GraphSAGE with mini-batch
neighbor sampling fits the full 14.6M-node graph in ~4GB RAM.

Usage:
  1. Train locally and save embeddings to file:
       python compute_embeddings_sage.py train --data-dir ./neo4j/raw_data --neo4j-uri bolt://localhost:7687

  2. Push saved embeddings to remote Neo4j:
       python compute_embeddings_sage.py push --neo4j-uri bolt://SERVER:7687

  Or do both in one shot (from Docker container):
       python -m app.services.compute_embeddings_sage all
"""

import argparse
import gc
import os
import sys
import time

import numpy as np
import pandas as pd
import torch
import torch.nn.functional as F
from sklearn.preprocessing import StandardScaler
from torch_geometric.data import Data
from torch_geometric.loader import LinkNeighborLoader
from torch_geometric.nn import SAGEConv

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------
KEPT_TYPES = {"ACTED_IN", "DIRECTED", "PRODUCED", "WROTE",
              "COMPOSED", "EDITED", "CINEMATOGRAPHER"}
MAX_EDGES = 30_000_000          # sample to cap memory
TRAIN_EDGES = 2_000_000         # subset of edges used for supervision
EMBED_DIM = 128
LEARNABLE_DIM = 64              # per-node learnable embedding dimension
EPOCHS = 10
BATCH_SIZE = 4096
NEG_RATIO = 1
NEIGHBORS = [20, 15, 10]        # 3-layer sampling: movie→crew→movies→crew
LR = 0.005
WRITE_BATCH = 5000              # Neo4j write batch
PROPERTY_NAME = "embeddingSage"
EMBEDDINGS_FILE = "sage_embeddings.npz"


# ---------------------------------------------------------------------------
# Model
# ---------------------------------------------------------------------------
class GraphSAGEEncoder(torch.nn.Module):
    def __init__(self, in_channels, hidden_channels, out_channels,
                 num_nodes=0, learnable_dim=0):
        super().__init__()
        # Learnable embedding per node — captures structural identity
        self.node_emb = None
        total_in = in_channels
        if num_nodes > 0 and learnable_dim > 0:
            self.node_emb = torch.nn.Embedding(num_nodes, learnable_dim)
            torch.nn.init.xavier_uniform_(self.node_emb.weight)
            total_in = in_channels + learnable_dim

        self.conv1 = SAGEConv(total_in, hidden_channels)
        self.conv2 = SAGEConv(hidden_channels, hidden_channels)
        self.conv3 = SAGEConv(hidden_channels, out_channels)

    def forward(self, x, edge_index, n_id=None):
        if self.node_emb is not None and n_id is not None:
            x = torch.cat([x, self.node_emb(n_id)], dim=-1)
        x = self.conv1(x, edge_index)
        x = F.relu(x)
        x = F.dropout(x, p=0.3, training=self.training)
        x = self.conv2(x, edge_index)
        x = F.relu(x)
        x = F.dropout(x, p=0.3, training=self.training)
        x = self.conv3(x, edge_index)
        return x


# ---------------------------------------------------------------------------
# Main class
# ---------------------------------------------------------------------------
class SageEmbeddingComputer:
    def __init__(self, neo4j_uri=None, neo4j_user=None, neo4j_password=None):
        self.neo4j_uri = neo4j_uri
        self.neo4j_user = neo4j_user
        self.neo4j_password = neo4j_password
        self._driver = None

    @property
    def driver(self):
        if self._driver is None:
            from neo4j import GraphDatabase
            self._driver = GraphDatabase.driver(
                self.neo4j_uri, auth=(self.neo4j_user, self.neo4j_password)
            )
        return self._driver

    def close(self):
        if self._driver is not None:
            self._driver.close()

    # ---- step 1: load nodes ------------------------------------------------
    def _load_nodes(self, data_dir):
        movies_csv = os.path.join(data_dir, "movies.csv")
        people_csv = os.path.join(data_dir, "people_names.csv")

        print("Loading movie nodes …")
        movies = pd.read_csv(movies_csv, sep="\t", usecols=["movieId:ID", "year"],
                             dtype={"movieId:ID": str, "year": str})
        movies.rename(columns={"movieId:ID": "id"}, inplace=True)
        movies["year"] = pd.to_numeric(movies["year"], errors="coerce").fillna(0).astype(np.float32)
        n_movies = len(movies)
        print(f"  {n_movies:,} movies loaded")

        print("Loading person nodes …")
        people = pd.read_csv(people_csv, sep="\t",
                             usecols=["personId:ID", "birthYear", "deathYear"],
                             dtype={"personId:ID": str, "birthYear": str, "deathYear": str})
        people.rename(columns={"personId:ID": "id"}, inplace=True)
        people["birthYear"] = pd.to_numeric(people["birthYear"], errors="coerce").fillna(0).astype(np.float32)
        people["deathYear"] = pd.to_numeric(people["deathYear"], errors="coerce").fillna(0).astype(np.float32)
        n_people = len(people)
        print(f"  {n_people:,} persons loaded")

        # Build global id → int index  (movies first, then persons)
        all_ids = pd.concat([movies["id"], people["id"]], ignore_index=True)
        id_map = pd.Series(np.arange(len(all_ids), dtype=np.int32), index=all_ids.values)
        print(f"  Total nodes: {len(id_map):,}")
        return movies, people, id_map, n_movies

    # ---- step 2: fetch centrality from Neo4j --------------------------------
    def _fetch_centrality(self, movie_ids: pd.Series):
        """Return a DataFrame indexed by movieId with 4 centrality columns."""
        print("Fetching centrality scores from Neo4j …")
        query = """
        MATCH (m:Movie)
        WHERE m.pageRank IS NOT NULL
        RETURN m.movieId AS id,
               m.pageRank           AS pr,
               m.degreeCentrality   AS dc,
               m.betweennessCentrality AS bc,
               m.eigenvectorCentrality AS ec
        """
        records = []
        with self.driver.session() as session:
            result = session.run(query)
            for r in result:
                records.append((r["id"], r["pr"], r["dc"], r["bc"], r["ec"]))
        if not records:
            print("  WARNING: no centrality data found – using zeros")
            return pd.DataFrame({"pr": 0, "dc": 0, "bc": 0, "ec": 0},
                                index=movie_ids)
        df = pd.DataFrame(records, columns=["id", "pr", "dc", "bc", "ec"])
        df.set_index("id", inplace=True)
        df = df.reindex(movie_ids, fill_value=0.0)
        print(f"  Centrality fetched for {(df['pr'] != 0).sum():,} / {len(df):,} movies")
        return df

    # ---- step 3: load edges ------------------------------------------------
    def _load_edges(self, data_dir, id_map: pd.Series):
        roles_csv = os.path.join(data_dir, "roles.csv")
        print(f"Loading edges from roles.csv (keeping {len(KEPT_TYPES)} types, max {MAX_EDGES:,}) …")
        src_list, dst_list = [], []
        total_kept = 0
        chunk_iter = pd.read_csv(
            roles_csv, sep="\t",
            usecols=[":START_ID", ":END_ID", ":TYPE"],
            dtype=str,
            chunksize=5_000_000,
        )
        for i, chunk in enumerate(chunk_iter):
            mask = chunk[":TYPE"].isin(KEPT_TYPES)
            filtered = chunk.loc[mask, [":START_ID", ":END_ID"]]
            s = id_map.reindex(filtered[":START_ID"].values).values
            d = id_map.reindex(filtered[":END_ID"].values).values
            valid = ~(np.isnan(s) | np.isnan(d))
            src_list.append(s[valid].astype(np.int64))
            dst_list.append(d[valid].astype(np.int64))
            total_kept += valid.sum()
            print(f"  chunk {i}: kept {valid.sum():,} edges  (total so far {total_kept:,})")
            if total_kept >= MAX_EDGES * 1.1:
                break

        src = np.concatenate(src_list)
        dst = np.concatenate(dst_list)
        del src_list, dst_list
        gc.collect()

        if len(src) > MAX_EDGES:
            print(f"  Sampling {MAX_EDGES:,} from {len(src):,} edges …")
            rng = np.random.default_rng(42)
            idx = rng.choice(len(src), size=MAX_EDGES, replace=False)
            src, dst = src[idx], dst[idx]

        print(f"  Final edge count (one-directional): {len(src):,}")
        edge_index = torch.tensor(
            np.stack([np.concatenate([src, dst]),
                      np.concatenate([dst, src])]),
            dtype=torch.long,
        )
        del src, dst
        gc.collect()
        print(f"  Bidirectional edge_index shape: {edge_index.shape}")
        return edge_index

    # ---- step 4: build features -------------------------------------------
    def _build_features(self, movies, people, centrality, n_movies):
        print("Building feature matrix …")
        movie_feat = np.zeros((n_movies, 5), dtype=np.float32)
        movie_feat[:, 0] = movies["year"].values
        movie_feat[:, 1] = centrality["pr"].values.astype(np.float32)
        movie_feat[:, 2] = centrality["dc"].values.astype(np.float32)
        movie_feat[:, 3] = centrality["bc"].values.astype(np.float32)
        movie_feat[:, 4] = centrality["ec"].values.astype(np.float32)

        n_people = len(people)
        person_feat = np.zeros((n_people, 5), dtype=np.float32)
        person_feat[:, 0] = people["birthYear"].values
        person_feat[:, 1] = people["deathYear"].values

        feat = np.vstack([movie_feat, person_feat])
        del movie_feat, person_feat
        gc.collect()

        scaler = StandardScaler()
        feat = scaler.fit_transform(feat).astype(np.float32)
        print(f"  Feature matrix shape: {feat.shape}")
        return torch.from_numpy(feat)

    # ---- step 5: train -----------------------------------------------------
    def _train(self, data: Data):
        print(f"\nTraining GraphSAGE ({EPOCHS} epochs, batch={BATCH_SIZE}, "
              f"neighbors={NEIGHBORS}) …")
        device = torch.device("cpu")
        model = GraphSAGEEncoder(
            in_channels=data.x.size(1),
            hidden_channels=256,
            out_channels=EMBED_DIM,
            num_nodes=data.x.size(0),
            learnable_dim=LEARNABLE_DIM,
        ).to(device)
        optimizer = torch.optim.Adam(model.parameters(), lr=LR)

        # Sample a subset of edges for supervision (full graph used for message passing)
        n_edges = data.edge_index.size(1)
        if n_edges > TRAIN_EDGES:
            rng = torch.Generator().manual_seed(42)
            perm = torch.randperm(n_edges, generator=rng)[:TRAIN_EDGES]
            train_edge_label_index = data.edge_index[:, perm]
            print(f"  Using {TRAIN_EDGES:,} / {n_edges:,} edges for supervision")
        else:
            train_edge_label_index = data.edge_index

        loader = LinkNeighborLoader(
            data,
            num_neighbors=NEIGHBORS,
            batch_size=BATCH_SIZE,
            edge_label_index=train_edge_label_index,
            neg_sampling_ratio=NEG_RATIO,
            shuffle=True,
            num_workers=0,
        )

        model.train()
        for epoch in range(1, EPOCHS + 1):
            total_loss = 0.0
            n_batches = 0
            t0 = time.time()
            for batch in loader:
                batch = batch.to(device)
                optimizer.zero_grad()
                h = model(batch.x, batch.edge_index, n_id=batch.n_id)
                src_emb = h[batch.edge_label_index[0]]
                dst_emb = h[batch.edge_label_index[1]]
                pred = (src_emb * dst_emb).sum(dim=-1)
                loss = F.binary_cross_entropy_with_logits(
                    pred, batch.edge_label.float()
                )
                loss.backward()
                optimizer.step()
                total_loss += loss.item()
                n_batches += 1
                if n_batches % 100 == 0:
                    print(f"    epoch {epoch}  batch {n_batches}  "
                          f"loss={loss.item():.4f}")
            dt = time.time() - t0
            print(f"  Epoch {epoch}/{EPOCHS}  avg_loss={total_loss / max(n_batches, 1):.4f}  "
                  f"batches={n_batches}  time={dt:.0f}s")

        return model

    # ---- step 6: infer embeddings ------------------------------------------
    def _infer(self, model, data: Data, id_map: pd.Series, n_movies: int):
        """Infer embeddings for all movies, return (movie_ids, embeddings) arrays."""
        print(f"\nInferring embeddings for {n_movies:,} movies …")
        model.eval()

        from torch_geometric.loader import NeighborLoader

        inv_map = pd.Series(id_map.index[:n_movies], index=np.arange(n_movies))

        infer_loader = NeighborLoader(
            data,
            num_neighbors=NEIGHBORS,
            batch_size=WRITE_BATCH,
            input_nodes=torch.arange(n_movies),
            shuffle=False,
            num_workers=0,
        )

        all_movie_ids = []
        all_embeddings = []
        processed = 0

        for batch in infer_loader:
            with torch.no_grad():
                h = model(batch.x, batch.edge_index, n_id=batch.n_id)
            n_seed = batch.batch_size if isinstance(batch.batch_size, int) else batch.batch_size.item()
            global_ids = batch.n_id[:n_seed].numpy()
            embeddings = h[:n_seed].numpy()

            for g_id, emb in zip(global_ids, embeddings):
                if g_id >= n_movies:
                    continue
                all_movie_ids.append(inv_map[g_id])
                all_embeddings.append(emb)

            processed += n_seed
            if processed % 100_000 == 0:
                print(f"    inferred {processed:,} / {n_movies:,}")

        print(f"  Total inferred: {len(all_movie_ids):,}")
        embeddings = np.array(all_embeddings, dtype=np.float32)
        # L2-normalize so cosine similarity spreads out (avoids all-0.99 scores)
        norms = np.linalg.norm(embeddings, axis=1, keepdims=True)
        norms = np.maximum(norms, 1e-8)
        embeddings = embeddings / norms
        return np.array(all_movie_ids, dtype=object), embeddings

    # ---- save / load embeddings file ---------------------------------------
    @staticmethod
    def save_embeddings(movie_ids, embeddings, output_file):
        print(f"\nSaving embeddings to {output_file} …")
        np.savez_compressed(output_file, movie_ids=movie_ids, embeddings=embeddings)
        size_mb = os.path.getsize(output_file) / (1024 * 1024)
        print(f"  Saved {len(movie_ids):,} embeddings ({size_mb:.1f} MB)")

    @staticmethod
    def load_embeddings(input_file):
        print(f"\nLoading embeddings from {input_file} …")
        data = np.load(input_file, allow_pickle=True)
        movie_ids = data["movie_ids"]
        embeddings = data["embeddings"]
        print(f"  Loaded {len(movie_ids):,} embeddings, dim={embeddings.shape[1]}")
        return movie_ids, embeddings

    # ---- push embeddings to Neo4j ------------------------------------------
    def push_to_neo4j(self, movie_ids, embeddings):
        print(f"\nPushing {len(movie_ids):,} embeddings to Neo4j …")
        written = 0
        with self.driver.session() as session:
            batch_params = []
            for mid, emb in zip(movie_ids, embeddings):
                batch_params.append({
                    "movieId": str(mid),
                    "emb": emb.tolist(),
                })
                if len(batch_params) >= WRITE_BATCH:
                    self._write_batch(session, batch_params)
                    written += len(batch_params)
                    batch_params = []
                    if written % 50_000 == 0:
                        print(f"    written {written:,} / {len(movie_ids):,}")

            if batch_params:
                self._write_batch(session, batch_params)
                written += len(batch_params)

        print(f"  Total written: {written:,}")

    @staticmethod
    def _write_batch(session, params):
        session.run(
            f"""
            UNWIND $rows AS row
            MATCH (m:Movie {{movieId: row.movieId}})
            SET m.{PROPERTY_NAME} = row.emb
            """,
            rows=params,
        )

    # ---- verify ------------------------------------------------------------
    def show_statistics(self):
        with self.driver.session() as session:
            print("\n" + "=" * 60)
            print("GRAPHSAGE EMBEDDING STATISTICS")
            print("=" * 60)

            result = session.run(f"""
                MATCH (m:Movie)
                WHERE m.{PROPERTY_NAME} IS NOT NULL
                RETURN count(m) AS cnt
            """)
            print(f"Movies with {PROPERTY_NAME}: {result.single()['cnt']:,}")

            result = session.run(f"""
                MATCH (m:Movie)
                WHERE m.{PROPERTY_NAME} IS NOT NULL
                RETURN size(m.{PROPERTY_NAME}) AS dim LIMIT 1
            """)
            rec = result.single()
            if rec:
                print(f"Embedding dimension: {rec['dim']}")

            print(f"\nTop 10 movies most similar to 'Titanic (1997)' by {PROPERTY_NAME}:")
            result = session.run(f"""
                MATCH (m1:Movie {{title: 'Titanic', year: '1997'}})
                WHERE m1.{PROPERTY_NAME} IS NOT NULL
                MATCH (m2:Movie)
                WHERE m2.{PROPERTY_NAME} IS NOT NULL AND m1 <> m2
                WITH m1, m2,
                     gds.similarity.cosine(m1.{PROPERTY_NAME}, m2.{PROPERTY_NAME}) AS sim
                WHERE sim IS NOT NULL AND NOT isNaN(sim)
                ORDER BY sim DESC
                LIMIT 10
                RETURN m2.title AS title, m2.year AS year, sim
            """)
            for i, r in enumerate(result, 1):
                print(f"  {i}. {r['title']} ({r['year']}): {r['sim']:.4f}")

    # ---- orchestrator: train -----------------------------------------------
    def train_and_save(self, data_dir, output_file=EMBEDDINGS_FILE):
        movies, people, id_map, n_movies = self._load_nodes(data_dir)
        centrality = self._fetch_centrality(movies["id"])
        edge_index = self._load_edges(data_dir, id_map)
        x = self._build_features(movies, people, centrality, n_movies)

        del movies, people, centrality
        gc.collect()

        data = Data(x=x, edge_index=edge_index)
        del x, edge_index
        gc.collect()

        model = self._train(data)
        movie_ids, embeddings = self._infer(model, data, id_map, n_movies)
        self.save_embeddings(movie_ids, embeddings, output_file)

    # ---- orchestrator: full pipeline ---------------------------------------
    def compute_all(self, data_dir, output_file=EMBEDDINGS_FILE):
        self.train_and_save(data_dir, output_file)
        movie_ids, embeddings = self.load_embeddings(output_file)
        self.push_to_neo4j(movie_ids, embeddings)
        self.show_statistics()


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------
def parse_args():
    parser = argparse.ArgumentParser(description="GraphSAGE movie embeddings")
    parser.add_argument("command", choices=["train", "push", "all"],
                        help="train = train locally & save file | "
                             "push = load file & write to Neo4j | "
                             "all = train + push")
    parser.add_argument("--data-dir", default=os.getenv("RAW_DATA_DIR", "/app/raw_data"),
                        help="Directory with movies.csv, people_names.csv, roles.csv")
    parser.add_argument("--neo4j-uri", default=os.getenv("NEO4J_URI", "bolt://neo4j:7687"))
    parser.add_argument("--neo4j-user", default=os.getenv("NEO4J_USERNAME", "neo4j"))
    parser.add_argument("--neo4j-password", default=os.getenv("NEO4J_PASSWORD", "adminadmin"))
    parser.add_argument("--embeddings-file", default=EMBEDDINGS_FILE,
                        help="Path to .npz embeddings file")
    return parser.parse_args()


if __name__ == "__main__":
    args = parse_args()
    computer = SageEmbeddingComputer(
        neo4j_uri=args.neo4j_uri,
        neo4j_user=args.neo4j_user,
        neo4j_password=args.neo4j_password,
    )
    try:
        if args.command == "train":
            print("=== TRAIN MODE: training locally, saving to file ===\n")
            computer.train_and_save(args.data_dir, args.embeddings_file)

        elif args.command == "push":
            print("=== PUSH MODE: loading file, writing to Neo4j ===\n")
            movie_ids, embeddings = computer.load_embeddings(args.embeddings_file)
            computer.push_to_neo4j(movie_ids, embeddings)
            computer.show_statistics()

        elif args.command == "all":
            print("=== ALL MODE: train + push ===\n")
            computer.compute_all(args.data_dir, args.embeddings_file)

        print("\n" + "=" * 60)
        print("Done!")
        print("=" * 60)

    except Exception as e:
        print(f"\nError: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)
    finally:
        computer.close()
