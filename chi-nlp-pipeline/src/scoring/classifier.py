"""
Passage Classifier — Uses Claude to score individual passages against CHI axes.
Each passage gets: relevance, valence, confidence, and justification.
"""

import json
import logging
import time
import os

logger = logging.getLogger("chi-pipeline.classifier")


class PassageClassifier:
    def __init__(self, model: str, max_tokens: int = 500, dry_run: bool = False):
        self.model = model
        self.max_tokens = max_tokens
        self.dry_run = dry_run
        self.client = None
        self.call_count = 0
        self.total_input_tokens = 0
        self.total_output_tokens = 0

    def _init_client(self):
        if self.client is None:
            from anthropic import Anthropic
            self.client = Anthropic()  # Uses ANTHROPIC_API_KEY env var

    def classify(self, passage: dict, axis_def: dict, tradition: str) -> dict:
        """
        Classify a single passage against a single axis.
        
        Returns: {relevance, valence, confidence, justification} or None on failure.
        """
        if self.dry_run:
            return {
                "relevance": 0.5,
                "valence": 0.0,
                "confidence": 0.5,
                "justification": "[DRY RUN]"
            }

        self._init_client()

        from prompts.classification_prompts import (
            SYSTEM_PROMPT, CLASSIFICATION_PROMPT, AXIS_DESCRIPTIONS
        )

        axis_id = axis_def["id"]
        axis_desc = AXIS_DESCRIPTIONS.get(axis_id, {"high": "", "low": ""})

        prompt = CLASSIFICATION_PROMPT.format(
            axis_label=axis_def["label"],
            axis_description=axis_def["description"],
            high_description=axis_desc["high"],
            low_description=axis_desc["low"],
            tradition=tradition,
            source_text=passage.get("source", ""),
            reference=passage.get("reference", ""),
            passage_text=passage["text"][:1500]  # Cap passage length
        )

        try:
            response = self.client.messages.create(
                model=self.model,
                max_tokens=self.max_tokens,
                system=SYSTEM_PROMPT,
                messages=[{"role": "user", "content": prompt}]
            )

            self.call_count += 1
            self.total_input_tokens += response.usage.input_tokens
            self.total_output_tokens += response.usage.output_tokens

            # Parse JSON response
            text = response.content[0].text.strip()
            # Strip markdown fences if present
            text = text.replace("```json", "").replace("```", "").strip()

            result = json.loads(text)

            # Validate ranges
            result["relevance"] = max(0, min(1, float(result.get("relevance", 0))))
            result["valence"] = max(-1, min(1, float(result.get("valence", 0))))
            result["confidence"] = max(0, min(1, float(result.get("confidence", 0))))
            result["justification"] = str(result.get("justification", ""))

            # Rate limiting: small delay between calls
            time.sleep(0.2)

            return result

        except json.JSONDecodeError as e:
            logger.warning(f"  JSON parse error: {e}")
            return None
        except Exception as e:
            logger.warning(f"  Classification error: {e}")
            # Back off on rate limits
            if "rate" in str(e).lower():
                logger.info("  Rate limited, waiting 10s...")
                time.sleep(10)
            return None

    def get_usage_stats(self) -> dict:
        return {
            "api_calls": self.call_count,
            "total_input_tokens": self.total_input_tokens,
            "total_output_tokens": self.total_output_tokens,
            "estimated_cost_usd": round(
                (self.total_input_tokens * 3 / 1_000_000) +
                (self.total_output_tokens * 15 / 1_000_000), 4
            )
        }
