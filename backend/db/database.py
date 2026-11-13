from contextlib import contextmanager
import sqlite3
from typing import Iterator

from api.settings import BACKEND_ROOT, database_path
from config import load_config


MIGRATIONS = BACKEND_ROOT / "db" / "migrations"


def connect() -> sqlite3.Connection:
    path = database_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    connection = sqlite3.connect(path, timeout=load_config("db")["database"]["timeout_seconds"], check_same_thread=False)
    connection.row_factory = sqlite3.Row
    connection.execute("PRAGMA foreign_keys = ON")
    return connection


@contextmanager
def database() -> Iterator[sqlite3.Connection]:
    connection = connect()
    try:
        yield connection
        connection.commit()
    except Exception:
        connection.rollback()
        raise
    finally:
        connection.close()


def initialize_database() -> None:
    connection = connect()
    try:
        for migration in sorted(MIGRATIONS.glob("*.sql")):
            connection.executescript(migration.read_text(encoding="utf-8"))
        connection.commit()
    finally:
        connection.close()


def row_dict(row: sqlite3.Row | None) -> dict | None:
    return dict(row) if row is not None else None


def new_id(prefix: str) -> str:
    import secrets

    return f"{prefix}_{secrets.token_hex(12)}"


def now_iso() -> str:
    from datetime import datetime, timezone

    return datetime.now(timezone.utc).isoformat(timespec="milliseconds").replace("+00:00", "Z")


def insert_message(
    connection: sqlite3.Connection,
    session_id: str,
    role: str,
    content: str,
    input_mode: str,
    language: str,
    meta: dict | None = None,
) -> str:
    message_id = new_id("usr" if role == "user" else "sys")
    stamp = now_iso()
    connection.execute(
        """INSERT INTO messages
           (id, session_id, role, content, input_mode, language, meta_json, created_at, updated_at)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
        (message_id, session_id, role, content, input_mode, language,
         __import__("json").dumps(meta, ensure_ascii=False) if meta else None, stamp, stamp),
    )
    return message_id


def list_messages(connection: sqlite3.Connection, session_id: str) -> list[dict]:
    return [dict(row) for row in connection.execute(
        "SELECT * FROM messages WHERE session_id = ? ORDER BY created_at ASC, rowid ASC", (session_id,)
    )]


def public_message(row: dict) -> dict:
    return {
        "id": row["id"], "role": row["role"], "content": row["content"],
        "inputMode": row["input_mode"], "language": row["language"],
        "createdAt": row["created_at"], "updatedAt": row["updated_at"],
    }


def get_state(connection: sqlite3.Connection, session_id: str) -> dict | None:
    import json

    row = connection.execute(
        "SELECT state_json, state_label FROM interview_states WHERE session_id = ?", (session_id,)
    ).fetchone()
    if row is None:
        return None
    return {"state": json.loads(row["state_json"]), "stateLabel": row["state_label"]}


def update_state(connection: sqlite3.Connection, session_id: str, state: dict, label: str) -> None:
    import json

    connection.execute(
        """INSERT INTO interview_states (session_id, state_json, state_label, updated_at)
           VALUES (?, ?, ?, ?)
           ON CONFLICT(session_id) DO UPDATE SET state_json=excluded.state_json,
             state_label=excluded.state_label, updated_at=excluded.updated_at""",
        (session_id, json.dumps(state, ensure_ascii=False), label, now_iso()),
    )
