"""
Semantic Retriever — Finds the most relevant passages for each axis per tradition.
Uses FAISS index + probe queries to retrieve candidate passages for classification.
"""

import json
import logging
import numpy as np
from pathlib import Path

logger = logging.getLogger("chi-pipeline.retriever")


class SemanticRetriever:
    def __init__(self, embeddings_dir: Path, model_name: str, top_k: int = 20):
        self.embeddings_dir = embeddings_dir
        self.model_name = model_name
        self.top_k = top_k
        self.index = None
        self.metadata = None
        self.model = None

    def _load(self):
        if self.index is not None:
            return

        import faiss
        from sentence_transformers import SentenceTransformer

        logger.info("Loading FAISS index and metadata...")
        self.index = faiss.read_index(str(self.embeddings_dir / "corpus.index"))
        self.metadata = json.loads(
            (self.embeddings_dir / "chunk_metadata.json").read_text()
        )
        self.model = SentenceTransformer(self.model_name)
        logger.info(f"Index loaded: {self.index.ntotal} vectors")

    def retrieve(self, tradition: str, probes_high: list, probes_low: list = None) -> list:
        """
        Retrieve top-k passages for a given tradition matching the probe queries.
        
        Combines high and low probes to capture passages relevant to the axis
        in both directions (supporting high or low scores).
        """
        self._load()

        # Combine all probe queries
        all_probes = probes_high + (probes_low or [])

        # Embed probe queries
        probe_embeddings = self.model.encode(
            all_probes,
            normalize_embeddings=True
        ).astype(np.float32)

        # Search for each probe, collect unique results
        seen_indices = set()
        candidates = []

        # Get indices for this tradition
        tradition_indices = [
            m["idx"] for m in self.metadata if m["tradition"] == tradition
        ]

        if not tradition_indices:
            logger.warning(f"No passages found for tradition: {tradition}")
            return []

        for probe_vec in probe_embeddings:
            # Search full index (we'll filter by tradition after)
            scores, indices = self.index.search(
                probe_vec.reshape(1, -1),
                min(self.top_k * 5, self.index.ntotal)  # overfetch to filter
            )

            for score, idx in zip(scores[0], indices[0]):
                if idx == -1:
                    continue
                if idx not in tradition_indices:
                    continue
                if idx in seen_indices:
                    continue

                seen_indices.add(idx)
                meta = self.metadata[idx]
                candidates.append({
                    "text": meta["text"],
                    "source": meta["source"],
                    "section": meta["section"],
                    "reference": meta["reference"],
                    "translation": meta["translation"],
                    "tradition": meta["tradition"],
                    "corpus_id": meta["corpus_id"],
                    "similarity_score": float(score),
                    "chunk_idx": int(idx)
                })

                if len(candidates) >= self.top_k:
                    break

            if len(candidates) >= self.top_k:
                break

        # Sort by similarity score descending
        candidates.sort(key=lambda x: x["similarity_score"], reverse=True)

        return candidates[:self.top_k]
