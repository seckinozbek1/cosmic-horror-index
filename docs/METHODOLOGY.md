# CHI-NLP Pipeline — Methodology

This document describes the full technical methodology for computing Cosmic Horror Index (CHI) scores from sacred text corpora.

---

## 1. What Is the Cosmic Horror Index?

The Cosmic Horror Index (CHI) is a 0–100 composite score measuring how structurally similar a cosmological tradition is to Lovecraftian horror. It is not a measure of literary influence, cultural value, or philosophical merit — it is a structural comparison along ten specific axes that characterize the Lovecraftian cosmological stance.

A score of 100 would indicate a tradition that is maximally indifferent to humanity, utterly incomprehensible, and morally neutral. A score of 0 would indicate a tradition that is maximally relational, knowable, and morally ordered.

---

## 2. The 10 CHI Axes

| Axis ID | Label | Weight | Core Question |
|---------|-------|--------|---------------|
| `omniscience` | Omniscience | 1 | Does the entity or ultimate reality know everything? |
| `omnipotence` | Omnipotence | 1 | Can the entity do anything? |
| `self_sufficiency` | Self-sufficiency | 1 | Does the entity need anything from creation? |
| `indifference` | Indifference to humans | **2** | Does it care about human welfare? |
| `incomprehensibility` | Incomprehensibility | **2** | Can humans understand the ultimate reality? |
| `human_insignificance` | Human insignificance | **2** | Do humans matter in this cosmological system? |
| `cyclical_destruction` | Cyclical destruction | 1 | Does the cosmos destroy and rebuild in cycles? |
| `awe_madness` | Awe / madness induction | 1 | Does encountering the truth overwhelm or break human minds? |
| `creation_without_consent` | Creation without consent | 1 | Were humans made without being consulted? |
| `moral_neutrality` | Moral neutrality | 1 | Is the ultimate reality beyond good and evil? |

### Why Three Axes Are Weighted 2x

`indifference`, `incomprehensibility`, and `human_insignificance` carry double weight because they are the most structurally distinctive features of Lovecraftian horror versus other high-scoring traditions. A tradition can be omnipotent and self-sufficient (Advaita Vedanta scores high here) without producing cosmic horror. What makes Lovecraft genuinely distinct is that the ultimate reality does not care, cannot be understood, and renders humanity meaningless. Doubling these three axes ensures the score reflects that structural core rather than superficial resemblances.

---

## 3. CHI Formula

CHI is the weighted mean of all ten axis scores:

```
CHI = (2×indifference + 2×incomprehensibility + 2×human_insignificance
       + omniscience + omnipotence + self_sufficiency + cyclical_destruction
       + awe_madness + creation_without_consent + moral_neutrality) / 13
```

The denominator is 13 because the three double-weighted axes each contribute weight 2, and the seven remaining axes contribute weight 1: (3×2) + (7×1) = 13.

Implementation in `src/export/compute_chi_v1.py`:

```python
def compute_chi(scores: dict, axes: list) -> float:
    weight_map = {a["id"]: a["weight"] for a in axes}
    total_weight = 0
    weighted_sum = 0
    for axis_id, value in scores.items():
        w = weight_map.get(axis_id, 1)
        weighted_sum += value * w
        total_weight += w
    return round(weighted_sum / total_weight, 1)
```

---

## 4. Pipeline Stages

The pipeline has four sequential stages, each of which can be run independently using `src/main.py --stage <stage>`.

### Stage 1: Corpus Acquisition

**Entry point:** `src/corpus/loader.py`

Downloads and parses sacred texts from:
- **Project Gutenberg** — plain text via `/cache/epub/NNNN/pgNNNN.txt` or `/files/NNNN/NNNN-0.txt`
- **sacred-texts.com** — HTML scrape
- **SuttaCentral / AccessToInsight** — HTML scrape for Pali Canon texts

Each loaded text is saved as a JSON file in `data/raw/{tradition}/` with the structure:
```json
{
  "corpus_id": "...",
  "tradition": "...",
  "name": "...",
  "translation": "...",
  "passages": [
    {"text": "...", "source": "...", "index": "..."}
  ]
}
```

Texts marked `"source": "manual_entry"` are not auto-downloaded and require manual placement in the raw directory.

### Stage 2: Chunking and Embedding

**Entry point:** `src/preprocessing/chunker.py`, `src/preprocessing/embedder.py`

**Chunking strategy** is determined per-text by the `chunk_by` field in `config/pipeline_config.yaml`:

- `"verse"` — Each passage is kept as a single chunk if it fits within the token limit (256 tokens / ~1024 chars). Used for metrically structured texts: Upanishads, Eddas, Dao De Jing, Buddhist sutras, Theogony.
- `"paragraph"` — Prose is split using a sliding window at sentence boundaries. Max chunk size: 256 tokens (~1024 chars). Overlap between consecutive chunks: 32 tokens (~128 chars). Used for: Lovecraft fiction, philosophical essays, commentaries, mythological prose.

