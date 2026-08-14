import json
from dataclasses import dataclass
from pathlib import Path

from ..terminology.technical_normalizer import TerminologyEntry


@dataclass(frozen=True)
class MaskMapping:
    placeholder: str
    original: str
    category: str


@dataclass(frozen=True)
class MaskCategory:
    placeholder_prefix: str
    label: str


def load_mask_categories(path: Path) -> dict[str, MaskCategory]:
    if not path.exists():
        raise FileNotFoundError(f"masking policy not found: {path}")
    data = json.loads(path.read_text(encoding="utf-8"))
    categories = data.get("categories")
    if not isinstance(categories, dict):
        raise ValueError("masking policy must contain a categories object")
    return {
        key: MaskCategory(
            placeholder_prefix=value["placeholderPrefix"],
            label=value["label"],
        )
        for key, value in categories.items()
    }


class SemanticMasker:
    def __init__(self, entries: list[TerminologyEntry], categories: dict[str, MaskCategory]):
        self.entries = sorted(entries, key=lambda item: len(item.term), reverse=True)
        self.categories = categories
        self.by_original: dict[str, MaskMapping] = {}
        self.category_counts: dict[str, int] = {}
        for entry in entries:
            if entry.category not in categories:
                raise ValueError(f"unknown masking category for {entry.term}: {entry.category}")

    def mask(self, text: str) -> tuple[str, list[MaskMapping]]:
        masked = text
        used: list[MaskMapping] = []
        for entry in self.entries:
            if entry.term not in masked:
                continue
            mapping = self._mapping_for(entry)
            masked = masked.replace(entry.term, mapping.placeholder)
            used.append(mapping)
        return masked, used

    def _mapping_for(self, entry: TerminologyEntry) -> MaskMapping:
        existing = self.by_original.get(entry.term)
        if existing:
            return existing
        count = self.category_counts.get(entry.category, 0)
        category = self.categories[entry.category]
        placeholder = f"<{category.placeholder_prefix}_{suffix_for(count)}>"
        mapping = MaskMapping(placeholder=placeholder, original=entry.term, category=entry.category)
        self.by_original[entry.term] = mapping
        self.category_counts[entry.category] = count + 1
        return mapping


def suffix_for(index: int) -> str:
    chars: list[str] = []
    value = index
    while True:
        chars.append(chr(ord("A") + (value % 26)))
        value = value // 26 - 1
        if value < 0:
            return "".join(reversed(chars))
