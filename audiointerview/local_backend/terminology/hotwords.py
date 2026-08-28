"""Chemical-plant vocabulary supplied to Whisper as transcription context.

Keep this list short and domain-specific. It is a hint to the recognizer, not
an instruction to blindly rewrite every occurrence.
"""

DOMAIN_TERMS = ("PPE", "鹸化", "重合")

# The three examples are deliberately explicit so site administrators can
# replace them with the vocabulary of the plant being interviewed.
TRANSCRIPTION_CORRECTIONS = (
    "ぴーぴーいー / PPE",
    "けん化 / 鹸化",
    "じゅうごう / 重合",
)

TRANSCRIPTION_PROMPT = (
    "化学プラントの現場インタビューです。専門用語は次の表記を優先してください: "
    + "、".join(DOMAIN_TERMS)
    + "。誤認識しやすい読み方: "
    + "、".join(TRANSCRIPTION_CORRECTIONS)
    + "。数字に置き換えず、文脈に合う専門用語として認識してください。"
)
