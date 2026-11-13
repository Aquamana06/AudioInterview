from pathlib import Path
from tempfile import NamedTemporaryFile
from threading import Lock

import ctranslate2
from faster_whisper import WhisperModel

from config import load_config

from ..terminology import TRANSCRIPTION_PROMPT


class LocalWhisper:
    def __init__(self, model_name: str, device: str = "auto", compute_type: str = "auto") -> None:
        if device == "auto":
            device = "cuda" if ctranslate2.get_cuda_device_count() > 0 else "cpu"
        if compute_type == "auto":
            compute_type = "float16" if device == "cuda" else "int8"
        self.model_name = model_name
        self.device = device
        self.compute_type = compute_type
        self._model: WhisperModel | None = None
        self._inference_lock = Lock()
        self._warmed_up = False

    @property
    def ready(self) -> bool:
        return self._warmed_up

    def warmup(self) -> None:
        """Exercise CUDA inference with silence; keep the same model for requests."""
        import numpy as np

        with self._inference_lock:
            if self._warmed_up:
                return
            segments, _ = self.model.transcribe(
                np.zeros(16000, dtype=np.float32), language="ja",
                vad_filter=False, initial_prompt=TRANSCRIPTION_PROMPT,
            )
            # faster-whisper executes inference while consuming the generator.
            for _ in segments:
                pass
            if load_config("whisper")["transcription"]["vad_filter"]:
                # Also initialize the VAD session used by ordinary requests.
                from faster_whisper.vad import get_speech_timestamps

                get_speech_timestamps(np.zeros(16000, dtype=np.float32))
            self._warmed_up = True

    @property
    def model(self) -> WhisperModel:
        if self._model is None:
            self._model = WhisperModel(
                self.model_name,
                device=self.device,
                compute_type=self.compute_type,
            )
        return self._model

    def transcribe(self, audio: bytes, filename: str, language: str | None = None) -> str:
        suffix = Path(filename).suffix or ".webm"
        with self._inference_lock, NamedTemporaryFile(suffix=suffix) as temporary:
            temporary.write(audio)
            temporary.flush()
            segments, _ = self.model.transcribe(
                temporary.name,
                language=language or None,
                vad_filter=load_config("whisper")["transcription"]["vad_filter"],
                initial_prompt=TRANSCRIPTION_PROMPT,
            )
            return "".join(segment.text for segment in segments).strip()
