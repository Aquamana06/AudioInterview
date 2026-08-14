import os
import re
from pathlib import Path

from fastapi import FastAPI, File, Form, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

from .privacy.semantic_masker import SemanticMasker, load_mask_categories
from .terminology.hotwords import load_hotwords
from .terminology.technical_normalizer import TechnicalNormalizer
from .transcription.local_whisper import LocalWhisper

BASE_DIR = Path(__file__).resolve().parent
CONFIG_DIR = Path(os.environ.get("AUDIOINTERVIEW_CONFIG_DIR", BASE_DIR / "config"))

normalizer = TechnicalNormalizer.from_file(CONFIG_DIR / "terminology.json")
hotwords = load_hotwords(CONFIG_DIR / "hotwords.json")
mask_categories = load_mask_categories(CONFIG_DIR / "masking_policy.json")
masker = SemanticMasker(normalizer.entries, mask_categories)
whisper = LocalWhisper(
    model_name=os.environ.get("FASTER_WHISPER_MODEL", "large-v3"),
    device=os.environ.get("FASTER_WHISPER_DEVICE", "cuda"),
    compute_type=os.environ.get("FASTER_WHISPER_COMPUTE_TYPE", "float16"),
)

app = FastAPI(title="AudioInterview Local Backend")
configured_origins = os.environ.get("AUDIOINTERVIEW_CORS_ORIGINS")
app.add_middleware(
    CORSMiddleware,
    allow_origins=configured_origins.split(",") if configured_origins else [],
    allow_origin_regex=None if configured_origins else r"https?://(localhost|127\.0\.0\.1|192\.168\.\d+\.\d+|100\.64\.\d+\.\d+)(:\d+)?",
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
)


class TextInput(BaseModel):
    text: str


@app.get("/health")
def health():
    return {
        "status": "ok",
        "transcription": "faster-whisper",
        "model": os.environ.get("FASTER_WHISPER_MODEL", "large-v3"),
        "device": os.environ.get("FASTER_WHISPER_DEVICE", "cuda"),
        "semanticMasking": True,
    }


@app.post("/mask-text")
def mask_text(body: TextInput):
    normalized_text = normalizer.normalize(body.text)
    masked_text, _mappings = masker.mask(normalized_text)
    return {
        "normalizedText": normalized_text,
        "maskedText": masked_text,
    }

@app.post("/transcribe")
async def transcribe(audio: UploadFile = File(...), language: str | None = Form("ja")):
    audio_bytes = await audio.read()
    raw_text = whisper.transcribe(audio_bytes, audio.filename or "audio.webm", hotwords, language)
    cleaned_text = strip_voice_commands(raw_text)
    normalized_text = normalizer.normalize(cleaned_text)
    masked_text, _mappings = masker.mask(normalized_text)
    return {
        "rawText": cleaned_text,
        "normalizedText": normalized_text,
        "maskedText": masked_text,
    }


def strip_voice_commands(text: str) -> str:
    cleaned = re.sub(
        r"^\s*(?:hey\s*whisper|ヘイ[、,\s]*(?:ウィスパー|ウイスパー))[\s、,。.!！?？]*",
        "",
        text,
        flags=re.IGNORECASE,
    )
    cleaned = re.sub(
        r"[\s、,。.!！?？]*(?:over|オーバー)[\s、,。.!！?？]*$",
        "",
        cleaned,
        flags=re.IGNORECASE,
    )
    return cleaned.strip()

def run():
    import uvicorn

    uvicorn.run(
        "local_backend.main:app",
        host=os.environ.get("AUDIOINTERVIEW_HOST", "127.0.0.1"),
        port=int(os.environ.get("AUDIOINTERVIEW_PORT", "8000")),
        reload=os.environ.get("AUDIOINTERVIEW_RELOAD", "0") == "1",
    )
