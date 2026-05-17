# CHI-NLP Pipeline

**Textually-grounded Cosmic Horror Index scoring across 13 cosmological traditions.**

Semantic retrieval + LLM classification on 14,096 public-domain text chunks. Every score traces to specific passages with relevance, valence, confidence, and justification.

---

## v2 Results

| Rank | Tradition | CHI | Notable |
|------|-----------|-----|---------|
| 1 | Lovecraft | **73.6** | Calibration anchor |
| 2 | Absurdism | **64.6** | Nietzsche, Hume, Lucretius, Russell |
| 3 | Daoism | **60.3** | Tao's self-sufficiency and moral neutrality |
| 4 | Gnosticism | **59.0** | High incomprehensibility, creation-without-consent |
| 5 | Pantheism | **56.0** | High self-sufficiency, but low awe/madness |
| 6 | Norse | **55.8** | Cyclical destruction, creation-without-consent |
| 7 | Bhakti Hinduism | **55.2** | High omniscience/omnipotence, but low indifference |
| 8 | Advaita Vedanta | **54.5** | High self-sufficiency, but low human insignificance |
| 9 | Aztec | **53.2** | High awe/madness and cyclical destruction |
| 10 | Shinto | **46.7** | High awe/madness, but very low indifference |
| 11 | Greek | **46.3** | Gods involved with humans; low indifference |
| 12 | Egyptian | **40.9** | Strong afterlife ethics, low cosmic horror |
| 13 | Buddhism | **40.8** | Compassion and immanence; lowest CHI |

CHI = weighted mean of 10 axes. Indifference, incomprehensibility, and human insignificance carry 2× weight (see [docs/METHODOLOGY.md](docs/METHODOLOGY.md)).

---

## What Is CHI?

The Cosmic Horror Index quantifies structural similarity to Lovecraftian cosmology: a universe that is vast, indifferent, incomprehensible, and in which humans are insignificant. High CHI ≠ "bad" — it measures a specific cosmological signature, not moral quality.

The 10 axes: omniscience, omnipotence, self-sufficiency, **indifference** (2×), **incomprehensibility** (2×), **human_insignificance** (2×), cyclical_destruction, awe_madness, creation_without_consent, moral_neutrality.

---

## Quick Start (Windows / PowerShell)

```powershell
# 1. Create environment
python -m venv .venv
.venv\Scripts\activate

# 2. Install dependencies
pip install -r requirements.txt

# 3. Configure API key
#    Create a file OUTSIDE this repo (never commit API keys):
#      e.g., C:\keys\config.py  with variable ANTHROPIC_API_KEY set to your key
#    Then set _API_CONFIG_DIR in src/scoring/classifier.py and src/main.py

# 4. Download corpus (~15 min)
python tasks.py corpus

# 5. Validate — catches wrong Project Gutenberg IDs before embedding
python tasks.py validate-corpus

# 6. Build FAISS index (~5 min, CPU)
python tasks.py embed

# 7. Check cost before scoring
python tasks.py cost-estimate
# → ~$9.40 for all 13 traditions

# 8. Score (~2 hours, ~$9.40)
python tasks.py score-all

# 9. Export
python tasks.py export
# → output/chi_dataset_grounded.json
# → output/evidence_document.md
```

---

## Task Runner

```bash
python tasks.py corpus                    # Download all corpora
python tasks.py corpus norse shinto       # Specific traditions only
python tasks.py embed                     # Rebuild FAISS index (required after any corpus change)
python tasks.py validate-corpus           # Verify downloads match expected traditions
python tasks.py cost-estimate             # Show API cost before committing spend
python tasks.py cost-estimate --traditions norse shinto
python tasks.py score-all                 # Score all (~$9.40, ~2hr) — asks confirmation if >$15
python tasks.py score norse shinto        # Score specific traditions (~$1.44)
python tasks.py export                    # Export JSON + evidence doc
python tasks.py add-tradition <name>      # Step-by-step guide for adding a tradition
```

---

## Architecture

