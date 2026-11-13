"""Small, auditable dictionary masker for confidential chemical names."""

from dataclasses import dataclass
import re


@dataclass(frozen=True)
class MaskRule:
    term: str
    replacement: str


# Sample rules: replace these with the actual confidential names per plant.
MASK_RULES = (
    MaskRule("塩酸", "薬品A"),
    MaskRule("苛性ソーダ", "薬品B"),
    MaskRule("トルエン", "薬品C"),
)


def mask_confidential_terms(text: str) -> str:
    masked = text
    for rule in sorted(MASK_RULES, key=lambda item: len(item.term), reverse=True):
        masked = re.sub(re.escape(rule.term), rule.replacement, masked, flags=re.IGNORECASE)
    return masked
