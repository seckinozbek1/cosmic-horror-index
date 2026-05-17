# Adding a New Tradition to the CHI Pipeline

This guide walks through adding a new cosmological tradition end-to-end. Follow the steps in order; several depend on the previous one completing successfully.

---

## Step 1: Find a Public Domain Source

The pipeline supports three source types: Project Gutenberg plain text, HTML scraping (sacred-texts.com, AccessToInsight, gnosis.org), and manual entry for texts that require pre-processing.

**Project Gutenberg is the preferred source.** Rules for using it:

- Browse gutenberg.org to find your text, then note the PG ID number in the URL (e.g., `gutenberg.org/ebooks/3283` → PG#3283).
- **Always verify the PG ID before adding it to config.** IDs are not sequential by topic. PG#1234 is not necessarily near PG#1235 in subject matter.
- To verify: fetch `https://www.gutenberg.org/ebooks/NNNN` and confirm the title and author match what you expect.
- Check which URL format the file uses. Most texts use one of:
  - `/cache/epub/NNNN/pgNNNN.txt`
  - `/files/NNNN/NNNN-0.txt`
  - `/files/NNNN/NNNN.txt`
  Fetch the URL directly to confirm it returns the text before adding it.

**Public domain requirement.** The text must be in the public domain:
- Published before 1928, or
- A translation published before 1928 (the translation, not the original)

Most Gutenberg texts qualify. When using a named translation (e.g., "Edwin Arnold, 1879"), include the year in the `translation` field.

---

## Step 2: Add the Corpus Entry to config/pipeline_config.yaml

Find the `corpora:` section and add a new entry. Use an existing entry as a model. The full structure:

```yaml
- id: "your_tradition_primary"
  tradition: "your_tradition"
  texts:
    - name: "Primary Text Name"
      source: "https://www.gutenberg.org/cache/epub/NNNN/pgNNNN.txt"
      format: "plaintext_url"
      translation: "Translator Name (year, public domain, PG#NNNN)"
      chunk_by: "paragraph"     # see chunk strategy table below
      key_sections: ["section1", "section2"]   # optional
```

**`id`** must be unique across the entire `corpora` list. Convention: `{tradition}_{shortname}` (e.g., `norse_poetic_edda`).

**`tradition`** is the string used everywhere in the pipeline to identify the tradition. It must be consistent: the corpus file, the keywords dict, the probe queries, and all pipeline commands all use this string. Stick to lowercase with underscores.

**`chunk_by`** determines how the text is split into embedding chunks:

| Text type | Examples | chunk_by |
|-----------|---------|---------|
| Verse / sutra | Upanishads, Eddas, Theogony, Dhammapada | `"verse"` |
| Mythological prose | Prose Edda, Popol Vuh, Myths of Mexico | `"paragraph"` |
| Philosophical prose | Zhuangzi, Nietzsche, Hume | `"paragraph"` |
| Scripture commentary | Upanishad commentaries | `"paragraph"` |
| Epic poetry (long stanzas) | Light of Asia, Mahabharata | `"paragraph"` |

Use `"verse"` for any text where the natural unit of meaning is a numbered verse, stanza, or sutra. Use `"paragraph"` for everything else. Prose chunking applies a 256-token sliding window with 32-token overlap.

**`key_sections`** is optional. It provides hints to the loader for extracting specific chapters or sections from longer texts. Only useful for texts where the cosmologically relevant material is concentrated in identifiable sections (e.g., Book I of the Metamorphoses for creation). If the whole text is relevant, omit this field.

**Adding multiple texts for one tradition** is supported and encouraged. Add additional entries under `texts:` for the same `tradition` string. The embedder and retriever handle multiple source texts transparently:

```yaml
- id: "your_tradition_secondary"
  tradition: "your_tradition"     # same tradition string
  texts:
    - name: "Second Text Name"
      source: "https://..."
      format: "plaintext_url"
      translation: "..."
      chunk_by: "paragraph"
```

---

## Step 3: Add Tradition Keywords to src/corpus/keywords.py

Open `src/corpus/keywords.py` and add an entry to the `TRADITION_KEYWORDS` dict:

```python
"your_tradition": ["keyword1", "keyword2", "keyword3", "keyword4",
                   "keyword5", "keyword6"],
```

**What makes a good keyword:**
- Appears in the target text with high frequency
- Unlikely to appear in unrelated texts (avoid generic words like "god", "soul", "death")
- Case-insensitive matching is used, so lowercase is sufficient
- The validator checks only the first ~2000 characters of each downloaded file, so prefer words that appear early in the text

**How many:** 6–10 keywords is sufficient. More is not necessarily better if the extras are generic.

**Examples from existing traditions:**

- `norse`: `["odin", "yggdrasil", "valhalla", "ragnar", "asgard", "norns"]`
- `gnosticism`: `["sophia", "demiurge", "pleroma", "gnosis", "barbelo", "archon"]`
- `shinto`: `["kami", "izanagi", "izanami", "amaterasu", "musubi", "shrine"]`

These keywords are used exclusively by the corpus validator (`python src/main.py --stage corpus` + validate step). They do not affect scoring.

---

## Step 4: Add Tradition-Specific Probe Queries (If Needed)

Check the existing probe queries in `config/pipeline_config.yaml` under `axes:`. For each axis, there are already generic probes that work well for many traditions. You do not need to add custom probes unless:

- The tradition uses distinctive vocabulary that the generic probes would miss
- The tradition's texts are highly metaphorical or poetic (retrieval on abstract language requires concrete probes)
- Early test retrieval (`--dry-run`, see Step 8) shows poor results for the tradition

**When adding tradition-specific probes,** add them directly to the `probes_high` or `probes_low` list for the relevant axis. Convention is to append tradition-specific probes after the generic ones:

```yaml
- id: "omniscience"
  probes_high:
    - "the divine knows all things past present and future"   # generic
    - "nothing is hidden from the supreme being"              # generic
    - "Your tradition-specific probe referencing its actual vocabulary"
```

**Examples of effective tradition-specific probes:**

Norse axes use kenning references. For `omniscience`: `"Odin gave his eye at Mimirs well to gain all wisdom and see all hidden things"`. For `cyclical_destruction`: `"Ragnarok the doom of the gods when the world sinks into the sea and rises anew"`.

Shinto uses untranslated terms. For `incomprehensibility`: `"the kami are mysterious forces musubi creative power beyond human comprehension"`. For `moral_neutrality`: `"impurity kegare is not moral evil but a natural state requiring ritual cleansing"`.

Egyptian texts require proper names. For `human_insignificance`, reference the Field of Reeds and the judgment of Osiris rather than abstract language about insignificance.

---

## Step 5: Download the Corpus

```
python src/main.py --stage corpus --tradition your_tradition
```

This runs only the corpus acquisition stage for the specified tradition. Check the log output for any download errors. If a URL fails:

- For Gutenberg, try the alternate URL format (some texts use `/files/NNNN/NNNN-0.txt` rather than `/cache/epub/NNNN/pgNNNN.txt`)
- For HTML sources, the scraper may need adjustment if the site's markup structure differs from existing supported sources

Corpus files are saved to `data/raw/your_tradition/`.

---

## Step 6: Validate the Corpus (Do Not Skip)

```
python src/main.py --stage corpus
```

After downloading, the pipeline runs a keyword-based validator against every downloaded file. Check the output for your tradition. Each file should show `OK` with a count of matched keywords:

```
[OK] your_tradition/primary_text.json — matched 7/8 keywords
```

If you see `SUSPICIOUS`:

```
[SUSPICIOUS] your_tradition/primary_text.json — 0 keywords matched
```

This means the downloaded file does not contain the expected tradition's content. The most common cause is a wrong Project Gutenberg ID. Go back to Step 1 and re-verify the ID by opening the URL directly.

A `SUSPICIOUS` result for even one file will produce meaningless scores. Fix it before proceeding.

---

## Step 7: Rebuild the FAISS Index

```
python src/main.py --stage embed
```

The FAISS index covers all traditions in a single flat file (`data/embeddings/corpus.index`). Adding a new tradition requires a full rebuild — there is no incremental append. The embed stage will:

1. Re-chunk all texts in `data/raw/` (all traditions)
2. Re-embed all chunks using `all-MiniLM-L6-v2`
3. Rebuild and save the `IndexFlatIP`

This step takes several minutes depending on corpus size. The log will report the total vector count when done.

---

## Step 8: Estimate Cost and Verify Retrieval

Before making any API calls, run a dry-run to verify retrieval quality and estimate cost:

```
python src/main.py --stage score --tradition your_tradition --dry-run
```

The dry-run:
- Embeds probe queries and runs FAISS retrieval (no API calls)
- Logs the top retrieved passages for each axis
- Reports how many passages were retrieved per (tradition, axis) pair

**What to check:**
- Each axis should retrieve close to 20 passages. Significantly fewer (< 10) means your tradition is underrepresented in the index or probe queries are not matching.
- Spot-check the logged passage text: does it look cosmologically relevant to the axis? If the top passages for `indifference` are descriptions of ritual practices rather than cosmological statements, adjust the probe queries.

After verifying retrieval looks reasonable, estimate cost:

```
python src/main.py --stage score --dry-run
```

Expected cost for one new tradition: approximately $0.72 (13 traditions × 10 axes × 20 passages = 2,600 API calls; one tradition = 200 calls; at ~500 input + ~100 output tokens per call and Claude Sonnet pricing).

---

## Step 9: Score the New Tradition

```
python src/main.py --stage score --tradition your_tradition
```

This runs semantic retrieval, LLM classification, and aggregation for all 10 axes. Results are merged into `data/processed/scoring_results.json` without overwriting other traditions' scores.

The log reports axis scores in real time:

```
  Axis: indifference
    Retrieved 20 passages
    Score: 61.3 (n=15, CI=[48.2, 74.1])
```

A full tradition run takes 5–15 minutes depending on network latency and rate limiting.

---

## Step 10: Review Results

After scoring completes, check the axis scores for plausibility.

**Common issues and their diagnoses:**

**All axes score near 50.0 with CI [0, 100].** The retriever found 0 passages that passed the relevance filter for every axis. Possible causes:
- The tradition name in the command does not match the `tradition` field in the corpus JSON files. They must be identical strings.
- The corpus was not included in the most recent embed run (rerun Step 7).
- Probe queries are too generic to match the tradition's vocabulary. Add tradition-specific probes (Step 4) and rerun.

**One or two axes score unexpectedly.** Read the evidence passages in `output/evidence_document.md`. Find your tradition and the unexpected axis. The evidence section shows which passages drove the score, with relevance, valence, confidence, and the LLM's justification. If the passages are genuinely off-topic, the probe queries for that axis need refinement.

**Very wide confidence intervals (> 40 points) on multiple axes.** Not enough relevant passages are surviving the relevance filter. Options:
- Add more source texts to the corpus for this tradition (more text = more retrieval candidates)
- Lower `min_relevance_threshold` in `config/pipeline_config.yaml` for this run (see guidance below)

### Setting min_relevance_threshold

The default threshold is `0.2`. Adjust per tradition type:

| Text type | Recommended threshold | Rationale |
|-----------|-----------------------|-----------|
| Doctrinal / philosophical (sutras, Upanishads, Gita) | `0.3` | Text is explicit; low-relevance passages are noise |
| Mythological prose (Eddas, Theogony, Popol Vuh) | `0.2` | Cosmological meaning is implicit in narrative |
| Highly metaphorical / poetic (Vedic hymns, verse epics) | `0.15` | Relevant passages use indirect language |

Change the threshold in `config/pipeline_config.yaml`:
```yaml
min_relevance_threshold: 0.2
```

If you change the threshold, rerun the score stage — classification results are cached in `scoring_results.json`, but aggregation is recomputed on export.

---

## Step 11: Export

```
python src/main.py --stage export
```

This regenerates both output files for all traditions (including the new one):

- `output/chi_dataset_grounded.json` — Full dataset with scores and evidence
- `output/evidence_document.md` — Human-readable passage-level audit

To verify the CHI formula is applied correctly for all traditions:

```
python src/export/compute_chi_v1.py --verify
```

A clean run prints: `All N CHI scores verified.`

---

## Quick Reference: Checklist

- [ ] Source text is public domain; PG ID verified by opening the URL
- [ ] Entry added to `corpora:` in `config/pipeline_config.yaml` with correct `tradition` string, URL, and `chunk_by`
- [ ] Keywords added to `TRADITION_KEYWORDS` in `src/corpus/keywords.py`
- [ ] Tradition-specific probe queries added (if needed)
- [ ] Corpus downloaded: `python src/main.py --stage corpus --tradition your_tradition`
- [ ] Corpus validated: every file shows `OK`
- [ ] FAISS index rebuilt: `python src/main.py --stage embed`
- [ ] Dry-run retrieval verified: passages look relevant, count is near 20 per axis
- [ ] Scoring run: `python src/main.py --stage score --tradition your_tradition`
- [ ] Results reviewed: no all-50 axes, no unexplained outliers
- [ ] Exported: `python src/main.py --stage export`
- [ ] CHI formula verified: `python src/export/compute_chi_v1.py --verify`
