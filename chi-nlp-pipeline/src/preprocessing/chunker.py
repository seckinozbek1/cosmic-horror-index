"""
Text Chunker — Splits raw text into semantically meaningful chunks.
Handles verse-level and paragraph-level chunking strategies.
"""

import re
import logging

logger = logging.getLogger("chi-pipeline.chunker")


class TextChunker:
    def __init__(self, chunk_config: dict):
        self.max_tokens = chunk_config.get("max_chunk_tokens", 256)
        self.overlap = chunk_config.get("overlap_tokens", 32)
        # Rough token estimate: 1 token ≈ 4 chars
        self.max_chars = self.max_tokens * 4
        self.overlap_chars = self.overlap * 4

    def chunk(self, text_data: dict) -> list:
        """Chunk a text document into pieces with metadata."""
        strategy = text_data.get("chunk_by", "paragraph")
        passages = text_data.get("passages", [])
        tradition = text_data.get("tradition", "unknown")
        corpus_id = text_data.get("corpus_id", "unknown")
        text_name = text_data.get("name", "unknown")
        translation = text_data.get("translation", "unknown")

        chunks = []
        for passage in passages:
            if passage.get("type") == "placeholder":
                continue

            text = passage["text"]
            source = passage.get("source", text_name)
            index = passage.get("index", "0")

            if strategy == "verse" and len(text) <= self.max_chars:
                # Verse-level: each passage is already a chunk
                chunks.append({
                    "text": text,
                    "tradition": tradition,
                    "corpus_id": corpus_id,
                    "source": text_name,
                    "section": source,
                    "reference": index,
                    "translation": translation,
                    "chunk_type": "verse"
                })
            else:
                # Paragraph-level: split long passages with sliding window
                sub_chunks = self._sliding_window(text)
                for j, sub in enumerate(sub_chunks):
                    chunks.append({
                        "text": sub,
                        "tradition": tradition,
                        "corpus_id": corpus_id,
                        "source": text_name,
                        "section": source,
                        "reference": f"{index}.{j}" if len(sub_chunks) > 1 else index,
                        "translation": translation,
                        "chunk_type": "paragraph"
                    })

        logger.debug(f"  Chunked {text_name}: {len(passages)} passages -> {len(chunks)} chunks")
        return chunks

    def _sliding_window(self, text: str) -> list:
        """Split text into overlapping windows at sentence boundaries."""
        if len(text) <= self.max_chars:
            return [text]

        sentences = re.split(r"(?<=[.!?])\s+", text)
        chunks = []
        current = ""
        overlap_buffer = ""

        for sent in sentences:
            if len(current) + len(sent) > self.max_chars and current:
                chunks.append(current.strip())
                # Start next chunk with overlap from end of current
                words = current.split()
                overlap_words = words[-min(len(words), self.overlap_chars // 5):]
                current = " ".join(overlap_words) + " " + sent
            else:
                current = (current + " " + sent).strip()

        if current.strip():
            chunks.append(current.strip())

        return chunks
