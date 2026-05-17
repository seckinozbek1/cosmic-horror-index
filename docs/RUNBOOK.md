# CHI-NLP Pipeline — Operational Runbook

**Audience:** A future engineer or Claude Code session picking up this project after the first production run.

**Status:** All six incidents documented below occurred during the initial production run. Each cost real debugging time. Read this before touching the corpus config or running at scale.

---

## Table of Contents

1. [Architecture Overview](#architecture-overview)
2. [Pipeline Stages Quick Reference](#pipeline-stages-quick-reference)
3. [Pre-Run Checklist](#pre-run-checklist)
4. [INCIDENT 1 — Wrong Project Gutenberg IDs (6 traditions)](#incident-1--wrong-project-gutenberg-ids-6-traditions)
5. [INCIDENT 2 — Retriever Finds 0 Passages for Small Traditions](#incident-2--retriever-finds-0-passages-for-small-traditions)
6. [INCIDENT 3 — Stale Index Bug (Scoring Ran Against Old Embeddings)](#incident-3--stale-index-bug-scoring-ran-against-old-embeddings)
7. [INCIDENT 4 — Per-Tradition Scoring Overwrite Bug](#incident-4--per-tradition-scoring-overwrite-bug)
8. [INCIDENT 5 — ATI Scraper Getting Only Index Page Content](#incident-5--ati-scraper-getting-only-index-page-content)
9. [INCIDENT 6 — Buddhism Scored Low Due to Wrong Text Type](#incident-6--buddhism-scored-low-due-to-wrong-text-type)
10. [Operational Procedures](#operational-procedures)
11. [Debugging Playbook](#debugging-playbook)
12. [Time and Cost Reference](#time-and-cost-reference)
13. [Data Directory Layout](#data-directory-layout)

---

## Architecture Overview

```
config/pipeline_config.yaml
        │
        ▼
src/corpus/loader.py          Stage 1 — Download + parse sacred texts
        │
        ▼  data/raw/{tradition}/*.json
src/preprocessing/chunker.py  Stage 2a — Verse/paragraph chunking
src/preprocessing/embedder.py Stage 2b — SentenceTransformer (all-MiniLM-L6-v2) + FAISS IndexFlatIP
        │
        ▼  data/embeddings/corpus.index  +  data/embeddings/chunk_metadata.json
           data/processed/chunks.json
src/scoring/retriever.py      Stage 3a — Semantic search per axis per tradition
src/scoring/classifier.py     Stage 3b — Claude Sonnet: relevance / valence / confidence
src/scoring/aggregator.py     Stage 3c — Weighted mean + bootstrap CI
        │
        ▼  data/processed/scoring_results.json
src/export/json_exporter.py   Stage 4a — Grounded JSON dataset
src/export/evidence_exporter.py Stage 4b — Full evidence markdown
        │
        ▼  output/chi_dataset_grounded.json
           output/evidence_document.md
```

**Key design choices that matter for debugging:**

- The FAISS index is rebuilt from scratch on every `--stage embed` run. It is NOT incremental. Adding one new corpus invalidates all prior embeddings.
- `scoring_results.json` is the sole state file for scores. Partial runs (using `--tradition`) merge into it. Full runs (`--stage score` without a tradition filter) start from `results = {}` and overwrite everything.
- The embedding model (`all-MiniLM-L6-v2`) runs on CPU. No GPU required, but expect ~5 min for 14k vectors.
- API keys are loaded from an external directory (`api_keys_seckin/config.py`), not from `.env`. See `src/scoring/classifier.py` and `src/main.py:load_config()`.

---

## Pipeline Stages Quick Reference

```powershell
# Full pipeline (all stages, all traditions)
python src/main.py

# Stage by stage
python src/main.py --stage corpus       # Download and cache texts to data/raw/
python src/main.py --stage embed        # Chunk + embed + rebuild FAISS index
python src/main.py --stage score        # Retrieve + classify + aggregate
python src/main.py --stage export       # Write output/ files

# Targeted (faster iteration)
python src/main.py --stage score --tradition norse
python src/main.py --stage score --tradition norse --axis indifference
python src/main.py --stage score --dry-run   # No API calls; just verify retrieval

# Retrieval quality check (before spending on API)
python src/scripts/check_retrieval.py norse
python src/scripts/check_retrieval.py lovecraft

# Verify index size
python -c "import faiss; idx = faiss.read_index('data/embeddings/corpus.index'); print(f'Index: {idx.ntotal} vectors')"
```

---

## Pre-Run Checklist

Run these steps before any full or partial scoring run. Skipping them was the cause of multiple incidents.

```powershell
# 1. Verify index is current — compare ntotal against chunk count
python -c "import faiss; idx = faiss.read_index('data/embeddings/corpus.index'); print(f'Index: {idx.ntotal} vectors')"
python -c "import json; d=json.load(open('data/processed/chunks.json')); print(f'Chunks: {len(d)}')"
# These numbers must match. If they don't, re-run --stage embed before scoring.

# 2. Verify scoring_results.json is not newer than corpus.index
#    (see Incident 3 for why this matters)
Get-Item data\embeddings\corpus.index | Select-Object Name, LastWriteTime
Get-Item data\processed\scoring_results.json | Select-Object Name, LastWriteTime
# corpus.index should be OLDER than or same age as scoring_results.json.
# If corpus.index is NEWER, your scores were computed against an old index.

# 3. Spot-check corpus content for any new or recently changed traditions
python -c "
import json
from pathlib import Path
for f in sorted(Path('data/raw/norse').glob('*.json')):
    d = json.loads(f.read_text(encoding='utf-8'))
    print(d['name'], '-', len(d['passages']), 'passages')
    for p in d['passages'][:2]:
        print(' ', p['text'][:100])
"
# The first few passages should be actual Norse mythology content.
# If you see Balzac, Ben Jonson, Chesterfield, sci-fi, or Victorian novels — stop.
# See Incident 1.

# 4. Check for placeholder-only files (manual_entry texts never downloaded)
python -c "
import json
from pathlib import Path
for f in Path('data/raw').rglob('*.json'):
    d = json.loads(f.read_text(encoding='utf-8'))
    if all(p.get('type') == 'placeholder' for p in d.get('passages', [])):
        print('PLACEHOLDER:', f)
"
```

---

## INCIDENT 1 — Wrong Project Gutenberg IDs (6 traditions)

**Date:** First production run  
**Time cost:** ~3 hours  
**Traditions affected:** Norse (both Eddas), Shinto (Aston), Daoism (Zhuangzi), Egyptian (Book of the Dead), Greek (Homeric Hymns)

### Symptom

After a full pipeline run, the first passages of several traditions contained completely unrelated text:

| corpus_id | What we got | What we expected |
|-----------|-------------|------------------|
| `poetic_edda` | "THE ATHEIST'S MASS By Honore De Balzac" | Voluspa, Havamal |
| `prose_edda` | Dark Victorian novel | Gylfaginning (Snorri) |
| `aston_shinto` | Ben Jonson plays | W.G. Aston's Shinto |
| `zhuangzi` | Chesterfield's Letters to His Son | Herbert Giles Zhuangzi |
| `egyptian_book_of_dead` | "Outbreak of Peace" (sci-fi, H.B. Fyfe) | Wallis Budge Book of the Dead |
| `homeric_hymns` | Catharine Furze (Victorian novel) | Andrew Lang Homeric Hymns |
| `upanishads_bhagavata` | Howells essays on Vedanta (too thin) | Bhagavata Purana cosmology |

### Root Cause

Project Gutenberg IDs were guessed rather than verified against the actual PG catalog. PG IDs are not stable across time and do not follow any predictable pattern by subject matter. The wrong IDs pointed to whatever text happened to occupy those numbers.

### Correct ID Mappings

| corpus_id | Wrong PG# | What that ID actually is | Correct source |
|-----------|-----------|--------------------------|----------------|
| `poetic_edda` | PG#1220 | Balzac's Atheist's Mass | PG#73533 |
| `prose_edda` | PG#21285 | Dark Victorian novel | PG#18947 |
| `aston_shinto` | PG#4081 | Ben Jonson's plays | PG#55973 |
| `zhuangzi` | PG#3352 | Chesterfield's Letters | `/files/59709/59709-0.txt` (see note below) |
| `egyptian_book_of_dead` | PG#29989 | "Outbreak of Peace" sci-fi | PG#7145 |
| `homeric_hymns` | PG#6023 | Catharine Furze novel | PG#16338 |
| `upanishads_bhagavata` | PG#3384 | Howells Vedanta essays | REMOVED from config |

**Zhuangzi URL note:** PG#59709 returns a 404 when accessed via the standard `/cache/epub/NNNN/pgNNNN.txt` URL pattern. Use the `/files/` path instead:
```
https://www.gutenberg.org/files/59709/59709-0.txt
```
This is already set correctly in `config/pipeline_config.yaml`. Do not revert it to the `/cache/epub/` form.

### Detection Method

After the embed stage, read the first 3 passages from each corpus file directly:

```python
import json
from pathlib import Path

for tradition_dir in sorted(Path('data/raw').iterdir()):
    if not tradition_dir.is_dir():
        continue
    for f in sorted(tradition_dir.glob('*.json')):
        d = json.loads(f.read_text(encoding='utf-8'))
        print(f"\n=== {d['corpus_id']} ({tradition_dir.name}) ===")
        print(f"File says: {d['name']}")
        for p in d['passages'][:3]:
            print(' ', p['text'][:120])
```

Wrong content is immediately obvious: you will see author names and titles in the first paragraph that have nothing to do with the expected tradition.

### Prevention Rules

1. **Never guess a PG ID.** Before adding a text to `config/pipeline_config.yaml`, fetch `https://www.gutenberg.org/ebooks/NNNN` and confirm the title matches.
2. **HEAD-check the `.txt` URL** before committing it to config. Some texts use `/cache/epub/NNNN/pgNNNN.txt`; others use `/files/NNNN/NNNN-0.txt`. Both patterns exist; only one works for any given ID.
3. **Add a corpus validation step** to your pre-run checklist. The spot-check command in the Pre-Run Checklist above will catch wrong content within seconds.

---

## INCIDENT 2 — Retriever Finds 0 Passages for Small Traditions

**Date:** First production run, scoring stage  
**Time cost:** ~1.5 hours  
**Traditions affected:** Norse (1711 chunks), Shinto (1174 chunks)

### Symptom

Both Norse and Shinto scored `50.0` on every axis — the neutral default that `ScoreAggregator.aggregate()` returns when `n_passages = 0`. The traditions existed in the FAISS index (their chunks were visible in `chunk_metadata.json`) but the retriever returned zero passages for them.

### Root Cause

The FAISS index had grown to 14,096 total vectors after adding large corpora (absurdism, Buddhism). The overfetch factor in `retriever.py` was hardcoded as `top_k * 5 = 100`.

The problem: the retriever searches the full index globally, then filters results by tradition. Norse comprised 1711/14096 = 12% of the index. At 100 global results, you statistically expect ~12 Norse results per probe — but only if the query is a perfect match. With probe queries written in modern English (not kenning-heavy Old Norse), cosine similarity was low, and the Norse chunks rarely appeared in the top 100 global results.

Shinto was worse: 1174/14096 = 8%, yielding ~8 expected results per probe. Any probe that didn't fire well left the tradition with zero evidence.

### Fix Applied

`src/scoring/retriever.py` — the overfetch calculation is now proportional to the tradition's share of the index:

```python
n_total = self.index.ntotal
n_tradition = len(tradition_indices)
overfetch_k = min(
    max(self.top_k * 5, int(self.top_k * n_total / max(n_tradition, 1) * 2)),
    n_total
)
```

This scales dynamically: Norse with 12% of the index gets `20 * 14096/1711 * 2 ≈ 330` global results, instead of 100. The 2x multiplier provides safety margin. The outer `min(..., n_total)` prevents requesting more results than the index contains.

Additionally, an early-exit that halted after the first probe returned enough candidates was removed. All probes are now exhausted to maximize coverage.

Tradition-specific probe queries were also added in `config/pipeline_config.yaml` for Norse and Shinto axes to improve cosine similarity:
- Norse: Ragnarok, Yggdrasil, kenning-style descriptions, Norns, fate
- Shinto: kami, musubi, Izanagi/Izanami, kegare, misogi

### Quick Verification

Before any scoring run, verify retrieval works for your smallest traditions:

```python
from src.scoring.retriever import SemanticRetriever
from pathlib import Path

r = SemanticRetriever(Path("data/embeddings"), "all-MiniLM-L6-v2", top_k=20)

# Test broad probes first (should never be 0 if tradition is in the index)
for tradition in ["norse", "shinto", "jainism"]:
    result = r.retrieve(tradition, ["god universe cosmos power divine fate"], [])
    print(f"{tradition}: {len(result)} passages")
    if result:
        print(f"  First: {result[0]['text'][:100]}")
```

If you get 0 for a tradition that has hundreds of chunks in the index, the overfetch formula is not scaling enough. Check if `n_total` has grown much larger while the tradition stayed the same size.

### Rule of Thumb

When any tradition is less than 5% of the total index, watch it carefully. The current formula (`top_k * n_total / n_tradition * 2`) scales correctly, but if `n_total` grows beyond ~50k vectors and the tradition stays at ~1k chunks, you should verify retrieval quality directly.

---

## INCIDENT 3 — Stale Index Bug (Scoring Ran Against Old Embeddings)

**Date:** First production run  
**Time cost:** ~2 hours (including the re-score run)  
**Traditions affected:** Norse, Shinto (both showed 0 passages after the Incident 2 fix was applied)

### Symptom

Applied the Incident 2 fix to `retriever.py`, re-ran `--stage embed` with the corrected corpus (corrected PG IDs from Incident 1 plus the enlarged Buddhism corpus), then ran `--stage score`. Norse and Shinto still showed `n_passages = 0`. The Incident 2 fix appeared not to have worked.

Inspection revealed the real problem: `data/processed/scoring_results.json` had a timestamp of **15:46**, but `data/embeddings/corpus.index` had a timestamp of **16:54**. The scoring results were written over an hour before the embed stage finished. The score run had executed against the old, smaller index (without the corrected corpora).

### Root Cause

Multiple processes were running simultaneously in the same terminal session. A `--stage score` run was still in progress from before the corpus corrections were made. When the embed stage completed and wrote the new `corpus.index`, the in-flight scoring run continued using its already-loaded (old) index. The results written at 15:46 reflected the stale index.

### Fix

Always verify the index timestamp before scoring:

```powershell
# Check timestamps
Get-Item data\embeddings\corpus.index | Select-Object Name, LastWriteTime
Get-Item data\processed\scoring_results.json | Select-Object Name, LastWriteTime
```

The `scoring_results.json` must be **newer** than `corpus.index` for the results to be valid. If `corpus.index` is newer, re-score.

Verify the index vector count matches your current chunk count:

```powershell
python -c "import faiss; idx = faiss.read_index('data/embeddings/corpus.index'); print(f'Index ntotal: {idx.ntotal}')"
python -c "import json; d=json.load(open('data/processed/chunks.json')); print(f'Chunks: {len(d)}')"
```

These must match exactly.

### Prevention

- Never run `--stage score` immediately after changing corpus or re-embedding in the same session if there is any chance of background processes still running.
- After re-embedding: **stop, verify the index size, then start the score run in a fresh terminal**.
- The safest sequence for a corpus change is:

```powershell
# 1. Corpus
python src/main.py --stage corpus
# 2. Wait for it to finish completely. Verify.
python -c "import json; d=json.load(open('data/processed/chunks.json')); print(len(d))" # not yet possible - chunks are from embed stage
# 3. Embed
python src/main.py --stage embed
# 4. Verify index
python -c "import faiss; idx = faiss.read_index('data/embeddings/corpus.index'); print(idx.ntotal)"
# 5. Score (fresh terminal or after the above confirms)
python src/main.py --stage score
```

---

## INCIDENT 4 — Per-Tradition Scoring Overwrite Bug

**Date:** First production run, scoring stage  
**Time cost:** ~45 minutes (re-running all previously scored traditions)  
**Traditions affected:** All previously scored traditions when `--tradition X` was used

### Symptom

After running the full pipeline to score 12 traditions, a single tradition (Norse) was re-scored with the corrected embeddings using:

```powershell
python src/main.py --stage score --tradition norse
```

When the run finished, `data/processed/scoring_results.json` contained only Norse. All 11 other traditions had been silently erased.

### Root Cause

The original `run_score_stage()` in `src/main.py` started unconditionally with:

```python
results = {}
```

At the end of the function it wrote `results` to `scoring_results.json`, overwriting whatever was there. There was no merge logic — a single-tradition run overwrote the entire file.

### Fix Applied

`src/main.py` — `run_score_stage()` now loads and merges when a tradition filter is active:

```python
results_path = PROJECT_ROOT / "data" / "processed" / "scoring_results.json"
if results_path.exists() and traditions:
    results = json.loads(results_path.read_text(encoding="utf-8"))
else:
    results = {}  # Full runs start fresh
```

The condition is: **if a tradition filter (`--tradition`) is active AND the results file already exists, load and merge**. Full runs (no `--tradition` flag) still start from `{}` to ensure a clean slate.

### Prevention

- Always use `--tradition` for incremental/re-score runs. This triggers the merge path.
- Never run `--stage score` (no tradition filter) unless you intend to wipe and re-score everything.
- If you need to re-score multiple specific traditions, run them sequentially with `--tradition`:

```powershell
python src/main.py --stage score --tradition norse
python src/main.py --stage score --tradition shinto
# Each run merges into the existing file
```

---

## INCIDENT 5 — ATI Scraper Getting Only Index Page Content

**Date:** Corpus acquisition stage, first production run  
**Time cost:** ~1 hour (diagnosing + fixing + re-downloading)  
**Traditions affected:** Buddhism (Sutta Nipata, Majjhima Nikaya)

### Symptom

After the corpus download stage, the Buddhism Buddhist corpus had suspiciously thin coverage:

- Sutta Nipata: **8 passages** (expected hundreds)
- Majjhima Nikaya: **6 passages** (expected 1000+)

The passages that did exist were bibliography metadata and section headers, not sutta text. The content looked like:

```
"Translated from the Pali by Thanissaro Bhikkhu. 
 Distributed under Creative Commons..."
```

### Root Cause

`_parse_accesstoinsight()` in `src/corpus/loader.py` was fetching the index page correctly (e.g., `accesstoinsight.org/tipitaka/kn/snp/index.html`), but then extracting paragraph text from the index page itself — which contains only brief bibliographic summaries, not sutta text. It was not following the links on the index page to individual sutta pages.

The `_parse_sacred_texts()` method had link-following logic; `_parse_accesstoinsight()` did not.

A second bug compounded this: the `load_text()` skip condition in `CorpusLoader` was:

```python
if passages and passages[0].get("type") != "placeholder":
```

This checked only the first passage. If a failed sutta fetch had inserted a placeholder entry first, followed by thousands of real passages from a previous partial run, the condition would be `True` and trigger a full re-download — discarding all real content. Fixed to:

```python
if passages and any(p.get("type") != "placeholder" for p in passages):
```

### Fix Applied

`src/corpus/loader.py` — `_parse_accesstoinsight()` now follows links to individual sutta pages, mirroring the pattern in `_parse_sacred_texts()`. The updated method:

1. Detects whether the fetched page is an index page (more than 2 relative `.html` links)
2. If so, follows each sutta link (up to 40 per index page) and extracts paragraph text from `div#main` on each sutta page
3. Falls through to direct extraction for single-text pages

**Results after fix:**

| Text | Before | After |
|------|--------|-------|
| Sutta Nipata | 8 passages | 583 passages |
| Majjhima Nikaya | 6 passages | 1705 passages |

### Detection

When a newly downloaded corpus produces suspiciously few passages for a multi-text tradition, check whether the number of passages is consistent with what the index page contains, not the actual text:

```powershell
python -c "
import json
from pathlib import Path
for f in sorted(Path('data/raw/buddhism').glob('*.json')):
    d = json.loads(f.read_text(encoding='utf-8'))
    print(f\"{d['name']}: {len(d['passages'])} passages\")
    print('  First:', d['passages'][0]['text'][:100])
"
```

If the passage count is in single digits for a text known to have hundreds of sections, and the content looks like bibliographic metadata, the scraper is reading the index page, not the content pages.

---

## INCIDENT 6 — Buddhism Scored Low Due to Wrong Text Type

**CHI result:** 40.8 (lowest of all traditions)  
**Date:** Post-scoring analysis  
**Nature:** Not a bug — a corpus selection problem

### Symptom

Buddhism scored 40.8 CHI, placing it last among all traditions. This was initially suspicious — Buddhist cosmology includes samsara, impermanence, and void teachings that have structural similarities to cosmic horror. A score lower than Roman polytheism seemed wrong.

### Root Cause

The initial Buddhism corpus consisted almost entirely of the **Dhammapada** — a collection of ethical aphorisms ("do not kill", "speak kindly", "right action"). The Dhammapada is primarily an ethical and practical text, not a cosmological one.

The CHI axes probe for: cosmic indifference, divine incomprehensibility, cyclical destruction, human insignificance, moral neutrality. The Dhammapada addresses almost none of these. It explicitly teaches the opposite of cosmic indifference — that the dharma cares about right action and its consequences for the practitioner.

The 40.8 score is not wrong. It accurately reflects what the Dhammapada says. The problem was using the Dhammapada as a proxy for Buddhist cosmology in general.

### Fix Applied

Added cosmologically-relevant Buddhist texts to `config/pipeline_config.yaml`:

| Text | Source | Why it helps |
|------|--------|-------------|
| Sutta Nipata (Atthakavagga) | AccessToInsight | Emptiness/non-self cosmology, radical uncertainty teachings |
| Majjhima Nikaya (MN1, MN22, MN72, MN140) | AccessToInsight | Dependent origination, void teachings, the fire-sermon |
| The Light of Asia (PG#8920) | Project Gutenberg | Narrative of Buddha's awakening with cosmic framing |

**Corpus growth:**

| State | Total passages |
|-------|---------------|
| Before (Dhammapada + Heart Sutra only) | ~80 passages |
| After (full corpus) | 2,742 passages |

**CHI result:** Stayed at 40.8 after re-scoring with the fuller corpus. This is the correct result — Buddhism's emphasis on immanence (Buddha-nature within all things), compassion, and the soteriological path places it structurally far from Lovecraftian cosmic horror. The score is now grounded in 2,742 passages rather than 80, making it far more robust.

### Lesson

A low score is not automatically evidence of a pipeline bug. Before investigating, ask: does the scored text actually contain cosmological content? A score of 40 for an ethical text is correct; a score of 40 for the Voluspa would be suspicious.

---

## Operational Procedures

### Adding a New Tradition

1. Find the text(s) on Project Gutenberg or AccessToInsight.
2. **Verify the PG ID** by loading `https://www.gutenberg.org/ebooks/NNNN` and confirming the title.
3. **HEAD-check the `.txt` URL** — try both `/cache/epub/NNNN/pgNNNN.txt` and `/files/NNNN/NNNN-0.txt`.
4. Add the entry to `config/pipeline_config.yaml`.
5. Run corpus stage for that tradition only: `python src/main.py --stage corpus --tradition <new_tradition>`
6. Spot-check the downloaded content: read the first 5 passages and confirm they are the expected text.
7. Re-run embed for **all** traditions (the FAISS index is rebuilt from scratch): `python src/main.py --stage embed`
8. Verify the new index size: `python -c "import faiss; idx = faiss.read_index('data/embeddings/corpus.index'); print(idx.ntotal)"`
9. Run a retrieval check before spending on API: `python src/scripts/check_retrieval.py <new_tradition>`
10. Score: `python src/main.py --stage score --tradition <new_tradition>`

### Re-Scoring a Single Tradition

```powershell
# Always use --tradition to trigger merge logic (Incident 4)
python src/main.py --stage score --tradition <tradition_id>
```

After re-scoring, verify the other traditions are still present in `scoring_results.json`:

```python
import json
d = json.load(open('data/processed/scoring_results.json'))
print(list(d.keys()))
```

### Full Re-Run from Scratch

```powershell
# 1. Optionally clear old data (corpus files are cached — only clear if you changed sources)
Remove-Item -Recurse data\embeddings\* -Force
Remove-Item data\processed\chunks.json, data\processed\scoring_results.json -ErrorAction SilentlyContinue

# 2. Download corpora (uses cached files if data/raw/ already has them)
python src/main.py --stage corpus

# 3. Rebuild embeddings
python src/main.py --stage embed

# 4. Verify index
python -c "import faiss; idx = faiss.read_index('data/embeddings/corpus.index'); print(f'Vectors: {idx.ntotal}')"

# 5. Dry run — inspect retrieval quality before spending on API
python src/main.py --stage score --dry-run

# 6. Full score
python src/main.py --stage score

# 7. Export
python src/main.py --stage export
```

---

## Debugging Playbook

### Symptom: Tradition scores all 50.0 (neutral default)

The aggregator returns 50.0 with `n_passages = 0` when no passages meet the relevance threshold. The retriever returned nothing.

**Step 1 — confirm the tradition is in the index:**

```python
import json
meta = json.load(open('data/embeddings/chunk_metadata.json'))
tradition_chunks = [m for m in meta if m['tradition'] == 'your_tradition']
print(f"Chunks in index: {len(tradition_chunks)}")
if tradition_chunks:
    print("Sample:", tradition_chunks[0]['text'][:100])
```

If 0: the embed stage never processed this tradition. Re-run `--stage embed`.

If > 0 but wrong content: see Incident 1. Check the raw corpus file.

**Step 2 — test retrieval directly:**

```python
from src.scoring.retriever import SemanticRetriever
from pathlib import Path

r = SemanticRetriever(Path("data/embeddings"), "all-MiniLM-L6-v2", top_k=20)

# Start with a very broad probe to verify any retrieval at all
result = r.retrieve("your_tradition", ["god universe cosmos creation destruction"], [])
print(f"Broad probe: {len(result)} passages")

# Then check a specific axis
result = r.retrieve("your_tradition", ["the cosmos is indifferent to human suffering"], [])
print(f"Indifference probe: {len(result)} passages")
```

If broad probe returns 0: the overfetch formula is probably insufficient for the tradition's size relative to the index. Check `n_total` and `n_tradition` values and compare with the formula in `src/scoring/retriever.py`.

**Step 3 — check the index is not stale:**

```powershell
Get-Item data\embeddings\corpus.index | Select-Object LastWriteTime
Get-Item data\processed\scoring_results.json | Select-Object LastWriteTime
```

If `corpus.index` is newer than `scoring_results.json` for the tradition you're debugging: stale index. See Incident 3.

### Symptom: Wrong content in scored passages

Passages in `scoring_results.json` evidence fields contain text unrelated to the tradition.

**Check the raw corpus:**

```python
import json
from pathlib import Path

# Replace 'norse' and 'poetic_edda' with your tradition/corpus
f = list(Path('data/raw/norse').glob('poetic_edda*.json'))[0]
d = json.loads(f.read_text(encoding='utf-8'))
print("File claims to be:", d['name'])
print("Source URL:", d['source'])
print()
for p in d['passages'][:5]:
    print(p['text'][:150])
    print('---')
```

If the content is wrong, the source URL pointed to the wrong text. Delete the file, fix the URL in `config/pipeline_config.yaml`, re-run `--stage corpus --tradition X`, then re-embed and re-score.

### Symptom: Very few passages in a scraped HTML corpus

Expected 500+ passages, got 8-20.

Check whether the scraper hit an index page instead of following links:

```python
import json
from pathlib import Path

f = list(Path('data/raw/buddhism').glob('pali_canon_sutta_nipata*.json'))[0]
d = json.loads(f.read_text(encoding='utf-8'))
print(f"Total passages: {len(d['passages'])}")
# Check content type
for p in d['passages'][:5]:
    print(p['text'][:100])
```

If the content looks like "Translated from the Pali by..." or section headers: the scraper read the index page. This is Incident 5's pattern. The `_parse_accesstoinsight()` method in `src/corpus/loader.py` now handles this, but other HTML sources may need similar fixes.

### Symptom: `scoring_results.json` missing traditions after a `--tradition` run

See Incident 4. Verify you are running a version of `src/main.py` that includes the merge logic:

```python
# src/main.py, run_score_stage() should contain:
results_path = PROJECT_ROOT / "data" / "processed" / "scoring_results.json"
if results_path.exists() and traditions:
    results = json.loads(results_path.read_text(encoding="utf-8"))
else:
    results = {}
```

If your version still has `results = {}` unconditionally at the top of `run_score_stage()`, it has not been patched.

### Symptom: JSON parse errors from classifier

```
WARNING  chi-pipeline.classifier: JSON parse error: ...
```

Claude occasionally returns JSON wrapped in markdown fences or with minor formatting deviations. The classifier strips ` ```json ` and ` ``` ` fences before parsing. If errors persist, check whether the model is returning a different wrapper format. The relevant code is in `src/scoring/classifier.py`:

```python
text = text.replace("```json", "").replace("```", "").strip()
result = json.loads(text)
```

A high rate of JSON parse errors (>5% of calls) usually means the prompt is confusing the model. Check `prompts/classification_prompts.py`.

### Symptom: Rate limit errors

The classifier backs off 10 seconds on rate limit responses. For sustained rate-limiting, reduce concurrency. The current pipeline is single-threaded (no async), so if rate limits are hit, it's because the model tier has a low RPM limit. Add a longer `time.sleep()` in `PassageClassifier.classify()` or request a higher tier.

---

## Time and Cost Reference

These figures are from the actual first production run (13 traditions, 10 axes, 20 passages/axis).

### Time Estimates

| Stage | Duration | Notes |
|-------|----------|-------|
| Corpus download | 10–30 min | Depends on network; cached after first run |
| Embed (14k chunks, CPU) | ~5 min | SentenceTransformer on CPU, batch_size=64 |
| Score (13 traditions × 10 axes × 20 passages) | ~2 hours | ~3.5s per API call including network latency |
| Export | < 5 seconds | Pure file I/O |

### API Cost Estimates (claude-sonnet-4, observed)

| Item | Count | Rate | Cost |
|------|-------|------|------|
| API calls | 2,600 (13 × 10 × 20) | — | — |
| Input tokens | ~1,820,000 | $3/MTok | $5.46 |
| Output tokens | ~260,000 | $15/MTok | $3.90 |
| **Total** | | | **~$9.40** |
| Per tradition | ~200 calls | ~$0.72 | |

Use `--dry-run` to verify retrieval quality before committing to a full scoring run. Dry run costs nothing and lets you inspect which passages would be sent to the API.

---

## Data Directory Layout

```
data/
├── raw/                          # Downloaded corpus files (one subdir per tradition)
│   ├── norse/
│   │   ├── poetic_edda_poetic_edda_voluspa_*.json
│   │   └── prose_edda_prose_edda_gylfaginning_*.json
│   ├── buddhism/
│   │   ├── pali_canon_dhammapada.json
│   │   ├── pali_canon_sutta_nipata.json
│   │   ├── pali_canon_majjhima_nikaya_*.json
│   │   └── light_of_asia_the_light_of_asia.json
│   ├── shinto/
│   │   ├── aston_shinto_shinto_*.json
│   │   └── hearn_japan_japan_*.json
│   └── ...
├── embeddings/
│   ├── corpus.index              # FAISS IndexFlatIP — rebuilt on every --stage embed
│   ├── chunk_metadata.json       # Parallel to index rows: tradition, corpus_id, text, source
│   └── embeddings.npy            # Raw numpy array (backup; not used by retriever)
└── processed/
    ├── chunks.json               # All chunks with metadata (output of chunker)
    └── scoring_results.json      # tradition → axis → {score, ci_low, ci_high, n_passages, evidence[]}
```

**Key invariants:**
- `corpus.index` row N corresponds to `chunk_metadata.json` entry N (same order, same count). If these are out of sync, retrieval will return wrong passages silently.
- `chunks.json` is written by `--stage embed` and used by `--stage score` to determine which traditions to process. If it is missing or stale, the score stage will use an incorrect tradition list.
- `scoring_results.json` is always valid JSON even mid-run (it is written atomically at the end of `run_score_stage()`). A run that was killed before completing will leave the file in its pre-run state.

---

## Known Limitations

1. **FAISS index is not incremental.** Adding one tradition requires re-embedding everything. For 14k vectors this takes ~5 minutes; plan accordingly.

2. **`--stage embed` with `--tradition` only embeds that tradition but writes it into the shared index.** This means if you do `--stage embed --tradition norse`, the index will contain only Norse chunks. Always run `--stage embed` without a tradition filter.

3. **Manual-entry texts (Pyramid Texts, De Natura Deorum, Tattvartha Sutra, Ovid Metamorphoses) are placeholders.** They contribute 1 placeholder chunk each to the index. This is harmless but means those traditions cannot be scored until real content is added to `data/raw/{tradition}/`.

4. **The Zhuangzi URL (`/files/59709/59709-0.txt`) is unusual.** The standard `/cache/epub/` form 404s for this ID. Do not "fix" it to the standard form.

5. **AccessToInsight follows up to 40 links per index page.** For large collections (Majjhima Nikaya has 152 suttas), only the first 40 are fetched. This is intentional to keep download time reasonable. The `key_sections` config field does not currently filter which suttas are fetched — it is metadata only.
