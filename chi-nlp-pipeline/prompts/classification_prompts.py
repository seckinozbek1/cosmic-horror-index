SYSTEM_PROMPT = """You are a comparative religion scholar and textual analyst. Your task is to evaluate passages from sacred and philosophical texts against specific cosmological dimensions.

For each passage, you will assess:
1. RELEVANCE: How directly does this passage address the given axis? (0.0 to 1.0)
2. VALENCE: Does this passage indicate a HIGH or LOW score on this axis? (-1.0 to +1.0, where +1.0 = maximum alignment with high score description, -1.0 = maximum alignment with low score description)
3. CONFIDENCE: How confident are you in this assessment? (0.0 to 1.0)
4. JUSTIFICATION: One sentence explaining your reasoning.

Be precise and text-grounded. Do not import external theological interpretations — score based only on what the passage itself says. If the passage is ambiguous, reflect that in a lower confidence score.

Respond ONLY in this exact JSON format, nothing else:
{"relevance": 0.0, "valence": 0.0, "confidence": 0.0, "justification": "..."}"""


CLASSIFICATION_PROMPT = """Evaluate this passage against the following axis:

AXIS: {axis_label}
AXIS DESCRIPTION: {axis_description}
HIGH SCORE MEANS: {high_description}
LOW SCORE MEANS: {low_description}

TRADITION: {tradition}
SOURCE TEXT: {source_text}
REFERENCE: {reference}

PASSAGE:
\"\"\"
{passage_text}
\"\"\"

Score this passage on relevance (0-1), valence (-1 to +1 where positive = supports HIGH score), and confidence (0-1). Respond only in JSON."""


# High/low descriptions per axis (used in the classification prompt)
AXIS_DESCRIPTIONS = {
    "omniscience": {
        "high": "The ultimate reality or divine entity knows everything — all events, thoughts, past, present, future. Total informational awareness.",
        "low": "The divine has limited knowledge, can be surprised or deceived, or there is no knowing entity."
    },
    "omnipotence": {
        "high": "The ultimate reality has unlimited power. Nothing can resist it. It creates and destroys without constraint.",
        "low": "Divine power is limited, can be challenged, or is distributed among many beings."
    },
    "self_sufficiency": {
        "high": "The divine needs nothing from creation. Worship, prayer, and human existence are unnecessary to it.",
        "low": "The divine requires offerings, worship, or human action to sustain itself or the cosmic order."
    },
    "indifference": {
        "high": "The ultimate reality does not care about human welfare, suffering, or flourishing. Humans are irrelevant to cosmic operations.",
        "low": "The divine actively loves, responds to, and cares about human beings and their welfare."
    },
    "incomprehensibility": {
        "high": "The divine nature is beyond human understanding. Language, thought, and reason cannot grasp it. Attempting to know it may overwhelm the mind.",
        "low": "The divine can be known, understood, or communicated with through scripture, reason, or direct experience."
    },
    "human_insignificance": {
        "high": "Humans are cosmically insignificant. Individual lives have no ultimate meaning. The cosmos is indifferent to human civilization.",
        "low": "Humans have a special role, cosmic significance, or divine purpose. Each human life matters."
    },
    "cyclical_destruction": {
        "high": "The cosmos destroys itself and rebuilds in cycles. Worlds end and are remade. Destruction is a recurring, structural feature.",
        "low": "Creation happened once. History is linear. The world ends once (or not at all) rather than cycling."
    },
    "awe_madness": {
        "high": "Encountering the divine or ultimate truth causes terror, overwhelm, madness, or ego-dissolution. The experience is unbearable.",
        "low": "Encountering the divine brings peace, comfort, joy. The experience is positive and integrating."
    },
    "creation_without_consent": {
        "high": "Beings are created or come into existence without choosing to. Existence is imposed. No one asked to be born.",
        "low": "Souls choose to incarnate, or creation is collaborative between divine and created beings."
    },
    "moral_neutrality": {
        "high": "The ultimate reality is beyond good and evil. The cosmos has no inherent moral order. Natural forces are amoral.",
        "low": "The divine is essentially good, opposes evil, and the cosmos has an inherent moral structure."
    }
}
"""
