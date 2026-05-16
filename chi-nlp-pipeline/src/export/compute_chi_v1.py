"""
Cosmic Horror Index (CHI) Calculator

Computes weighted composite scores for cosmological systems
and generates ranked outputs, comparative analyses, and chart data.

Usage:
    python src/compute_chi.py                    # full pipeline
    python src/compute_chi.py --format markdown  # markdown table output
    python src/compute_chi.py --format csv       # csv output
    python src/compute_chi.py --verify           # verify CHI scores match dataset
"""

import json
import argparse
import csv
import sys
from pathlib import Path

DATA_PATH = Path(__file__).parent.parent / "data" / "cosmologies.json"
OUTPUT_DIR = Path(__file__).parent.parent / "output"


def load_data(path: Path = DATA_PATH) -> dict:
    with open(path) as f:
        return json.load(f)


def compute_chi(scores: dict, axes: list) -> float:
    """
    Compute Cosmic Horror Index as weighted mean.
    
    Weights are defined per-axis in the metadata.
    Default: indifference, incomprehensibility, human_insignificance = 2x
    Everything else = 1x
    """
    weight_map = {a["id"]: a["weight"] for a in axes}
    total_weight = 0
    weighted_sum = 0
    for axis_id, value in scores.items():
        w = weight_map.get(axis_id, 1)
        weighted_sum += value * w
        total_weight += w
    return round(weighted_sum / total_weight, 1)


def verify_scores(data: dict) -> list:
    """Check that computed CHI matches stored CHI for each cosmology."""
    axes = data["metadata"]["methodology"]["axes"]
    discrepancies = []
    for cosmo in data["cosmologies"]:
        computed = compute_chi(cosmo["scores"], axes)
        stored = cosmo["chi"]
        if abs(computed - stored) > 1.5:
            discrepancies.append({
                "id": cosmo["id"],
                "name": cosmo["name"],
                "stored": stored,
                "computed": computed,
                "diff": round(computed - stored, 1)
            })
    return discrepancies


def rank_cosmologies(data: dict) -> list:
    """Return cosmologies sorted by CHI descending."""
    axes = data["metadata"]["methodology"]["axes"]
    ranked = []
    for cosmo in data["cosmologies"]:
        chi = compute_chi(cosmo["scores"], axes)
        ranked.append({
            "rank": 0,
            "id": cosmo["id"],
            "name": cosmo["name"],
            "category": cosmo["category"],
            "chi": chi,
            "scores": cosmo["scores"],
            "summary": cosmo["summary"]
        })
    ranked.sort(key=lambda x: x["chi"], reverse=True)
    for i, item in enumerate(ranked):
        item["rank"] = i + 1
    return ranked


def format_markdown(ranked: list, axes: list) -> str:
    """Generate markdown table of rankings."""
    lines = ["# Cosmic Horror Index — Full Rankings\n"]
    lines.append("| Rank | System | Category | CHI | Summary |")
    lines.append("|------|--------|----------|-----|---------|")
    for r in ranked:
        lines.append(f"| {r['rank']} | {r['name']} | {r['category']} | {r['chi']} | {r['summary'][:80]}... |")
    
    lines.append("\n\n## Axis Breakdown\n")
    axis_ids = [a["id"] for a in axes]
    header = "| System | " + " | ".join(a["label"] for a in axes) + " | CHI |"
    sep = "|--------|" + "|".join("---" for _ in axes) + "|-----|"
    lines.append(header)
    lines.append(sep)
    for r in ranked:
        vals = " | ".join(str(r["scores"].get(aid, "")) for aid in axis_ids)
        lines.append(f"| {r['name']} | {vals} | {r['chi']} |")
    
    return "\n".join(lines)


def format_csv(ranked: list, axes: list) -> str:
    """Generate CSV output."""
    import io
    output = io.StringIO()
    axis_ids = [a["id"] for a in axes]
    fieldnames = ["rank", "id", "name", "category", "chi"] + axis_ids + ["summary"]
    writer = csv.DictWriter(output, fieldnames=fieldnames)
    writer.writeheader()
    for r in ranked:
        row = {
            "rank": r["rank"],
            "id": r["id"],
            "name": r["name"],
            "category": r["category"],
            "chi": r["chi"],
            "summary": r["summary"]
        }
        row.update(r["scores"])
        writer.writerow(row)
    return output.getvalue()


def generate_chart_data(ranked: list) -> dict:
    """Generate data structure for chart.js / d3 visualization."""
    return {
        "labels": [r["name"] for r in ranked],
        "datasets": [{
            "label": "Cosmic Horror Index",
            "data": [r["chi"] for r in ranked],
            "backgroundColor": [
                "#E24B4A" if r["chi"] >= 80 else
                "#BA7517" if r["chi"] >= 60 else
                "#888780" if r["chi"] >= 40 else
                "#1D9E75"
                for r in ranked
            ]
        }]
    }


def generate_annihilation_comparison(data: dict) -> str:
    """Generate markdown comparison of Lovecraft vs Annihilation."""
    comp = data["comparisons"]["annihilation"]
    lines = [f"# {comp['title']} — Structural Comparison with Lovecraft\n"]
    lines.append("| Dimension | Lovecraft | Annihilation | L-Score | A-Score |")
    lines.append("|-----------|-----------|-------------|---------|---------|")
    for dim in comp["dimensions"]:
        lines.append(
            f"| {dim['axis']} | {dim['lovecraft_note']} | "
            f"{dim['annihilation_note']} | {dim['lovecraft']} | {dim['annihilation']} |"
        )
    lines.append("\n## Paradigm Shifts\n")
    for shift in comp["paradigm_shifts"]:
        lines.append(f"- {shift}")
    return "\n".join(lines)


def main():
    parser = argparse.ArgumentParser(description="Cosmic Horror Index Calculator")
    parser.add_argument("--format", choices=["markdown", "csv", "json"], default="markdown")
    parser.add_argument("--verify", action="store_true", help="Verify stored CHI scores")
    parser.add_argument("--output", type=str, default=None, help="Output file path")
    args = parser.parse_args()

    data = load_data()
    axes = data["metadata"]["methodology"]["axes"]

    if args.verify:
        discrepancies = verify_scores(data)
        if discrepancies:
            print("DISCREPANCIES FOUND:")
            for d in discrepancies:
                print(f"  {d['name']}: stored={d['stored']}, computed={d['computed']}, diff={d['diff']}")
            sys.exit(1)
        else:
            print(f"All {len(data['cosmologies'])} CHI scores verified.")
            sys.exit(0)

    ranked = rank_cosmologies(data)

    if args.format == "markdown":
        result = format_markdown(ranked, axes)
    elif args.format == "csv":
        result = format_csv(ranked, axes)
    elif args.format == "json":
        result = json.dumps({
            "rankings": ranked,
            "chart_data": generate_chart_data(ranked),
        }, indent=2)

    OUTPUT_DIR.mkdir(exist_ok=True)

    if args.output:
        outpath = Path(args.output)
    else:
        ext = {"markdown": "md", "csv": "csv", "json": "json"}[args.format]
        outpath = OUTPUT_DIR / f"chi_rankings.{ext}"

    outpath.write_text(result)
    print(f"Output written to {outpath}")

    # Always generate the annihilation comparison
    ann_output = generate_annihilation_comparison(data)
    ann_path = OUTPUT_DIR / "annihilation_comparison.md"
    ann_path.write_text(ann_output)
    print(f"Annihilation comparison written to {ann_path}")


if __name__ == "__main__":
    main()
