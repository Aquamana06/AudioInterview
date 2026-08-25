import os

from fastapi import FastAPI, File, Form, HTTPException, UploadFile
from fastapi.middleware.cors import CORSMiddleware

from .transcription.local_whisper import LocalWhisper


whisper = LocalWhisper(
    os.getenv("FASTER_WHISPER_MODEL", "large-v3"),
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
    raw_text = whisper.transcribe(audio_bytes, audio.filename or "audio.webm", language)
    return {"rawText": raw_text}


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(
        "local_backend.main:app",
        host=os.getenv("AUDIOINTERVIEW_HOST", "127.0.0.1"),
        port=int(os.getenv("AUDIOINTERVIEW_PORT", "8000")),
    )
