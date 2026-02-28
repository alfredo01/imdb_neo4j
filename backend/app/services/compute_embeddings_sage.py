"""
Compute 128-d GraphSAGE movie embeddings with PyTorch Geometric.

Unlike FastRP (limited to 32d by JVM memory), GraphSAGE with mini-batch
neighbor sampling fits the full 14.6M-node graph in ~4GB RAM.

Usage (from backend container):
    python -m app.services.compute_embeddings_sage
"""

import gc
import os
import time

import numpy as np
import pandas as pd
import torch
import torch.nn.functional as F
from neo4j import GraphDatabase
from dotenv import load_dotenv
from sklearn.preprocessing import StandardScaler
from torch_geometric.data import Data
from torch_geometric.loader import LinkNeighborLoader
from torch_geometric.nn import SAGEConv

load_dotenv()

# ---------------------------------------------------------------------------
# Paths & constants
# ---------------------------------------------------------------------------
RAW_DATA = os.getenv("RAW_DATA_DIR", "/app/raw_data")
MOVIES_CSV = os.path.join(RAW_DATA, "movies.csv")
PEOPLE_CSV = os.path.join(RAW_DATA, "people_names.csv")
ROLES_CSV = os.path.join(RAW_DATA, "roles.csv")

KEPT_TYPES = {"ACTED_IN", "DIRECTED", "PRODUCED", "WROTE",
              "COMPOSED", "EDITED", "CINEMATOGRAPHER"}
MAX_EDGES = 30_000_000          # sample to cap memory
TRAIN_EDGES = 2_000_000         # subset of edges used for supervision
EMBED_DIM = 128
EPOCHS = 5
BATCH_SIZE = 4096
NEG_RATIO = 1
NEIGHBORS = [15, 10]            # 2-layer sampling
LR = 0.005
WRITE_BATCH = 5000              # Neo4j write batch
PROPERTY_NAME = "embeddingSage"


# ---------------------------------------------------------------------------
# Model
# ---------------------------------------------------------------------------
class GraphSAGEEncoder(torch.nn.Module):
    def __init__(self, in_channels, hidden_channels, out_channels):
        super().__init__()
        self.conv1 = SAGEConv(in_channels, hidden_channels)
        self.conv2 = SAGEConv(hidden_channels, out_channels)

    def forward(self, x, edge_index):
        x = self.conv1(x, edge_index)
        x = F.relu(x)
        x = F.dropout(x, p=0.3, training=self.training)
        x = self.conv2(x, edge_index)
        return x


