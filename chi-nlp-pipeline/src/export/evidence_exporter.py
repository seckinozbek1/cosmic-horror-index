"""
Evidence Exporter — Generates a markdown document with full passages and context.
Every CHI score is traceable to specific textual evidence.
"""

import json
import logging
from pathlib import Path

logger = logging.getLogger("chi-pipeline.evidence-export")


class EvidenceExporter:
    def export(self, results: dict, output_path: Path):
        """Generate evidence document with full passages."""
        lines = [
            "# Cosmic Horror Index — Textual Evidence Document\n",
            "Every axis score is grounded in specific passages from canonical texts.",
            "This document provides the full citation chain for audit and review.\n",
            "---\n"
        ]

        for tradition, axis_data in sorted(results.items()):
            lines.append(f"\n## {tradition.replace('_', ' ').title()}\n")

            for axis_id, data in sorted(axis_data.items()):
                score = data.get("score", "N/A")
                ci_low = data.get("ci_low", "N/A")
                ci_high = data.get("ci_high", "N/A")
                n = data.get("n_passages", 0)

                lines.append(f"\n### {axis_id.replace('_', ' ').title()}")
                lines.append(f"**Score: {score}** (CI: [{ci_low}, {ci_high}], n={n} passages)\n")

                evidence = data.get("evidence", [])
                if not evidence:
                    lines.append("*No evidence passages met relevance threshold.*\n")
                    continue

                for i, ev in enumerate(evidence):
                    citation_key = f"{tradition}_{axis_id}_{i}"
                    lines.append(f"#### [{citation_key}]")
                    lines.append(f"- **Source:** {ev.get('source', 'unknown')}")
                    lines.append(f"- **Reference:** {ev.get('reference', 'N/A')}")
                    lines.append(f"- **Translation:** {ev.get('translation', 'N/A')}")
                    lines.append(f"- **Relevance:** {ev.get('relevance', 0):.2f} | "
                                f"**Valence:** {ev.get('valence', 0):+.2f} | "
                                f"**Confidence:** {ev.get('confidence', 0):.2f}")
                    lines.append(f"- **Justification:** {ev.get('justification', '')}")
                    lines.append(f"\n> {ev.get('text', '[no text]')}\n")

            lines.append("---\n")

        output_path.write_text("\n".join(lines))
        logger.info(f"Evidence document exported: {output_path}")