**Embedding** is performed by `SentenceTransformer("all-MiniLM-L6-v2")`:
- 384-dimensional dense vectors
- `normalize_embeddings=True` — vectors are L2-normalized so that inner product equals cosine similarity
- Batch size: 64 chunks
- Output: `data/embeddings/corpus.index` (FAISS `IndexFlatIP`), `data/embeddings/embeddings.npy`, `data/embeddings/chunk_metadata.json`

The FAISS `IndexFlatIP` (inner product) performs exact nearest-neighbor search. Because vectors are normalized, inner product is equivalent to cosine similarity. The index covers all traditions simultaneously; filtering to a specific tradition happens in the retriever after search.

Production index statistics: **14,096 vectors across 13 traditions.**

### Stage 3: Semantic Retrieval

**Entry point:** `src/scoring/retriever.py`

For each (tradition, axis) pair, the retriever:

1. Embeds all probe queries for the axis (both `probes_high` and `probes_low`) using the same SentenceTransformer model.
2. Runs FAISS search for each probe query, overfetching to compensate for index dilution. Because the index contains all traditions, a tradition that is 1% of the total index would need 100x results to reliably capture its top-20 passages. The overfetch formula:
   ```python
   overfetch_k = min(
       max(top_k * 5, int(top_k * n_total / max(n_tradition, 1) * 2)),
       n_total
   )
   ```
3. Filters results to only the target tradition's chunks.
4. Deduplicates (a passage matched by multiple probes is included once).
5. Sorts by similarity score descending.
6. Returns the top `top_k` passages (default: 20).

Both `probes_high` and `probes_low` queries are used for retrieval. This ensures the retrieved candidate set contains passages arguing both for and against a high score, giving the classifier (Stage 4) material to assign accurate valence.

### Stage 4: LLM Classification

**Entry point:** `src/scoring/classifier.py`

Each retrieved passage is individually classified by Claude Sonnet via the Anthropic API. The prompt supplies:
- The axis label, description, and what high/low scores mean
- The tradition name (so the model has cultural context)
- The source text name and reference
- The passage text (capped at 1,500 characters)

The model returns a JSON object with four fields:

| Field | Type | Range | Meaning |
|-------|------|-------|---------|
| `relevance` | float | 0–1 | How directly does this passage address the axis? |
| `valence` | float | −1 to +1 | Does it support a high (+1) or low (−1) score? |
| `confidence` | float | 0–1 | How certain is the model in its assessment? |
| `justification` | string | — | One sentence of reasoning |

The model is instructed to assess valence from the content of the passage, not from which probe query retrieved it. A passage retrieved by a `probes_high` query can correctly receive a negative valence if its content describes rejection of that feature.

**Rate limiting:** A 0.2-second sleep is inserted between API calls. On rate limit errors, the classifier backs off for 10 seconds.

### Stage 5: Aggregation

**Entry point:** `src/scoring/aggregator.py`

1. **Filter:** Passages with `relevance < min_relevance_threshold` (default: 0.2) are discarded.
2. **Weight:** Each remaining passage receives a weight of `relevance × confidence`.
3. **Weighted mean valence:** Weights are normalized to sum to 1; weighted mean of valences is computed over [−1, 1].
4. **Scale to [0, 100]:** `score = (mean_valence + 1) × 50`
5. **Bootstrap CI:** 1000-iteration bootstrap resampling of the passage set, computing the weighted mean on each resample. The 2.5th and 97.5th percentiles of the bootstrap distribution give the 95% confidence interval.

If no passages survive the relevance filter, the axis score defaults to 50.0 (neutral) with CI [0, 100] and a note recording the failure.

If fewer than 3 passages survive (insufficient for bootstrap), CI is set to [0, 100] to signal unreliability.

### Stage 6: Export

**Entry points:** `src/export/json_exporter.py`, `src/export/evidence_exporter.py`

Two output files are generated in `output/`:

- `chi_dataset_grounded.json` — Full dataset with per-tradition CHI scores, per-axis breakdowns (score, CI, n_passages), and top-10 evidence passages per axis. Each evidence entry includes the passage text, source, reference, translation, relevance, valence, confidence, justification, and contribution weight.

- `evidence_document.md` — Human-readable audit trail mapping every axis score to the specific passages that produced it, with full citation chains (tradition, text name, translation, passage reference).

---

## 5. Probe Query Design

Each axis has 4–8 natural language probe queries defined in `config/pipeline_config.yaml`. Queries are divided into two groups:

