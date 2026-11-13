"""Conservative dictionary corrections for common speech-recognition errors."""

import re

# Only corrections observed in this domain should be added here. Do not add
# broad Japanese homophones without a plant-specific confirmation.
TECHNICAL_CORRECTIONS = (
    (re.compile(r"(?<![A-Za-z])(?:ぴーぴーいー|ＰＰＥ|pp[eE]|P P E)(?![A-Za-z])", re.I), "PPE"),
    (re.compile(r"(?:けんか|ケンカ|けん化)(?=剤|反応|工程|処理|価|$|[、。])"), "鹸化"),
    (re.compile(r"(?:じゅうごう|ジュウゴウ|重合う|15)(?=反応|度|工程|槽|物|樹脂|$|[、。])"), "重合"),
)


def normalize_technical_terms(text: str) -> str:
    """Apply only high-confidence, context-aware technical corrections."""
    normalized = text
    for pattern, replacement in TECHNICAL_CORRECTIONS:
        normalized = pattern.sub(replacement, normalized)
    return normalized
