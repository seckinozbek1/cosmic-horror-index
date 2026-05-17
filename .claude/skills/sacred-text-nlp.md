---
name: sacred-text-nlp
description: Reusable methodology for NLP on historical, religious, and philosophical texts — semantic retrieval, LLM classification, and corpus acquisition from public domain sources.
metadata:
  type: reference
---

# Sacred Text NLP — Reusable Methodology

For any project doing NLP on historical, religious, or philosophical texts. Validated on the CHI pipeline (13 traditions, 14k-chunk FAISS index, Claude Sonnet classification).

---

## 1. Project Gutenberg Source Verification

**Never guess PG IDs.** IDs are allocated by submission date, not by topic.

### Verification workflow
1. Fetch `https://www.gutenberg.org/ebooks/NNNN` — read the HTML title
2. Confirm the author and title match your expectation
3. Test the .txt URL — try both:
   - `/cache/epub/NNNN/pgNNNN.txt` (standard)
   - `/files/NNNN/NNNN-0.txt` (some older texts)
4. Only then add to config

### What went wrong in production
7 of 13 traditions had wrong PG IDs pointing to unrelated texts (Balzac, Ben Jonson, Chesterfield, Victorian novels, sci-fi). Detected only after embed by reading first chunks. Cost ~3 hours.