- **`probes_high`** — Describe what a high-scoring tradition looks like on this axis. Example for `indifference`: `"the cosmos operates without concern for human welfare"`
- **`probes_low`** — Describe what a low-scoring tradition looks like. Example: `"the divine loves and cares for humanity"`

Both groups are submitted to FAISS search. The LLM then determines valence based on the passage's actual content.

### Tradition-Specific Probes

Generic probes using language like "the supreme being knows all things" are effective for traditions that use that vocabulary directly (Advaita Vedanta, Bhakti Hinduism, Gnosticism). For traditions with distinctive vocabulary, tradition-specific probes are added to ensure relevant passages are retrieved:

**Norse:** Probes reference Ragnarok, Yggdrasil, the Norns, Odin's sacrifices, and kenning-heavy imagery. A Norse text will rarely say "the gods are omniscient"; it will describe Odin trading his eye at Mimir's well.

**Shinto:** Probes reference kami, musubi (creative force), Izanagi and Izanami, ritual purification (misogi), and kegare (impurity). Generic "divine" language underperforms on Shinto corpora.

**Egyptian:** Probes reference Osiris, Ra, the Duat, the Field of Reeds, and Ma'at. The Book of the Dead requires specific vocabulary to retrieve cosmologically relevant passages.

---

## 6. Score Calibration

Lovecraft is the calibration anchor for the upper bound:

- Expected: 70–80 CHI
- Actual v2 score: **73.6** ✓

Buddhism serves as the lower-bound anchor:

- Expected: ~40 CHI (a tradition with active soteriological concern for all sentient beings, an explicit moral order, and a comprehensible path to liberation)
- Actual v2 score: **40.8** ✓

Full v2 rankings (13 traditions):

| Rank | Tradition | CHI |
|------|-----------|-----|
| 1 | Lovecraft | 73.6 |
| 2 | Absurdism | 64.6 |
| 3 | Daoism | 60.3 |
| 4 | Gnosticism | 59.0 |
| 5 | Pantheism | 56.0 |
| 6 | Norse | 55.8 |
| 7 | Bhakti Hinduism | 55.2 |
| 8 | Advaita Vedanta | 54.5 |
| 9 | Aztec | 53.2 |
| 10 | Shinto | 46.7 |
| 11 | Greek | 46.3 |
| 12 | Egyptian | 40.9 |
| 13 | Buddhism | 40.8 |

---

## 7. Confidence Intervals

Confidence intervals are computed via non-parametric bootstrap (1000 iterations, α=0.05, seed=42). Each iteration resamples the valid passage set with replacement and recomputes the weighted mean valence.

**Interpreting CIs:**
- CI width < 20 points: high confidence
- CI width 20–40 points: moderate confidence; score is directionally reliable
- CI width > 40 points: provisional; insufficient or inconsistent evidence
- CI = [0, 100]: fewer than 3 passages survived relevance filtering; treat as no score

---

## 8. Known Limitations

1. **Corpus size imbalance.** Absurdism has 3,020 chunks (multiple Nietzsche and Hume texts); Advaita Vedanta has 142 (one Upanishad translation). More text provides more retrieval diversity but does not guarantee more accurate scores — it depends on textual coverage of each axis.

2. **Translation dependence.** All corpora use public domain translations published before 1928. Different translations may score differently. The Legge Dao De Jing (1891) may emphasize different aspects than the Gia-fu Feng translation.

3. **Probe query coverage asymmetry.** Concrete axes like `cyclical_destruction` are easier to probe ("Ragnarok the doom of the gods when the world sinks into the sea") than abstract axes like `moral_neutrality` or `self_sufficiency`, which depend on philosophical language that varies widely across traditions.

4. **LLM stochasticity.** Claude Sonnet classification has some temperature-based variation. Repeated full pipeline runs typically yield scores within ±3 points per axis. Axis scores with few evidence passages are more sensitive to this variance.

5. **Index dilution.** Small traditions (fewer than 200 chunks) require aggressive overfetching to compete against larger traditions in the shared FAISS index. The retriever compensates for this, but very small corpora may still under-retrieve.

6. **No Jain or Roman corpus.** `jainism` and `roman` entries in the config have `source: "manual_entry"` and were not included in v2 scoring.

---

## 9. Reproducibility

To reproduce v2 scores exactly:

1. Use Python 3.9, `all-MiniLM-L6-v2`, FAISS `IndexFlatIP`, bootstrap seed=42
2. Use corpus sources as listed in `config/pipeline_config.yaml`
3. Use `min_relevance_threshold: 0.2` and `top_k_retrieval: 20`
4. Run `python src/main.py` for full pipeline
5. Verify: `python src/export/compute_chi_v1.py --verify`

Minor score variation (~±3 points) is expected due to LLM classification stochasticity. The bootstrap seed is fixed at 42, so CI bounds will be stable across runs given the same classifications.
