# CHI-NLP Pipeline

**Textually-grounded Cosmic Horror Index scoring from sacred text corpora.**

An NLP pipeline that computes Cosmic Horror Index (CHI) scores for cosmological traditions by:
1. Ingesting digitized sacred texts and scholarly commentaries
2. Chunking and embedding with SentenceTransformer
3. Retrieving relevant passages per axis via FAISS semantic search
4. Classifying each passage with Claude (relevance, valence, confidence)
5. Aggregating into axis scores with bootstrap confidence intervals
6. Exporting grounded JSON dataset + full evidence document

Every score is traceable to specific textual passages.

## Setup

```bash
# Create environment (Python 3.9+)
python -m venv .venv
source .venv/bin/activate  # or .venv\Scripts\activate on Windows

# Install dependencies
pip install -r requirements.txt

# Set API key
export ANTHROPIC_API_KEY=your_key_here
```

## Usage

```bash
# Full pipeline (all stages)
python src/main.py

# Stage by stage
python src/main.py --stage corpus       # 1. Download texts
python src/main.py --stage embed        # 2. Chunk + embed + index
python src/main.py --stage score        # 3. Retrieve + classify + aggregate
python src/main.py --stage export       # 4. Export JSON + evidence doc

# Targeted runs
python src/main.py --tradition buddhism               # One tradition
python src/main.py --axis indifference                 # One axis
python src/main.py --tradition advaita_vedanta --axis incomprehensibility  # Both

# Cost estimation (no API calls)
python src/main.py --stage score --dry-run
```

## Project Structure

```
chi-nlp-pipeline/
├── config/
│   └── pipeline_config.yaml    # All sources, axes, probes, model settings
├── prompts/
│   └── classification_prompts.py  # LLM prompt templates
├── src/
│   ├── main.py                 # Pipeline orchestrator
│   ├── corpus/
│   │   └── loader.py           # Downloads + parses sacred texts
│   ├── preprocessing/
│   │   ├── chunker.py          # Verse/paragraph chunking
│   │   └── embedder.py         # SentenceTransformer + FAISS index
│   ├── scoring/
│   │   ├── retriever.py        # Semantic search per axis per tradition
│   │   ├── classifier.py       # Claude passage classification
│   │   └── aggregator.py       # Weighted aggregation + bootstrap CI
│   └── export/
│       ├── json_exporter.py    # Grounded JSON with citation keys
│       └── evidence_exporter.py # Full evidence markdown document
├── data/
│   ├── raw/                    # Downloaded corpus files
│   ├── processed/              # Chunks, scoring results
│   ├── embeddings/             # FAISS index + vectors
│   └── evidence/               # Passage-level evidence
├── output/                     # Final exports
├── tests/
└── requirements.txt
```

## API Cost Estimate

For 18 traditions × 10 axes × 20 passages = ~3,600 API calls to Claude Sonnet.
At ~500 input tokens + ~100 output tokens per call:
- Input: ~1.8M tokens × $3/MTok = ~$5.40
- Output: ~360K tokens × $15/MTok = ~$5.40
- **Total: ~$11 for a full run**

Use `--dry-run` to verify retrieval quality before committing to API spend.

## Methodology

### Axis Probe Queries
Each axis has 4-6 natural language "probe queries" describing what a high score looks like (e.g., for indifference: "the cosmos operates without concern for human welfare"). These are embedded and used for semantic retrieval.

### Passage Classification
Each retrieved passage is sent to Claude with a structured prompt asking for:
- **Relevance** (0-1): how directly does this address the axis?
- **Valence** (-1 to +1): does it support high or low score?
- **Confidence** (0-1): how confident is the assessment?
- **Justification**: one sentence of reasoning

### Aggregation
Axis score = weighted mean of passage valences (weighted by relevance × confidence), scaled from [-1,1] to [0,100]. Confidence intervals from 1000-iteration bootstrap.

### CHI Computation
CHI = weighted mean of axis scores. Indifference, incomprehensibility, and human insignificance carry 2x weight.

---

## Claude Code Prompt

To continue development with Claude Code, use this prompt:

```
I have a comparative cosmology NLP pipeline at [path/to/chi-nlp-pipeline].
Read the README.md and config/pipeline_config.yaml first.

The pipeline scores sacred texts against a "Cosmic Horror Index" — 
10 axes measuring structural similarity to Lovecraftian cosmology.

Current state: all modules are written, config has full corpus source list.
What I need you to do:

1. Run `python src/main.py --stage corpus` to download available texts
   - Some sources may need scraper adjustments (sacred-texts.com HTML varies)
   - Create fallbacks for texts that can't be auto-scraped
   - For manual_entry texts, create a data/raw/{tradition}/ placeholder

2. Run `python src/main.py --stage embed` to build the FAISS index
   - Verify chunk counts are reasonable (expect 2000-5000 total chunks)
   - Check embedding dimensions match config

3. Run `python src/main.py --stage score --dry-run` first
   - Verify retrieval quality: are the top passages actually relevant?
   - Adjust probe queries in config if retrieval is off
   
4. Run `python src/main.py --stage score --tradition lovecraft` as a test
   - Lovecraft should score ~90+ CHI — if not, the pipeline has issues
   
5. Full run: `python src/main.py`

6. Review output/evidence_document.md — every score should trace to real passages.

Key constraints:
- Use py -3.9 on this machine (Anaconda base env)
- ANTHROPIC_API_KEY is in .env
- Network is unrestricted from local machine
- Total API budget: ~$15 for initial run
```
