import json
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class TerminologyEntry:
    term: str
    category: str
    reading: str
    aliases: tuple[str, ...]
    common_asr_errors: tuple[str, ...]


class TechnicalNormalizer:
    def __init__(self, entries: list[TerminologyEntry]):
        self.entries = entries
        replacements: list[tuple[str, str]] = []
        for entry in entries:
            candidates = [entry.term, *entry.aliases, *entry.common_asr_errors]
            replacements.extend((candidate, entry.term) for candidate in candidates if candidate)
        self.replacements = sorted(replacements, key=lambda item: len(item[0]), reverse=True)

    @classmethod
    def from_file(cls, path: Path) -> "TechnicalNormalizer":
        if not path.exists():
            raise FileNotFoundError(f"terminology dictionary not found: {path}")
        data = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(data, list):
            raise ValueError("terminology dictionary must be a JSON array")
        entries = [
            TerminologyEntry(
                term=item["term"],
                category=item["category"],
                reading=item.get("reading", ""),
                aliases=tuple(item.get("aliases", [])),
                common_asr_errors=tuple(item.get("common_asr_errors", [])),
            )
            for item in data
        ]
        return cls(entries)

    def normalize(self, text: str) -> str:
        normalized = text
        for source, target in self.replacements:
            normalized = normalized.replace(source, target)
        return normalized
