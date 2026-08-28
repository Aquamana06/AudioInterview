import asyncio
import os

from fastapi import FastAPI, File, Form, HTTPException, UploadFile
from fastapi.middleware.cors import CORSMiddleware

from .transcription.local_whisper import LocalWhisper
from .privacy.dictionary_masker import mask_confidential_terms
from .terminology import normalize_technical_terms


whisper = LocalWhisper(
    os.getenv("FASTER_WHISPER_MODEL", "small"),
    os.getenv("FASTER_WHISPER_DEVICE", "auto"),
    os.getenv("FASTER_WHISPER_COMPUTE_TYPE", "auto"),
)

app = FastAPI(title="AudioInterview Local Whisper Backend")
app.add_middleware(
    CORSMiddleware,
    allow_origin_regex=r"https?://(localhost|127\.0\.0\.1|192\.168\.\d+\.\d+|100\.64\.\d+\.\d+)(:\d+)?",
    allow_credentials=True,
    allow_methods=["GET", "POST", "OPTIONS"],
    allow_headers=["*"],
)


@app.get("/health")
def health() -> dict[str, str]:
    return {
        "status": "ok",
        "transcription": "faster-whisper",
        "model": whisper.model_name,
        "device": whisper.device,
        "computeType": whisper.compute_type,
    }


@app.post("/transcribe")
async def transcribe(
    audio: UploadFile = File(...),
    language: str = Form("ja"),
) -> dict[str, str]:
    audio_bytes = await audio.read()
    if not audio_bytes:
        raise HTTPException(status_code=400, detail="Audio file is empty")
    # faster-whisper is synchronous and can take a while on CPU, so keep it
    # out of FastAPI's event loop while the model loads or runs inference.
    raw_text = await asyncio.to_thread(
        whisper.transcribe, audio_bytes, audio.filename or "audio.webm", language
    )
    normalized_text = normalize_technical_terms(raw_text)
    return {
        "rawText": raw_text,
        "normalizedText": normalized_text,
        "maskedText": mask_confidential_terms(normalized_text),
    }


@app.post("/mask-text")
async def mask_text(payload: dict[str, str]) -> dict[str, str]:
    text = payload.get("text", "").strip()
    if not text:
        raise HTTPException(status_code=400, detail="text is required")
    normalized_text = normalize_technical_terms(text)
    return {
        "normalizedText": normalized_text,
        "maskedText": mask_confidential_terms(normalized_text),
    }


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(
        "local_backend.main:app",
        host=os.getenv("AUDIOINTERVIEW_HOST", "127.0.0.1"),
        port=int(os.getenv("AUDIOINTERVIEW_PORT", "8000")),
    )
