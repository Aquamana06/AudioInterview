"""Detect spoken turn-ending commands while preserving the original answer."""

import re
import unicodedata


_JAPANESE_OVER = re.compile(r"オ[ーオ]?バー*")
_HIRAGANA_TO_KATAKANA = str.maketrans({chr(code): chr(code + 0x60) for code in range(0x3041, 0x3097)})


def _command_start(text: str) -> int | None:
    end = len(text)
    while end and (text[end - 1].isspace() or unicodedata.category(text[end - 1]).startswith("P")):
        end -= 1
    # Normalize only candidate suffixes so half-width kana and full-width
    # English work without changing offsets into the original transcript.
    for start in range(max(0, end - 16), end):
        candidate = unicodedata.normalize("NFKC", text[start:end]).translate(_HIRAGANA_TO_KATAKANA)
        previous = unicodedata.normalize("NFKC", text[start - 1:start])
        if candidate.casefold() == "over":
            if not previous or not (previous[-1].isalnum() or previous[-1] == "_"):
                return start
        elif _JAPANESE_OVER.fullmatch(candidate):
            # Avoid word endings such as タイムオーバー and あおば. Short
            # variants おば/オバ need a clearer boundary than オーバー.
            if previous and ("ァ" <= previous[-1] <= "ヺ" or previous[-1] == "ー"):
                continue
            if candidate == "オバ" and previous and "ぁ" <= previous[-1] <= "ゖ":
                continue
            return start
    return None


def split_turn_command(text: str) -> tuple[str, bool]:
    """Strip terminal commands, including repetitions, and report detection."""
    answer = text
    detected = False
    while (start := _command_start(answer)) is not None:
        detected = True
        answer = answer[:start].rstrip()
        while answer and (unicodedata.category(answer[-1]) in {"Ps", "Pi"} or answer[-1] in "\"'"):
            answer = answer[:-1].rstrip()
    return answer, detected
