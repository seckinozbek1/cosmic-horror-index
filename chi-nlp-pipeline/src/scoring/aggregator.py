"""
Score Aggregator — Combines passage-level classifications into axis scores.
Produces: score (0-100), confidence interval, and ranked evidence list.
"""

import logging
import numpy as np

logger = logging.getLogger("chi-pipeline.aggregator")


class ScoreAggregator:
    def __init__(self, min_relevance: float = 0.3, bootstrap_n: int = 1000):
        self.min_relevance = min_relevance
        self.bootstrap_n = bootstrap_n

    def aggregate(self, classifications: list, axis_id: str) -> dict:
        """
        Aggregate passage-level classifications into a single axis score.
        
        Method:
        1. Filter by minimum relevance threshold
        2. Weight each passage's valence by (relevance × confidence)
        3. Compute weighted mean → scale to 0-100
        4. Bootstrap for confidence interval
        5. Rank evidence passages by contribution
        """
        # Filter
        valid = [
            c for c in classifications
            if c.get("relevance", 0) >= self.min_relevance
        ]

        if not valid:
            return {
                "score": 50.0,  # Default to neutral if no evidence
                "ci_low": 0.0,
                "ci_high": 100.0,
                "n_passages": 0,
                "evidence": [],
                "note": "No passages met relevance threshold"
            }

        # Compute weighted valence
        valences = np.array([c["valence"] for c in valid])
        weights = np.array([
            c["relevance"] * c["confidence"] for c in valid
        ])

        # Normalize weights
        if weights.sum() > 0:
            weights_norm = weights / weights.sum()
        else:
            weights_norm = np.ones_like(weights) / len(weights)

        # Weighted mean valence: [-1, 1]
        mean_valence = np.average(valences, weights=weights_norm)

        # Scale to [0, 100]: -1 → 0, 0 → 50, +1 → 100
        score = (mean_valence + 1) * 50

        # Bootstrap confidence interval
        ci_low, ci_high = self._bootstrap_ci(valences, weights_norm)

        # Rank evidence by contribution (weight × |valence|)
        evidence = []
        for i, c in enumerate(valid):
            evidence.append({
                "text": c.get("text", "")[:300],
                "source": c.get("source", ""),
                "reference": c.get("reference", ""),
                "translation": c.get("translation", ""),
                "relevance": round(c["relevance"], 3),
                "valence": round(c["valence"], 3),
                "confidence": round(c["confidence"], 3),
                "justification": c.get("justification", ""),
                "contribution": round(float(weights_norm[i] * abs(valences[i])), 4)
            })

        evidence.sort(key=lambda x: x["contribution"], reverse=True)

        return {
            "score": round(float(score), 1),
            "ci_low": round(float(ci_low), 1),
            "ci_high": round(float(ci_high), 1),
            "n_passages": len(valid),
            "mean_valence": round(float(mean_valence), 3),
            "evidence": evidence[:10]  # Top 10 evidence passages
        }

    def _bootstrap_ci(self, valences: np.ndarray, weights: np.ndarray,
                       alpha: float = 0.05) -> tuple:
        """Bootstrap confidence interval for the weighted mean valence, scaled to 0-100."""
        n = len(valences)
        if n < 3:
            return (0.0, 100.0)

        rng = np.random.default_rng(42)
        boot_means = []

        for _ in range(self.bootstrap_n):
            idx = rng.choice(n, size=n, replace=True)
            boot_v = valences[idx]
            boot_w = weights[idx]
            if boot_w.sum() > 0:
                boot_w = boot_w / boot_w.sum()
            boot_mean = np.average(boot_v, weights=boot_w)
            boot_means.append(boot_mean)

        boot_means = np.array(boot_means)
        ci_low = np.percentile(boot_means, alpha / 2 * 100)
        ci_high = np.percentile(boot_means, (1 - alpha / 2) * 100)

        # Scale to 0-100
        return ((ci_low + 1) * 50, (ci_high + 1) * 50)
