"""
Training cell v2 for graphsage_colab.ipynb.

Implements plan groups 5.2 and 5.4:

  5.2  L2-normalize the encoder output and switch BCE-on-dot-product
       to symmetric in-batch InfoNCE on cosine. This fixes the
       retrieval-geometry failure that produced the baseline's 87%
       zero-shared-crew top-10 slots.

  5.4  Concatenate a learnable per-movie id-embedding to the 12-d
       structural features. Even at random init, this scatters
       cold-start movies of the same year apart in the embedding
       space — instead of collapsing them to a single point.

To use:
  - Replace cell 21 of graphsage_colab.ipynb with the body of this file.
  - In cell 22 (inference), change
        h = model(batch.x, batch.edge_index, batch.edge_weight)
    to
        h = model(batch.x, batch.edge_index, batch.edge_weight, n_id=batch.n_id)

Caveat for 5.4:
  Movies that never appear in any supervision pair never receive a
  gradient on their id-embedding — they keep their random init. That
  still beats the baseline (random scatter > deterministic collapse),
  but the full cold-start fix needs broader supervision coverage
  (plan group 4.x) so those id-embeddings actually train.
"""

import os
os.environ["PYTORCH_CUDA_ALLOC_CONF"] = "expandable_segments:True"

import time
import numpy as np
import torch
import torch.nn.functional as F
from torch_geometric.nn import GCNConv
from torch_geometric.loader import LinkNeighborLoader

EMBED_DIM = 128
ID_DIM = 64
TRAIN_EDGES = 10_000_000
BATCH_SIZE = 1024
NEIGHBORS = [10, 5]
EPOCHS = 10
LR = 0.003
TAU = 0.1  # InfoNCE temperature; 0.05–0.2 is the usual band


class MovieEncoder(torch.nn.Module):
    def __init__(self, feat_dim, hidden_ch, out_ch, n_nodes, id_dim):
        super().__init__()
        self.id_emb = torch.nn.Embedding(n_nodes, id_dim)
        torch.nn.init.normal_(self.id_emb.weight, std=0.02)
        self.conv1 = GCNConv(feat_dim + id_dim, hidden_ch)
        self.bn1 = torch.nn.BatchNorm1d(hidden_ch)
        self.conv2 = GCNConv(hidden_ch, out_ch)

    def forward(self, x, edge_index, edge_weight=None, n_id=None, **_):
        ids = n_id if n_id is not None else torch.arange(x.size(0), device=x.device)
        h = torch.cat([x, self.id_emb(ids)], dim=-1)
        h = F.relu(self.bn1(self.conv1(h, edge_index, edge_weight)))
        h = F.dropout(h, p=0.3, training=self.training)
        h = self.conv2(h, edge_index, edge_weight)
        return F.normalize(h, p=2, dim=-1)


def info_nce(src: torch.Tensor, dst: torch.Tensor, tau: float) -> torch.Tensor:
    """Symmetric in-batch InfoNCE on already L2-normalized vectors."""
    logits = src @ dst.T / tau
    targets = torch.arange(src.size(0), device=src.device)
    return 0.5 * (
        F.cross_entropy(logits, targets) + F.cross_entropy(logits.T, targets)
    )


def train(data, device):
    feat_dim = data.x.size(1)
    n_nodes = data.x.size(0)
    model = MovieEncoder(feat_dim, 256, EMBED_DIM, n_nodes, ID_DIM).to(device)
    optimizer = torch.optim.Adam(model.parameters(), lr=LR)
    scheduler = torch.optim.lr_scheduler.CosineAnnealingLR(optimizer, T_max=EPOCHS)
    print(f"Model params: {sum(p.numel() for p in model.parameters()):,}")

    # Sample positive supervision edges only — within-batch negatives
    # come for free from the InfoNCE matmul.
    n_edges = data.edge_index.size(1)
    if n_edges > TRAIN_EDGES:
        ew = data.edge_weight.numpy()
        probs = ew / ew.sum()
        perm = np.random.default_rng(42).choice(
            n_edges, size=TRAIN_EDGES, replace=False, p=probs
        )
        train_edge_label_index = data.edge_index[:, perm]
    else:
        train_edge_label_index = data.edge_index
    print(f"Supervision edges: {train_edge_label_index.size(1):,}")

    loader = LinkNeighborLoader(
        data,
        num_neighbors=NEIGHBORS,
        batch_size=BATCH_SIZE,
        edge_label_index=train_edge_label_index,
        neg_sampling_ratio=0.0,            # was 1.0 — InfoNCE handles negatives
        shuffle=True,
        num_workers=2,
        weight_attr="edge_weight",
    )

    torch.cuda.empty_cache()
    model.train()
    for epoch in range(1, EPOCHS + 1):
        total_loss, n_batches = 0.0, 0
        t0 = time.time()
        for batch in loader:
            batch = batch.to(device)
            optimizer.zero_grad()
            h = model(batch.x, batch.edge_index, batch.edge_weight, n_id=batch.n_id)
            src = h[batch.edge_label_index[0]]
            dst = h[batch.edge_label_index[1]]
            loss = info_nce(src, dst, TAU)
            loss.backward()
            optimizer.step()
            total_loss += loss.item()
            n_batches += 1
            if n_batches % 100 == 0:
                print(f"  epoch {epoch}  batch {n_batches}  loss={loss.item():.4f}")
        scheduler.step()
        dt = time.time() - t0
        print(
            f"Epoch {epoch}/{EPOCHS}  avg_loss={total_loss / n_batches:.4f}  "
            f"lr={scheduler.get_last_lr()[0]:.5f}  batches={n_batches}  time={dt:.0f}s"
        )

    print("\nTraining complete!")
    return model


# Example wiring inside the notebook (already has `data` and `device`):
#   model = train(data, device)