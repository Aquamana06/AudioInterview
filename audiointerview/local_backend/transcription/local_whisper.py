from pathlib import Path
from tempfile import NamedTemporaryFile

import ctranslate2
from faster_whisper import WhisperModel


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
        with NamedTemporaryFile(suffix=suffix) as temporary:
            temporary.write(audio)
            temporary.flush()
            segments, _ = self.model.transcribe(
                temporary.name,
                language=language or None,
                vad_filter=True,
            )
            return "".join(segment.text for segment in segments).strip()
