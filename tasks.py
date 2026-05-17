#!/usr/bin/env python
"""
CHI Pipeline task runner — shortcuts for common operations.

Usage:
    python tasks.py corpus [tradition ...]     Download/update corpora
    python tasks.py embed                      Chunk + embed + build FAISS index
    python tasks.py score-all                  Score all 13 traditions (~$9, ~2hr)
    python tasks.py score norse shinto         Score specific traditions
    python tasks.py export                     Export JSON dataset + evidence doc
    python tasks.py validate-corpus            Verify downloads match expected traditions
    python tasks.py cost-estimate              Estimate API cost for full run
    python tasks.py cost-estimate --traditions norse shinto
    python tasks.py add-tradition <name>       Instructions for adding a new tradition
"""

import json
import subprocess
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).parent
sys.path.insert(0, str(PROJECT_ROOT))

COST_PER_INPUT_MTOK = 3.0
COST_PER_OUTPUT_MTOK = 15.0
AVG_INPUT_TOKENS = 700
AVG_OUTPUT_TOKENS = 100
AXES_PER_TRADITION = 10
PASSAGES_PER_AXIS = 20
COST_CONFIRM_THRESHOLD = 15.0


# ---------------------------------------------------------------------------
# Commands
# ---------------------------------------------------------------------------

def cmd_corpus(traditions: list[str]):
    if traditions:
        for t in traditions:
            _run(["src/main.py", "--stage", "corpus", "--tradition", t])
    else:
        _run(["src/main.py", "--stage", "corpus"])


def cmd_embed():
    _run(["src/main.py", "--stage", "embed"])


def cmd_score(traditions: list[str]):
    if not traditions:
        print("ERROR: 'score' requires at least one tradition. Use 'score-all' to score everything.")
        sys.exit(1)
    for trad in traditions:
        cost = _cost_for_n(1)
        print(f"Scoring: {trad}  (~${cost:.2f})")
        _run(["src/main.py", "--stage", "score", "--tradition", trad])


def cmd_score_all():
    n = _count_traditions()
    cost = _cost_for_n(n)
    print(f"Scoring all {n} traditions.  Estimated cost: ~${cost:.2f}  (~2hr on cpu)")
    if cost > COST_CONFIRM_THRESHOLD:
        print(f"\nEstimated cost ~${cost:.2f} exceeds ${COST_CONFIRM_THRESHOLD:.0f} budget. Proceed? [y/n] ", end="")
        if input().strip().lower() != "y":
            print("Aborted.")
            sys.exit(0)
    _run(["src/main.py", "--stage", "score"])


def cmd_export():
    _run(["src/main.py", "--stage", "export"])


def cmd_validate():
    """Walk data/raw/ and check each corpus file for tradition-relevant keywords."""
    from src.corpus.keywords import TRADITION_KEYWORDS

    raw_dir = PROJECT_ROOT / "data" / "raw"
    if not raw_dir.exists():
        print("No data/raw/ directory — run 'python tasks.py corpus' first.")
        sys.exit(1)

    suspicious: list[tuple[str, str]] = []
    ok_count = 0
    placeholder_count = 0
    checked = 0

    for tradition_dir in sorted(raw_dir.iterdir()):
        if not tradition_dir.is_dir():
            continue
        tradition = tradition_dir.name
        keywords = [k.lower() for k in TRADITION_KEYWORDS.get(tradition, [])]

        for corpus_file in sorted(tradition_dir.glob("*.json")):
            checked += 1
            try:
                data = json.loads(corpus_file.read_text(encoding="utf-8"))
            except Exception as e:
                print(f"  ERROR        [{tradition}] {corpus_file.name}: {e}")
                continue

            passages = data.get("passages", [])
            real = [p for p in passages if p.get("type") != "placeholder"]

            if not real:
                placeholder_count += 1
                print(f"  PLACEHOLDER  [{tradition}] {corpus_file.name}")
                continue

            if not keywords:
                print(f"  NO_KEYWORDS  [{tradition}] {corpus_file.name}  — add to src/corpus/keywords.py")
                continue

            sample = " ".join(p.get("text", "")[:300] for p in real[:7]).lower()
            matched = [kw for kw in keywords if kw in sample]

            if matched:
                ok_count += 1
                print(f"  OK           [{tradition}] {corpus_file.name}  ({', '.join(matched[:3])})")
            else:
                print(f"  SUSPICIOUS   [{tradition}] {corpus_file.name}  (none of: {keywords[:5]})")
                suspicious.append((tradition, corpus_file.name))

    print(f"\n{'='*64}")
    print(f"Checked: {checked}  |  OK: {ok_count}  |  Placeholder: {placeholder_count}  |  SUSPICIOUS: {len(suspicious)}")

    if suspicious:
        print("\nSUSPICIOUS files — wrong content, verify PG IDs before embedding:")
        for trad, fname in suspicious:
            print(f"  [{trad}] {fname}")
        print("\nFix: fetch https://www.gutenberg.org/ebooks/NNNN to confirm title,")
        print("     then update source URL in config/pipeline_config.yaml.")
        sys.exit(1)
    else:
        print("\nAll files OK — safe to embed.")


