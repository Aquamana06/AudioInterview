#!/usr/bin/env python3
"""Transcribe local MP4 files with Hugging Face openai/whisper-small.

Usage:
  .venv/bin/python scripts/transcribe_local.py data/interview.mp4
  .venv/bin/python scripts/transcribe_local.py --all
"""

from __future__ import annotations

import argparse
import subprocess
import sys
from pathlib import Path

import numpy as np
from huggingface_hub import snapshot_download
from transformers import pipeline


ROOT = Path(__file__).resolve().parents[1]
MODEL_DIR = ROOT / "models" / "whisper-small"
DATA_DIR = ROOT / "data"
PROMPT = "化学プラントの現場インタビュー。専門用語: 重合、鹸化、加水分解、触媒、モノマー、ポリマー。読み方: じゅうごう、けんか。"


def decode_mp4(path: Path) -> np.ndarray:
    """Decode any ffmpeg-supported audio track to 16 kHz mono float32 PCM."""
    command = [
        "ffmpeg", "-nostdin", "-v", "error", "-i", str(path),
        "-vn", "-ac", "1", "-ar", "16000", "-f", "f32le", "pipe:1",
    ]
    try:
        result = subprocess.run(command, check=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    except FileNotFoundError as error:
        raise RuntimeError("ffmpegが必要です。Ubuntuなら `sudo apt install ffmpeg` で導入してください。") from error
    except subprocess.CalledProcessError as error:
        detail = error.stderr.decode("utf-8", errors="replace").strip()
        raise RuntimeError(f"音声を読み込めませんでした: {detail}") from error
    audio = np.frombuffer(result.stdout, dtype=np.float32)
    if audio.size == 0:
        raise RuntimeError(f"音声トラックが空です: {path}")
    return audio


def get_pipeline():
    MODEL_DIR.mkdir(parents=True, exist_ok=True)
    marker = MODEL_DIR / "config.json"
    if not marker.exists():
        print(f"Hugging Faceからモデルをダウンロードします: {MODEL_DIR}", file=sys.stderr)
        snapshot_download(repo_id="openai/whisper-small", local_dir=MODEL_DIR)

    import torch

    use_cuda = torch.cuda.is_available()
    device = 0 if use_cuda else -1
    dtype = torch.float16 if use_cuda else torch.float32
    print(f"モデル: {MODEL_DIR} / device: {'cuda' if use_cuda else 'cpu'}", file=sys.stderr)
    return pipeline(
        "automatic-speech-recognition",
        model=str(MODEL_DIR),
        device=device,
        torch_dtype=dtype,
    )


def transcribe(pipe, path: Path, language: str, prompt: str) -> str:
    audio = decode_mp4(path)
    generate_kwargs = {"language": language, "task": "transcribe"}
    if prompt:
        # Whisper expects the textual initial prompt as token ids.
        generate_kwargs["prompt_ids"] = pipe.tokenizer.get_prompt_ids(prompt, return_tensors="pt")
    result = pipe(
        {"raw": audio, "sampling_rate": 16000},
        chunk_length_s=30,
        stride_length_s=5,
        return_timestamps=False,
        generate_kwargs=generate_kwargs,
    )
    return str(result["text"]).strip()


def main() -> int:
    parser = argparse.ArgumentParser(description="data内のMP4をローカルWhisperで文字起こしします")
    parser.add_argument("files", nargs="*", type=Path, help="対象の音声・動画ファイル。省略時は --all が必要")
    parser.add_argument("--all", action="store_true", help="data/内の音声・動画ファイルを処理")
    parser.add_argument("--language", default="japanese", help="Whisperの言語名（既定: japanese）")
    parser.add_argument("--no-prompt", action="store_true", help="専門用語プロンプトを無効化")
    parser.add_argument("--save", action="store_true", help="各MP4の隣に .txt でも保存")
    args = parser.parse_args()

    files = [path if path.is_absolute() else ROOT / path for path in args.files]
    if args.all:
        extensions = {".mp4", ".m4a", ".mp3", ".wav", ".webm", ".mov", ".aac", ".flac"}
        files.extend(sorted(path for path in DATA_DIR.iterdir() if path.is_file() and path.suffix.lower() in extensions))
    files = list(dict.fromkeys(files))
    if not files:
        parser.error("MP4を指定するか --all を指定してください")
    missing = [path for path in files if not path.is_file()]
    if missing:
        parser.error("ファイルが見つかりません: " + ", ".join(map(str, missing)))

    pipe = get_pipeline()
    prompt = "" if args.no_prompt else PROMPT
    for index, path in enumerate(files, 1):
        print(f"\n[{index}/{len(files)}] {path}", file=sys.stderr)
        text = transcribe(pipe, path, args.language, prompt)
        print(f"\n===== {path.name} =====\n{text}")
        if args.save:
            output = path.with_suffix(".txt")
            output.write_text(text + "\n", encoding="utf-8")
            print(f"保存: {output}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
