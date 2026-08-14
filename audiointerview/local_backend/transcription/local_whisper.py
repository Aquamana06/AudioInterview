from pathlib import Path
from tempfile import NamedTemporaryFile

from faster_whisper import WhisperModel


class LocalWhisper:
    def __init__(self, model_name: str = "large-v3", device: str = "auto", compute_type: str = "default"):
        self.model = WhisperModel(model_name, device=device, compute_type=compute_type)

    def transcribe(self, audio_bytes: bytes, filename: str, hotwords: list[str], language: str | None = "ja") -> str:
        suffix = Path(filename).suffix or ".webm"
        with NamedTemporaryFile(suffix=suffix) as tmp:
            tmp.write(audio_bytes)
            tmp.flush()
            segments, _info = self.model.transcribe(
                tmp.name,
                language=language,
                vad_filter=True,
                hotwords=" ".join(hotwords),
                condition_on_previous_text=False,
            )
            accepted: list[str] = []
            for segment in segments:
                if segment.no_speech_prob >= 0.6:
                    continue
                if segment.avg_logprob <= -1.0:
                    continue
                accepted.append(segment.text)

            text = "".join(accepted).strip()
            if is_hotword_hallucination(text, hotwords):
                return ""
            return text


def is_hotword_hallucination(text: str, hotwords: list[str]) -> bool:
    compact = normalize_for_comparison(text)
    if not compact:
        return False
    remaining = compact
    matched = 0
    for hotword in sorted(hotwords, key=len, reverse=True):
        normalized_hotword = normalize_for_comparison(hotword)
        if normalized_hotword and normalized_hotword in remaining:
            matched += 1
            remaining = remaining.replace(normalized_hotword, "")
    # A real answer may legitimately be one technical term. Multiple prompted
    # terms with almost no other content is the characteristic silence hallucination.
    return matched >= 2 and len(remaining) <= 4


def normalize_for_comparison(text: str) -> str:
    return "".join(character.lower() for character in text if character.isalnum())