# ---------------------------------------------------------------------------
# Main class
# ---------------------------------------------------------------------------
class SageEmbeddingComputer:
    def __init__(self, uri=None, user=None, password=None):
        if uri is None:
            uri = os.getenv("NEO4J_URI", "bolt://neo4j:7687")
        if user is None:
            user = os.getenv("NEO4J_USERNAME", "neo4j")
        if password is None:
            password = os.getenv("NEO4J_PASSWORD")
        self.driver = GraphDatabase.driver(uri, auth=(user, password))

    def close(self):
        self.driver.close()

    # ---- step 1: load nodes ------------------------------------------------
    def _load_nodes(self):
        print("Loading movie nodes …")
        movies = pd.read_csv(MOVIES_CSV, sep="\t", usecols=["movieId:ID", "year"],
                             dtype={"movieId:ID": str, "year": str})
        movies.rename(columns={"movieId:ID": "id"}, inplace=True)
        movies["year"] = pd.to_numeric(movies["year"], errors="coerce").fillna(0).astype(np.float32)
        n_movies = len(movies)
        print(f"  {n_movies:,} movies loaded")

        print("Loading person nodes …")
        people = pd.read_csv(PEOPLE_CSV, sep="\t",
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
        # reindex to match movie_ids order, fill missing with 0
        df = df.reindex(movie_ids, fill_value=0.0)
        print(f"  Centrality fetched for {(df['pr'] != 0).sum():,} / {len(df):,} movies")
        return df

    # ---- step 3: load edges ------------------------------------------------
    def _load_edges(self, id_map: pd.Series):
        print(f"Loading edges from roles.csv (keeping {len(KEPT_TYPES)} types, max {MAX_EDGES:,}) …")
        src_list, dst_list = [], []
        total_kept = 0
        chunk_iter = pd.read_csv(
            ROLES_CSV, sep="\t",
            usecols=[":START_ID", ":END_ID", ":TYPE"],
            dtype=str,
            chunksize=5_000_000,
        )
        for i, chunk in enumerate(chunk_iter):
            mask = chunk[":TYPE"].isin(KEPT_TYPES)
            filtered = chunk.loc[mask, [":START_ID", ":END_ID"]]
            # map to int indices – drop edges whose nodes are unknown
            s = id_map.reindex(filtered[":START_ID"].values).values
            d = id_map.reindex(filtered[":END_ID"].values).values
            valid = ~(np.isnan(s) | np.isnan(d))
            src_list.append(s[valid].astype(np.int64))
            dst_list.append(d[valid].astype(np.int64))
            total_kept += valid.sum()
            print(f"  chunk {i}: kept {valid.sum():,} edges  (total so far {total_kept:,})")
            if total_kept >= MAX_EDGES * 1.1:
                break  # read slightly more, sample later

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
        # make bidirectional
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
    def _build_features(self, movies, people, centrality, n_movies, n_total):
        print("Building feature matrix …")
        # movies: [year, pr, dc, bc, ec]  →  5 features
        movie_feat = np.zeros((n_movies, 5), dtype=np.float32)
        movie_feat[:, 0] = movies["year"].values
        movie_feat[:, 1] = centrality["pr"].values.astype(np.float32)
        movie_feat[:, 2] = centrality["dc"].values.astype(np.float32)
        movie_feat[:, 3] = centrality["bc"].values.astype(np.float32)
        movie_feat[:, 4] = centrality["ec"].values.astype(np.float32)

        # persons: [birthYear, deathYear, 0, 0, 0]  →  padded to 5
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
                h = model(batch.x, batch.edge_index)
                # edge_label_index has shape [2, E_pos+E_neg]
                # edge_label: 1 for positive, 0 for negative
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
                if n_batches % 500 == 0:
                    print(f"    epoch {epoch}  batch {n_batches}  "
                          f"loss={loss.item():.4f}")
            dt = time.time() - t0
            print(f"  Epoch {epoch}/{EPOCHS}  avg_loss={total_loss / max(n_batches, 1):.4f}  "
                  f"batches={n_batches}  time={dt:.0f}s")

        return model

    # ---- step 6: infer + write to Neo4j ------------------------------------
    def _infer_and_write(self, model, data: Data, id_map: pd.Series, n_movies: int):
        print(f"\nInferring embeddings for {n_movies:,} movies and writing to Neo4j …")
        model.eval()

        # Reverse map: int index → movieId string (only movie indices)
        inv_map = pd.Series(id_map.index[:n_movies], index=np.arange(n_movies))

        # We infer in batches to avoid building the full 11M × 128 matrix
        from torch_geometric.loader import NeighborLoader

        infer_loader = NeighborLoader(
            data,
            num_neighbors=NEIGHBORS,
            batch_size=WRITE_BATCH,
            input_nodes=torch.arange(n_movies),  # only movie nodes
            shuffle=False,
            num_workers=0,
        )

        written = 0
        with self.driver.session() as session:
            batch_params = []
            for batch in infer_loader:
                with torch.no_grad():
                    h = model(batch.x, batch.edge_index)
                # batch.n_id maps local indices back to global indices
                # batch.input_id or batch.batch_size tells us which are seed nodes
                n_seed = batch.batch_size if isinstance(batch.batch_size, int) else batch.batch_size.item()
                global_ids = batch.n_id[:n_seed].numpy()
                embeddings = h[:n_seed].numpy()

                for g_id, emb in zip(global_ids, embeddings):
                    if g_id >= n_movies:
                        continue
                    movie_id = inv_map[g_id]
                    batch_params.append({
                        "movieId": movie_id,
                        "emb": emb.tolist(),
                    })

                if len(batch_params) >= WRITE_BATCH:
                    self._write_batch(session, batch_params)
                    written += len(batch_params)
                    batch_params = []
                    if written % 50_000 == 0:
                        print(f"    written {written:,} / {n_movies:,}")

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

    # ---- step 7: verify ----------------------------------------------------
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

    # ---- orchestrator ------------------------------------------------------
    def compute(self):
        movies, people, id_map, n_movies = self._load_nodes()
        centrality = self._fetch_centrality(movies["id"])

        edge_index = self._load_edges(id_map)

        n_total = len(id_map)
        x = self._build_features(movies, people, centrality, n_movies, n_total)

        # free heavy dataframes
        del movies, people, centrality
        gc.collect()

        data = Data(x=x, edge_index=edge_index)
        del x, edge_index
        gc.collect()

        model = self._train(data)
        self._infer_and_write(model, data, id_map, n_movies)


if __name__ == "__main__":
    computer = SageEmbeddingComputer()
    try:
        print("Starting GraphSAGE embedding computation …\n")
        computer.compute()
        computer.show_statistics()
        print("\n" + "=" * 60)
        print("GraphSAGE embeddings computed and stored successfully!")
        print("=" * 60)
    except Exception as e:
        print(f"\nError: {e}")
        import traceback
        traceback.print_exc()
    finally:
        computer.close()
