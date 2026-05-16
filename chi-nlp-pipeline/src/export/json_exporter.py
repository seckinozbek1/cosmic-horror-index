"""
JSON Exporter — Generates the grounded CHI dataset with citation keys.
"""

import json
import logging
from pathlib import Path

logger = logging.getLogger("chi-pipeline.json-export")


class JSONExporter:
    def __init__(self, config: dict):
        self.config = config
        self.axes = config["axes"]
        self.weight_map = {a["id"]: a["weight"] for a in self.axes}

    def compute_chi(self, axis_scores: dict) -> float:
        """Compute CHI from axis scores using defined weights."""
        total_weight = 0
        weighted_sum = 0
        for axis_id, data in axis_scores.items():
            score = data.get("score", 50)
            if score is None:
                score = 50
            w = self.weight_map.get(axis_id, 1)
            weighted_sum += score * w
            total_weight += w
        return round(weighted_sum / total_weight, 1) if total_weight > 0 else 50.0

    def export(self, results: dict, output_path: Path):
        """Export full grounded dataset."""
        dataset = {
            "metadata": {
                "title": "Cosmic Horror Index — NLP-Grounded Dataset",
                "version": "2.0.0",
                "methodology": "Automated scoring via semantic retrieval + LLM classification of sacred text corpora",
                "axes": self.axes,
                "chi_formula": "weighted_mean(axes) with indifference/incomprehensibility/human_insignificance at 2x"
            },
            "cosmologies": []
        }

        for tradition, axis_data in results.items():
            # Compute CHI
            chi = self.compute_chi(axis_data)

            # Build axis scores with citation keys
            scores = {}
            for axis_id, data in axis_data.items():
                evidence_refs = []
                for i, ev in enumerate(data.get("evidence", [])):
                    citation_key = f"{tradition}_{axis_id}_{i}"
                    evidence_refs.append({
                        "citation_key": citation_key,
                        "source": ev.get("source", ""),
                        "reference": ev.get("reference", ""),
                        "relevance": ev.get("relevance", 0),
                        "valence": ev.get("valence", 0),
                        "confidence": ev.get("confidence", 0),
                        "justification": ev.get("justification", "")
                    })

                scores[axis_id] = {
                    "score": data.get("score", 50),
                    "ci_low": data.get("ci_low", 0),
                    "ci_high": data.get("ci_high", 100),
                    "n_passages": data.get("n_passages", 0),
                    "evidence": evidence_refs
                }

            dataset["cosmologies"].append({
                "id": tradition,
                "chi": chi,
                "scores": scores
            })

        # Sort by CHI descending
        dataset["cosmologies"].sort(key=lambda x: x["chi"], reverse=True)

        output_path.write_text(json.dumps(dataset, indent=2, ensure_ascii=False))
        logger.info(f"JSON dataset exported: {output_path}")
