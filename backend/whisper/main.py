import asyncio

from fastapi import FastAPI, File, Form, HTTPException, UploadFile
from fastapi.middleware.cors import CORSMiddleware

from api.settings import setting
from config import load_config

from .transcription.local_whisper import LocalWhisper
from .privacy.dictionary_masker import mask_confidential_terms
from .terminology import normalize_technical_terms


CONFIG = load_config("whisper")


whisper = LocalWhisper(
    setting("FASTER_WHISPER_MODEL", CONFIG["model"]),
    setting("FASTER_WHISPER_DEVICE", CONFIG["device"]),
    setting("FASTER_WHISPER_COMPUTE_TYPE", CONFIG["compute_type"]),
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
        "whisper.main:app",
        host=setting("AUDIOINTERVIEW_HOST", load_config("api")["server"]["host"]),
        port=int(setting("AUDIOINTERVIEW_PORT", str(load_config("api")["server"]["port"]))),
    )
