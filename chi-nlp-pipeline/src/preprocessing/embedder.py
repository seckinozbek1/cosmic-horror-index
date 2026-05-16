"""
Corpus Embedder — Generates sentence embeddings and builds FAISS index.
Uses SentenceTransformer for embedding and FAISS for similarity search.
"""

import json
import logging
import numpy as np
from pathlib import Path

logger = logging.getLogger("chi-pipeline.embedder")


class CorpusEmbedder:
    def __init__(self, model_name: str, output_dir: Path):
        self.model_name = model_name
        self.output_dir = output_dir
        self.output_dir.mkdir(parents=True, exist_ok=True)
        self.model = None  # lazy load

    def _load_model(self):
        if self.model is None:
            from sentence_transformers import SentenceTransformer
            logger.info(f"Loading embedding model: {self.model_name}")
            self.model = SentenceTransformer(self.model_name)

    def embed_chunks(self, chunks: list):
        """Generate embeddings for all chunks and save FAISS index."""
        self._load_model()
        import faiss

        texts = [c["text"] for c in chunks]
        logger.info(f"Embedding {len(texts)} chunks...")

        # Batch encode
        embeddings = self.model.encode(
            texts,
            show_progress_bar=True,
            batch_size=64,
            normalize_embeddings=True  # For cosine similarity via inner product
        )

        # Build FAISS index
        dim = embeddings.shape[1]
        index = faiss.IndexFlatIP(dim)  # Inner product = cosine sim on normalized vectors
        index.add(embeddings.astype(np.float32))

        # Save index
        faiss.write_index(index, str(self.output_dir / "corpus.index"))

        # Save embeddings as numpy array (for potential reuse)
        np.save(str(self.output_dir / "embeddings.npy"), embeddings)

        # Save chunk metadata (parallel to embedding rows)
        meta = []
        for i, c in enumerate(chunks):
            meta.append({
                "idx": i,
                "tradition": c["tradition"],
                "corpus_id": c["corpus_id"],
                "source": c["source"],
                "section": c["section"],
                "reference": c["reference"],
                "translation": c["translation"],
                "text": c["text"],
                "chunk_type": c["chunk_type"]
            })

        (self.output_dir / "chunk_metadata.json").write_text(
            json.dumps(meta, indent=2, ensure_ascii=False)
        )

        logger.info(f"FAISS index built: {index.ntotal} vectors, dim={dim}")
        logger.info(f"Saved to {self.output_dir}")
