"""Conservative dictionary corrections for common speech-recognition errors."""

import re

# Only corrections observed in this domain should be added here. Do not add
# broad Japanese homophones without a plant-specific confirmation.
TECHNICAL_CORRECTIONS = (
    # Confirmed tower homophone, only with an equipment attribute immediately
    # after it. Preserve standalone 15, grades, temperatures, and building IDs.
    (re.compile(
        r"(?<![0-9０-９一二三四五六七八九十百千第.．−〜～-])(?:15|１５|十五)等"
        r"(?=の(?:温度|圧力|液面|液位|流量|入口|出口)|内の(?:温度|圧力|液面|液位))"
    ), "重合塔"),
    (re.compile(r"(?<![A-Za-z])(?:ぴーぴーいー|ＰＰＥ|pp[eE]|P P E)(?![A-Za-z])", re.I), "PPE"),
    (re.compile(r"(?:けんか|ケンカ|けん化)(?=剤|反応|工程|処理|価|$|[、。])"), "鹸化"),
    (re.compile(r"(?:じゅうごう|ジュウゴウ|重合う)(?=反応|度|工程|塔|槽|物|樹脂|$|[、。])"), "重合"),
)


def normalize_technical_terms(text: str) -> str:
    """Apply only high-confidence, context-aware technical corrections."""
    normalized = text
    for pattern, replacement in TECHNICAL_CORRECTIONS:
        normalized = pattern.sub(replacement, normalized)
    return normalized
