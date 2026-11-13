from whisper.privacy.dictionary_masker import mask_confidential_terms
from whisper.terminology.technical_normalizer import normalize_technical_terms


def prepare_text(text: str) -> dict[str, str]:
    normalized = normalize_technical_terms(text)
    return {"normalizedText": normalized, "maskedText": mask_confidential_terms(normalized)}
