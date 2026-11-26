"""Local recordings and session JSON archives; no model imports or inference."""

import hashlib
import json
import logging
import os
from pathlib import Path
import re
import sqlite3
from tempfile import NamedTemporaryFile

from api.settings import database_path
from db.database import database, list_messages, now_iso


logger = logging.getLogger("audiointerview")
COMPONENT = re.compile(r"[A-Za-z0-9_-]{1,100}")
EXTENSIONS = {".webm", ".wav", ".ogg", ".mp4", ".m4a", ".mp3", ".flac"}
MIME_EXTENSIONS = {
    "audio/webm": ".webm", "video/webm": ".webm", "audio/wav": ".wav",
    "audio/x-wav": ".wav", "audio/ogg": ".ogg", "audio/mp4": ".mp4",
    "audio/mpeg": ".mp3", "audio/flac": ".flac",
}


class RecordingConflict(ValueError):
    pass


def archive_root() -> Path:
    return database_path().resolve().parent / "interviews"


def session_directory(session_id: str) -> Path:
    if not COMPONENT.fullmatch(session_id):
        raise ValueError("Invalid session ID")
    root = archive_root().resolve()
    path = (root / session_id).resolve()
    path.relative_to(root)
    return path


def atomic_write(path: Path, data: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = None
    try:
        with NamedTemporaryFile(dir=path.parent, prefix=".pending-", delete=False) as file:
            temporary = Path(file.name)
            file.write(data)
            file.flush()
            os.fsync(file.fileno())
        os.replace(temporary, path)
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)


def save_recording(session_id: str, recording_id: str, content: bytes,
                   filename: str, content_type: str) -> dict:
    if not COMPONENT.fullmatch(recording_id):
        raise ValueError("Invalid recording ID")
    if not content:
        raise ValueError("Audio file is empty")
    media_type = content_type.split(";", 1)[0].lower()
    suffix = MIME_EXTENSIONS.get(media_type, Path(filename).suffix.lower())
    if suffix not in EXTENSIONS:
        raise ValueError("Unsupported audio format")
    digest = hashlib.sha256(content).hexdigest()
    with database() as connection:
        # Serialize duplicate uploads so one recording ID always means one file.
        connection.execute("BEGIN IMMEDIATE")
        session = connection.execute("SELECT status FROM interview_sessions WHERE id=?", (session_id,)).fetchone()
        if session is None:
            raise ValueError("Session not found")
        if session["status"] == "ended":
            raise RecordingConflict("Session has ended")
        existing = connection.execute("SELECT * FROM interview_recordings WHERE id=?", (recording_id,)).fetchone()
        if existing:
            if existing["session_id"] != session_id or existing["sha256"] != digest:
                raise RecordingConflict("Recording ID already belongs to different audio")
            audio_file = existing["audio_file"]
        else:
            audio_file = f"audio/{recording_id}{suffix}"
        path = session_directory(session_id) / audio_file
        atomic_write(path, content)
        if not existing:
            connection.execute(
                """INSERT INTO interview_recordings
                   (id, session_id, audio_file, content_type, sha256, created_at) VALUES (?, ?, ?, ?, ?, ?)""",
                (recording_id, session_id, audio_file, media_type, digest, now_iso()),
            )
    return {"recordingId": recording_id, "audioFile": audio_file}


def recording_for_message(connection: sqlite3.Connection, session_id: str, recording_id: str) -> dict:
    row = connection.execute(
        "SELECT * FROM interview_recordings WHERE id=? AND session_id=?", (recording_id, session_id)
    ).fetchone()
    if row is None:
        raise ValueError("Recording not found for this session")
    if not (session_directory(session_id) / row["audio_file"]).is_file():
        raise ValueError("Recording file is missing")
    return dict(row)


def session_document(connection: sqlite3.Connection, session_id: str, *, simple: bool = False) -> dict:
    session = connection.execute(
        """SELECT s.*, a.user_name FROM interview_sessions s
           JOIN interview_archives a ON a.session_id=s.id WHERE s.id=?""", (session_id,)
    ).fetchone()
    if session is None:
        raise ValueError("Session not found")
    recordings = {row["message_id"]: row["audio_file"] for row in connection.execute(
        "SELECT message_id, audio_file FROM interview_recordings WHERE session_id=? AND message_id IS NOT NULL",
        (session_id,),
    )}
    messages = []
    for row in list_messages(connection, session_id):
        message = {"role": row["role"], "message": row["content"]}
        if not simple and row["role"] == "user":
            message = {"message_id": row["id"], **message, "audio_file": recordings.get(row["id"])}
        messages.append(message)
    return {"account_id": session["account_id"], "user_name": session["user_name"],
            "session_id": session_id, "messages": messages}


def write_session_archive(session_id: str) -> Path:
    with database() as connection:
        connection.execute("BEGIN IMMEDIATE")
        session = connection.execute("SELECT status FROM interview_sessions WHERE id=?", (session_id,)).fetchone()
        if session is None or session["status"] != "ended":
            raise ValueError("Only ended sessions can be archived")
        document = session_document(connection, session_id)
        path = session_directory(session_id) / "transcript.json"
        atomic_write(path, (json.dumps(document, ensure_ascii=False, indent=2) + "\n").encode("utf-8"))
        connection.execute(
            "UPDATE interview_archives SET status='ready', exported_at=?, last_error=NULL WHERE session_id=?",
            (now_iso(), session_id),
        )
    return path


def archive_session_safe(session_id: str) -> bool:
    try:
        write_session_archive(session_id)
        return True
    except Exception as error:
        logger.exception("[archive] session_id=%s JSON save failed", session_id)
        with database() as connection:
            connection.execute(
                "UPDATE interview_archives SET status='pending', last_error=? WHERE session_id=?",
                (str(error), session_id),
            )
        return False


def recover_archives(*, force: bool = False) -> int:
    with database() as connection:
        sessions = connection.execute(
            """SELECT s.id, a.status FROM interview_sessions s
               JOIN interview_archives a ON a.session_id=s.id WHERE s.status='ended'"""
        ).fetchall()
    saved = 0
    for session in sessions:
        if force or session["status"] != "ready" or not (session_directory(session["id"]) / "transcript.json").is_file():
            saved += archive_session_safe(session["id"])
    return saved