```
config/pipeline_config.yaml    ← All sources, axes, probes, thresholds
src/
  corpus/
    loader.py      ← Downloads from Gutenberg, sacred-texts.com, ATI; site-specific parsers
    keywords.py    ← Tradition keywords for corpus validation
  preprocessing/
    chunker.py     ← Verse/paragraph chunking (256-token max)
    embedder.py    ← SentenceTransformer all-MiniLM-L6-v2 → FAISS IndexFlatIP
  scoring/
    retriever.py   ← Probe embedding → FAISS search → tradition filter (dynamic overfetch)
    classifier.py  ← Claude Sonnet: relevance + valence + confidence + justification
    aggregator.py  ← Weighted mean valence → [0,100] + bootstrap CI (1000 iterations)
  export/
    json_exporter.py      ← chi_dataset_grounded.json with full metadata
    evidence_exporter.py  ← evidence_document.md with passage citations
tasks.py           ← CLI shortcuts with cost guards
docs/              ← METHODOLOGY.md, RUNBOOK.md, ADDING_A_TRADITION.md
output/            ← chi_dataset_grounded.json, evidence_document.md
```

---

## API Cost (Actual v2 Run)

| Item | Value |
|------|-------|
| API calls | 2,600 (13 × 10 axes × 20 passages) |
| Input tokens | ~1,820,000 |
| Output tokens | ~260,000 |
| Input cost | ~$5.46 |
| Output cost | ~$3.90 |
| **Total** | **~$9.40** |
| Time (CPU) | ~2 hours |

Per tradition: ~$0.72, ~10 minutes.

`python tasks.py cost-estimate` shows estimates before any API calls. `score-all` prompts for confirmation if cost exceeds $15.

---

## Corpus Sources

All texts are public domain (pre-1928 publication or translation):

| Tradition | Primary Sources |
|-----------|----------------|
| Lovecraft | Project Gutenberg complete works |
| Absurdism | Nietzsche (PG#1998, PG#4363), Hume (PG#4583), Lucretius (PG#785), Russell (PG#25447) |
| Daoism | Dao De Jing PG#216, Zhuangzi PG#59709 (Giles) |
| Gnosticism | Nag Hammadi texts via gnosis.org |
| Norse | Poetic Edda PG#73533, Prose Edda PG#18947 |
| Buddhism | Dhammapada PG#2017, Sutta Nipata + Majjhima Nikaya (AccessToInsight), Light of Asia PG#8920 |
| Advaita Vedanta | Upanishads PG#3283 (Paramananda) |
| Bhakti Hinduism | Bhagavad Gita PG#2388 (Edwin Arnold) |
| Greek | Hesiod Theogony PG#348, Homeric Hymns PG#16338 |
| Egyptian | Book of the Dead PG#7145 (Budge) |
| Shinto | Aston's Shinto PG#55973, Hearn's Japan PG#5979 |
| Aztec | Spence Mexico & Peru PG#53080, Popol Vuh PG#56550 |
| Pantheism | Spinoza Ethics |

---

## Known Gaps

- **Buddhism (40.8):** Correct result — Buddhism genuinely emphasizes compassion over cosmic horror.
- **Advaita Vedanta** CIs wider than ideal (only 142 chunks). More Upanishad translations would help.
- **Aztec incomprehensibility** n=7 passages — more Mesoamerican texts needed.
- **Greek cyclical destruction** n=4 — Orphic texts would strengthen coverage.

---

## Adding a Tradition

See [docs/ADDING_A_TRADITION.md](docs/ADDING_A_TRADITION.md) for full workflow.

```bash
# 1. Add to config/pipeline_config.yaml + src/corpus/keywords.py
python tasks.py corpus your_tradition
python tasks.py validate-corpus    # ← never skip
python tasks.py embed
python tasks.py score your_tradition
python tasks.py export
```

---

## Documentation

- [docs/METHODOLOGY.md](docs/METHODOLOGY.md) — Axes, weights, probe design, aggregation, CIs
- [docs/RUNBOOK.md](docs/RUNBOOK.md) — All 6 incidents from v2 run, with fixes and prevention
- [docs/ADDING_A_TRADITION.md](docs/ADDING_A_TRADITION.md) — Step-by-step guide

---

## License

MIT — see [LICENSE](LICENSE). All corpus texts are public domain.