### Known PG patterns
- Most modern uploads: `/cache/epub/NNNN/pgNNNN.txt`
- Some older texts: `/files/NNNN/NNNN-0.txt` (PG#59709 Zhuangzi needed this)
- Some multi-volume works: `/files/NNNN/NNNN-8.txt` (utf-8 variant)
- HTML pages (sacred-texts.com): use the `html_scrape` format

---

## 2. Chunking Strategies

Match chunk strategy to text structure:

| Text Type | Example | Strategy | Max Tokens |
|-----------|---------|----------|------------|
| Verse/sutra | Upanishads, Eddas, Theogony | verse (split on blank lines) | 256 |
| Mythological prose | Prose Edda, Popol Vuh | paragraph | 256 |
| Philosophical prose | Zhuangzi, Nietzsche essays | paragraph | 256 |
| Epic poetry | Light of Asia, Mahabharata | paragraph | 256 |
| Aphorisms | Dhammapada, Dao De Jing | verse | 128 |

The key insight: verse texts chunked by paragraph lose logical units; prose texts chunked by verse get fragmented sentences. Match the natural structure.

---

## 3. Probe Query Design for Abstract Concepts

Probe queries are embedded and used for semantic retrieval. They need to match the vocabulary of the target texts, not modern English abstractions.

### Generic probes (always include)
```
"the ultimate reality is incomprehensible to human minds"
"the divine is indifferent to human suffering"
"the cosmos is vast and humans are insignificant"
```

### Tradition-specific probes (add for non-standard vocabulary)

**Norse** (kenning-heavy, Old Norse vocabulary):
```
"Odin hung nine nights on Yggdrasil the world tree to gain the runes"
"Ragnarok the doom of the gods when the world sinks into the sea"
"The Norns weave the destiny of gods and men without mercy"
```

**Shinto** (kami cosmology vocabulary):
```
"the kami are mysterious forces musubi creative power beyond comprehension"
"Izanagi and Izanami created the islands from the primordial void"
"ritual purification misogi required after contact with powerful kami"
```

**Daoist** (paradox-based language):
```
"the Tao that can be named is not the eternal Tao"
"the nameless is the beginning of heaven and earth"
```

**General principle:** If a tradition's texts use specialized vocabulary (kennings, Sanskrit terms, ritual language), add 2–4 tradition-specific probes to at least the 3 high-weight axes (indifference, incomprehensibility, human_insignificance).

---

## 4. Retriever Tuning for Small-Corpus Traditions

**Problem:** When a large shared FAISS index contains many traditions, small traditions get squeezed out by the global top-K search.

**Example:** Norse = 1711/14096 = 12% of index. With `top_k=20` and global search of 100 (`top_k×5`), statistically about 12 of those 100 hits are Norse — but with tradition-filtering after the fact, you need proportionally more global hits.

**Fix (dynamic overfetch):**
```python
n_total = self.index.ntotal
n_tradition = len(tradition_indices)
overfetch_k = min(
    max(self.top_k * 5, int(self.top_k * n_total / max(n_tradition, 1) * 2)),
    n_total
)
```

This scales overfetch so even a tradition with 1% of the index gets adequate coverage.

**Rule of thumb:** If a tradition has < 5% of the index and `top_k * 5 < n_total / n_tradition`, use dynamic overfetch.

---

## 5. min_relevance_threshold by Text Type

The LLM returns `relevance` (0–1) for each passage. Passages below threshold are discarded.

| Text Type | Threshold | Reason |
|-----------|-----------|--------|
| Doctrinal (sutra, upanishad, gita) | 0.3 | Text states concepts explicitly |
| Mythological prose (edda, theogony) | 0.2 | Meaning embedded in narrative |
| Poetic/hymn (rig veda, homeric hymns) | 0.15 | Highly metaphorical, indirect |
| Philosophical prose (Nietzsche, Hume) | 0.25 | Abstract but explicit |

Set in `config/pipeline_config.yaml` as `min_relevance_threshold`.

**Symptom of too-high threshold:** n_passages very low (<5) across axes, scores stuck near 50.0.
**Symptom of too-low threshold:** Wide confidence intervals (CI span >40 points), irrelevant passages in evidence.

---

## 6. LLM Classification Prompt Pattern

The structured classification prompt pattern that works well:

```
System: You are an expert in comparative religion and cosmology. Score passages objectively.

User: Evaluate this passage from [TRADITION] against the axis "[AXIS_LABEL]".

High score (100) means: [HIGH_DESCRIPTION — what a high-scoring tradition looks like]
Low score (0) means: [LOW_DESCRIPTION — what a low-scoring tradition looks like]

Passage:
> [TEXT]

Return JSON:
{
  "relevance": 0.0-1.0,   // how directly this addresses the axis
  "valence": -1.0 to 1.0, // +1 = clearly high-scoring, -1 = clearly low-scoring
  "confidence": 0.0-1.0,  // certainty of assessment
  "justification": "..."   // one sentence
}
```

**Key design choices:**
- `relevance` gates whether the passage is used at all (< threshold → discard)
- `valence` can be negative even for a `probes_high`-retrieved passage (passage argues against the axis)
- `confidence` down-weights uncertain classifications in aggregation
- One-sentence justification creates an auditable evidence trail

---

## 7. Corpus Validation Pattern

After downloading any text, verify it contains tradition-relevant keywords before embedding.

```python
TRADITION_KEYWORDS = {
    "norse": ["odin", "thor", "yggdrasil", "valhalla", "ragnar", "loki"],
    "buddhism": ["buddha", "dharma", "nirvana", "suffering", "dhamma"],
    # ... one entry per tradition
}

def validate(tradition: str, passages: list[dict]) -> bool:
    """Returns True if content looks correct, False if suspicious."""
    keywords = [k.lower() for k in TRADITION_KEYWORDS.get(tradition, [])]
    if not keywords:
        return True  # no keywords defined, skip check
    real = [p for p in passages if p.get("type") != "placeholder"]
    if not real:
        return True  # placeholder — not suspicious, just empty
    sample = " ".join(p.get("text", "")[:300] for p in real[:7]).lower()
    return any(kw in sample for kw in keywords)
```

**Integration point:** Call this in the corpus loader after downloading, before writing to disk. Flag suspicious files with `"suspicious": true` in the JSON and log a WARNING. The embed stage can then skip or warn on suspicious files.

---

## 8. Cost Estimation Formula

For Claude Sonnet API (adjust pricing for other models):

```
cost = (
    n_traditions × n_axes × n_passages_per_axis × avg_input_tokens × input_price_per_mtok / 1e6
) + (
    n_traditions × n_axes × n_passages_per_axis × avg_output_tokens × output_price_per_mtok / 1e6
)
```

Typical values for CHI-style pipeline:
- `n_axes = 10`
- `n_passages_per_axis = 20`
- `avg_input_tokens = 700` (system prompt + axis desc + passage + instructions)
- `avg_output_tokens = 100` (JSON with 4 fields + justification)
- Claude Sonnet: `$3/MTok input`, `$15/MTok output`

**Per-tradition cost:** ~$0.72
**13-tradition run:** ~$9.40 (observed actual cost)

**Rule:** If estimated cost > $15, ask for confirmation before proceeding.

---

## 9. Common Failure Modes

| Symptom | Root Cause | Fix |
|---------|-----------|-----|
| First chunks show wrong author/title | Wrong PG ID | Verify at gutenberg.org/ebooks/NNNN |
| Tradition scores 50.0 with n_passages=0 | Overfetch too low, small tradition | Dynamic overfetch scaling |
| scoring_results.json has old timestamp | Scored against stale FAISS index | Re-score after verifying index timestamp |
| Per-tradition run wiped other traditions | Missing merge logic in score stage | Load existing results when tradition filter active |
| Scraper gets 6–8 passages from index page | Site uses pagination, scraper got only root | Add link-following for chapter/sutta links |
| All axis scores near 0 or 100 | Wrong text for tradition (ethical vs cosmological) | Add cosmologically-relevant texts |
| Wide CI (>40 points) across all axes | Too few passages passing relevance filter | Lower min_relevance_threshold or add more texts |
| Scores vary ±5 between runs | LLM stochasticity | Expected — run 3× and average if precision matters |