def cmd_cost_estimate(traditions: list[str] | None):
    if traditions:
        n = len(traditions)
        label = ", ".join(traditions)
    else:
        n = _count_traditions()
        label = f"all {n} traditions"

    input_tok = n * AXES_PER_TRADITION * PASSAGES_PER_AXIS * AVG_INPUT_TOKENS
    output_tok = n * AXES_PER_TRADITION * PASSAGES_PER_AXIS * AVG_OUTPUT_TOKENS
    input_cost = input_tok / 1_000_000 * COST_PER_INPUT_MTOK
    output_cost = output_tok / 1_000_000 * COST_PER_OUTPUT_MTOK
    total = input_cost + output_cost
    n_calls = n * AXES_PER_TRADITION * PASSAGES_PER_AXIS

    print(f"Cost estimate for {label}:")
    print(f"  API calls:  {n} × {AXES_PER_TRADITION} axes × {PASSAGES_PER_AXIS} passages = {n_calls:,}")
    print(f"  Input:      {input_tok:,} tokens × ${COST_PER_INPUT_MTOK}/MTok = ${input_cost:.2f}")
    print(f"  Output:     {output_tok:,} tokens × ${COST_PER_OUTPUT_MTOK}/MTok = ${output_cost:.2f}")
    print(f"  {'─'*45}")
    print(f"  Total:      ~${total:.2f}")
    print(f"  Time:       ~{round(n_calls * 3.5 / 60):,} minutes at 3.5s/call (cpu)")

    if total > COST_CONFIRM_THRESHOLD:
        print(f"\n  WARNING: Exceeds ${COST_CONFIRM_THRESHOLD:.0f} budget.")
        print(f"  Score subsets: python tasks.py score norse shinto")


def cmd_add_tradition(name: str):
    print(f"""
Steps to add '{name}' to the pipeline:

1. Find a public domain source
   - Prefer Project Gutenberg: https://www.gutenberg.org
   - ALWAYS verify PG ID: fetch https://www.gutenberg.org/ebooks/NNNN and confirm title
   - Check .txt URL works: /cache/epub/NNNN/pgNNNN.txt  OR  /files/NNNN/NNNN-0.txt

2. Add to config/pipeline_config.yaml:

   - id: "{name}_primary"
     tradition: "{name}"
     texts:
       - name: "Primary Text"
         source: "https://www.gutenberg.org/cache/epub/NNNN/pgNNNN.txt"
         format: "plaintext_url"
         translation: "Translator Name (year, PG#NNNN)"
         chunk_by: "paragraph"  # or "verse" for poetry/sutras

3. Add keywords to src/corpus/keywords.py:
   "{name}": ["keyword1", "keyword2", "keyword3", ...],

4. Add tradition-specific probe queries in config/pipeline_config.yaml
   (especially for texts with unusual vocabulary — poetry, mythology)

5. Download corpus:
   python tasks.py corpus {name}

6. Validate (CRITICAL — catches wrong PG IDs immediately):
   python tasks.py validate-corpus

7. Rebuild FAISS index (covers all traditions):
   python tasks.py embed

8. Estimate cost:
   python tasks.py cost-estimate --traditions {name}

9. Score:
   python tasks.py score {name}

10. Export:
    python tasks.py export

See docs/ADDING_A_TRADITION.md for detailed guidance and min_relevance_threshold tuning.
""")


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _run(args: list[str]):
    cmd = [sys.executable] + args
    result = subprocess.run(cmd, cwd=PROJECT_ROOT)
    if result.returncode != 0:
        sys.exit(result.returncode)


def _cost_for_n(n: int) -> float:
    input_tok = n * AXES_PER_TRADITION * PASSAGES_PER_AXIS * AVG_INPUT_TOKENS
    output_tok = n * AXES_PER_TRADITION * PASSAGES_PER_AXIS * AVG_OUTPUT_TOKENS
    return (input_tok / 1e6 * COST_PER_INPUT_MTOK) + (output_tok / 1e6 * COST_PER_OUTPUT_MTOK)


def _count_traditions() -> int:
    try:
        import yaml
        cfg = yaml.safe_load((PROJECT_ROOT / "config" / "pipeline_config.yaml").read_text())
        return len({c["tradition"] for c in cfg.get("corpora", [])})
    except Exception:
        return 13  # fallback


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def main():
    args = sys.argv[1:]
    if not args:
        print(__doc__)
        sys.exit(0)

    cmd = args[0]
    rest = args[1:]

    if cmd == "corpus":
        cmd_corpus(rest)
    elif cmd == "embed":
        cmd_embed()
    elif cmd == "score-all":
        cmd_score_all()
    elif cmd == "score":
        cmd_score(rest)
    elif cmd == "export":
        cmd_export()
    elif cmd == "validate-corpus":
        cmd_validate()
    elif cmd == "cost-estimate":
        traditions = None
        if "--traditions" in rest:
            idx = rest.index("--traditions")
            traditions = rest[idx + 1:]
        cmd_cost_estimate(traditions)
    elif cmd == "add-tradition":
        if not rest:
            print("Usage: python tasks.py add-tradition <name>")
            sys.exit(1)
        cmd_add_tradition(rest[0])
    else:
        print(f"Unknown command: {cmd}")
        print(__doc__)
        sys.exit(1)


if __name__ == "__main__":
    main()
