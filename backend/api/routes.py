import asyncio
from datetime import datetime
from urllib.parse import unquote
import json
import re

from fastapi import BackgroundTasks, Depends, File, Form, HTTPException, Request, UploadFile
from fastapi.responses import JSONResponse
from starlette.datastructures import UploadFile as StarletteUploadFile

from api.auth import (
    COOKIE_NAME, login as login_account, logout as logout_account,
    public_account, require_account, require_admin, set_auth_cookie,
)
from db.database import database, get_state, insert_message, list_messages, new_id, now_iso, public_message, row_dict, update_state
from db.memory import ensure_session_memory, finalize_session, get_session_memory, load_participant_profile, load_task_memory
from interview.agent import ENDINGS, extract_turn, initial_state, run_interview_turn
from interview.diagnostics import log_event, log_turn, logger
from interview.longitudinal import starter as longitudinal_starter
from interview.profile_agent import run_profile_turn, starter as profile_starter
from config import load_config
from llm.client import status as llm_status
from llm.terminology import prepare_text
from whisper.main import whisper as local_whisper


LANGUAGES = {"ja", "en", "de"}


def _lang(value) -> str:
    return value if value in LANGUAGES else "ja"


def _owned_session(session_id: str, account: dict) -> dict:
    with database() as connection:
        query = "SELECT * FROM interview_sessions WHERE id=?"
        args: tuple = (session_id,)
        if account["role"] != "admin":
            query += " AND account_id=?"
            args = (session_id, account["id"])
        session = row_dict(connection.execute(query, args).fetchone())
    if not session:
        raise HTTPException(404, "Session not found")
    return session


def _session_payload(session: dict) -> dict:
    with database() as connection:
        messages = list_messages(connection, session["id"])
        saved_state = get_state(connection, session["id"])
        memory = get_session_memory(connection, session["id"])
    return {
        "session": session,
        "messages": [public_message(item) for item in messages],
        "state": saved_state["state"] if saved_state else initial_state(),
        "stateLabel": saved_state["stateLabel"] if saved_state else "running",
        "memory": memory,
    }


def _touch_session(session_id: str, *, status: str | None = None, ended_at: str | None = None) -> None:
    with database() as connection:
        if status is None:
            connection.execute("UPDATE interview_sessions SET updated_at=? WHERE id=?", (now_iso(), session_id))
        else:
            connection.execute(
                "UPDATE interview_sessions SET status=?, ended_at=?, updated_at=? WHERE id=?",
                (status, ended_at, now_iso(), session_id),
            )


def _update_stagnation(session_id: str, count: int) -> None:
    with database() as connection:
        connection.execute(
            """INSERT INTO longitudinal_session_states (session_id, depth_stagnation_count, updated_at)
               VALUES (?, ?, ?) ON CONFLICT(session_id) DO UPDATE SET
               depth_stagnation_count=excluded.depth_stagnation_count, updated_at=excluded.updated_at""",
            (session_id, count, now_iso()),
        )


def _stagnation(session_id: str) -> int:
    with database() as connection:
        row = connection.execute(
            "SELECT depth_stagnation_count FROM longitudinal_session_states WHERE session_id=?", (session_id,)
        ).fetchone()
        return int(row[0]) if row else 0


async def _run_turn(state: dict, content: str, history: list[dict], language: str, memory: dict, stalled: int = 0,
                    *, session_id: str = "") -> dict:
    if memory["session_count"] == 0:
        return await run_profile_turn(state, content, history, language, memory["profile"],
                                      domain_knowledge=memory.get("domain_knowledge", []))
    # Identify the task from the current answer before retrieving past sessions.
    # Past answers must not contaminate extraction or the current session's scores.
    info = await extract_turn(content, state, history)
    active = state.get("deep_dive")
    target_work = (active["return_target_work"] if active else
                   info.get("target_work") or state.get("target_work"))
    relevant = {"profile": memory["profile"], "current_session_id": session_id, "sessions": []}
    if target_work:
        relevant = load_task_memory(memory["account_id"], target_work, exclude_session_id=session_id,
                                    profile=memory["profile"])
        log_event("memory_referenced", session_id, target_work=target_work, memory=relevant)
    relevant["domain_knowledge"] = memory.get("domain_knowledge", [])
    contextual_history = list(history)
    if stalled >= load_config("interview")["guidance"]["stagnation_turns"]:
        reminder = "今の質問方針に沿い、既に答えた内容や理由を聞き直さない。"
        log_event("stagnation_guidance", session_id, depth_stagnation_count=stalled,
                  guidance=reminder)
        contextual_history.insert(0, {
            "context": True,
            "role": "system",
            "content": "【補足】" + reminder,
        })
    return await run_interview_turn(state, content, contextual_history, language,
                                    extracted=info, task_memory=relevant)


async def _process_message(session: dict, body: dict, background_tasks: BackgroundTasks) -> dict:
    if session["status"] == "ended":
        raise HTTPException(409, "Session has ended")
    content = prepare_text(str(body.get("maskedText") or ""))["maskedText"].strip()
    if not content:
        raise HTTPException(400, "maskedText is required")
    mode = "voice" if body.get("inputMode") == "voice" else "text"
    with database() as connection:
        saved = get_state(connection, session["id"])
        state = saved["state"] if saved else initial_state()
        insert_message(connection, session["id"], "user", content, mode, session["language"])
        history = list_messages(connection, session["id"])
    memory = load_participant_profile(session["account_id"])
    stalled = _stagnation(session["id"])
    before_depth = state.get("task_depth", 0)
    result = await _run_turn(state, content, history, session["language"], memory, stalled, session_id=session["id"])
    next_stalled = stalled + 1 if result["state"].get("task_depth", 0) == before_depth else 0
    _update_stagnation(session["id"], next_stalled)
    with database() as connection:
        insert_message(connection, session["id"], "system", result["text"], "system", session["language"], {
            "extracted": result.get("extracted"), "guide": result.get("guide"),
            "stateSnapshot": result["state"], "depthStagnationCount": next_stalled,
        })
        update_state(connection, session["id"], result["state"], result["stateLabel"])
        stamp = now_iso()
        if result["stateLabel"] == "end":
            connection.execute(
                "UPDATE interview_sessions SET status='ended', ended_at=?, updated_at=? WHERE id=?",
                (stamp, stamp, session["id"]),
            )
        else:
            connection.execute("UPDATE interview_sessions SET updated_at=? WHERE id=?", (stamp, session["id"]))
    log_turn(session["id"], result, depth_stagnation_count=next_stalled)
    if result["stateLabel"] == "end":
        with database() as connection:
            messages = list_messages(connection, session["id"])
        ensure_session_memory(session["account_id"], session["id"], messages)
        background_tasks.add_task(_finalize_session_safe, session)
    updated = {**session, "status": "ended" if result["stateLabel"] == "end" else session["status"]}
    return _session_payload(updated)


async def _finalize_session_safe(session: dict) -> None:
    try:
        with database() as connection:
            messages = list_messages(connection, session["id"])
        await finalize_session(session["account_id"], session["id"], session["language"], messages)
    except Exception:
        logger.exception("[interview] session_id=%s Failed to finalize session memory", session["id"])


async def _replay_after_edit(session: dict, message_id: str, content: str) -> dict:
    with database() as connection:
        rows = list_messages(connection, session["id"])
    edit_index = next((i for i, row in enumerate(rows) if row["id"] == message_id and row["role"] == "user"), -1)
    if edit_index < 0:
        raise HTTPException(404, "Editable user message not found")
    retained = rows[:edit_index]
    user_turns = [row for row in retained if row["role"] == "user"] + [{**rows[edit_index], "content": content}]
    opening = next((row for row in retained if row["role"] == "system"), None)
    with database() as connection:
        connection.execute("DELETE FROM messages WHERE session_id=?", (session["id"],))
        connection.execute("DELETE FROM interview_states WHERE session_id=?", (session["id"],))
        state = initial_state()
        if opening:
            insert_message(connection, session["id"], "system", opening["content"], "system", session["language"])
    memory = load_participant_profile(session["account_id"])
    for turn in user_turns:
        with database() as connection:
            insert_message(connection, session["id"], "user", turn["content"], turn["input_mode"], session["language"])
            history = list_messages(connection, session["id"])
        result = await _run_turn(state, turn["content"], history, session["language"], memory, session_id=session["id"])
        state = result["state"]
        with database() as connection:
            insert_message(connection, session["id"], "system", result["text"], "system", session["language"], {
                "extracted": result.get("extracted"), "guide": result.get("guide"), "stateSnapshot": state,
            })
        log_turn(session["id"], result, replay=True)
    with database() as connection:
        update_state(connection, session["id"], state, "running")
        connection.execute(
            "UPDATE interview_sessions SET status='running', ended_at=NULL, updated_at=? WHERE id=?",
            (now_iso(), session["id"]),
        )
    return _session_payload({**session, "status": "running", "ended_at": None})


async def status():
    return llm_status()


async def mask_text(body: dict, account: dict = Depends(require_account)):
    text = str(body.get("text", "")).strip()
    if not text:
        raise HTTPException(400, "text is required")
    return prepare_text(text)


async def local_transcribe(file: UploadFile = File(...), language: str = Form("ja"),
                           account: dict = Depends(require_account)):
    content = await file.read()
    if not content:
        raise HTTPException(400, "Audio file is empty")
    try:
        raw_text = await asyncio.to_thread(
            local_whisper.transcribe, content, file.filename or "audio.webm", language
        )
    except Exception as error:
        raise HTTPException(502, str(error)) from error
    return {"rawText": raw_text, **prepare_text(raw_text)}


async def auth_login(request: Request, body: dict):
    account_id = str(body.get("id") or body.get("qrToken") or "")
    prefix = "audiointerview://login?id="
    if account_id.startswith(prefix):
        account_id = account_id[len(prefix):]
    account_id = unquote(account_id)
    if not account_id:
        raise HTTPException(400, "ID is required")
    account, token = login_account(account_id, body.get("password"))
    response = JSONResponse({"account": account, "token": token})
    set_auth_cookie(response, request, token)
    return response


async def auth_logout(request: Request):
    logout_account(request.cookies.get(COOKIE_NAME))
    response = JSONResponse({"ok": True})
    set_auth_cookie(response, request, "", clear=True)
    return response


async def me(account: dict = Depends(require_account)):
    return {"account": public_account(account)}


async def change_password(request: Request, body: dict, account: dict = Depends(require_admin)):
    password = str(body.get("password") or "")
    if len(password) < 6:
        raise HTTPException(400, "Password must be at least 6 characters")
    from api.auth import hash_password
    salt = new_id("salt")
    with database() as connection:
        connection.execute(
            "UPDATE accounts SET password_hash=?, password_salt=?, updated_at=? WHERE id=?",
            (hash_password(password, salt), salt, now_iso(), account["id"]),
        )
    return {"ok": True}


async def sessions(account: dict = Depends(require_account)):
    with database() as connection:
        if account["role"] == "admin":
            rows = connection.execute("SELECT * FROM interview_sessions ORDER BY updated_at DESC").fetchall()
        else:
            rows = connection.execute(
                "SELECT * FROM interview_sessions WHERE account_id=? ORDER BY updated_at DESC", (account["id"],)
            ).fetchall()
    return {"sessions": [dict(row) for row in rows]}


async def create_session(body: dict, account: dict = Depends(require_account)):
    language = _lang(body.get("language"))
    session_id = new_id("interview")
    title = str(body.get("title") or "").strip() or f"Interview {datetime.now().strftime('%Y/%m/%d')}"
    stamp = now_iso()
    with database() as connection:
        connection.execute(
            """INSERT INTO interview_sessions (id, account_id, title, language, status, started_at, updated_at)
               VALUES (?, ?, ?, ?, 'running', ?, ?)""",
            (session_id, account["id"], title, language, stamp, stamp),
        )
        session = row_dict(connection.execute("SELECT * FROM interview_sessions WHERE id=?", (session_id,)).fetchone())
    return _session_payload(session)


async def get_session(session_id: str, account: dict = Depends(require_account)):
    return _session_payload(_owned_session(session_id, account))


async def start_session(session_id: str, account: dict = Depends(require_account)):
    session = _owned_session(session_id, account)
    with database() as connection:
        existing = list_messages(connection, session_id)
    if not existing:
        memory = load_participant_profile(session["account_id"])
        opening = (
            await profile_starter(session["language"], domain_knowledge=memory.get("domain_knowledge", []))
            if memory["session_count"] == 0
            else await longitudinal_starter(session["language"], memory["session_count"], memory["profile"],
                                            domain_knowledge=memory.get("domain_knowledge", []))
        )
        with database() as connection:
            insert_message(connection, session_id, "system", opening, "system", session["language"],
                            {"stateSnapshot": initial_state()})
            update_state(connection, session_id, initial_state(), "running")
        _update_stagnation(session_id, 0)
        log_event("session_started", session_id,
                  mode="profile" if memory["session_count"] == 0 else "interview",
                  state=initial_state(), memory=memory, opening=opening)
    return _session_payload(session)


async def send_message(session_id: str, body: dict, background_tasks: BackgroundTasks,
                       account: dict = Depends(require_account)):
    session = _owned_session(session_id, account)
    if session["status"] == "ended":
        raise HTTPException(409, "Session has ended")
    content = str(body.get("maskedText") or "").strip()
    if body.get("editMessageId"):
        return await _replay_after_edit(session, str(body["editMessageId"]), prepare_text(content)["maskedText"])
    return await _process_message(session, body, background_tasks)


async def end_session(session_id: str, background_tasks: BackgroundTasks,
                      account: dict = Depends(require_account)):
    session = _owned_session(session_id, account)
    if session["status"] != "ended":
        with database() as connection:
            insert_message(connection, session_id, "system", ENDINGS[session["language"]], "system", session["language"])
            saved = get_state(connection, session_id)
            update_state(connection, session_id, saved["state"] if saved else initial_state(), "end")
            stamp = now_iso()
            connection.execute(
                "UPDATE interview_sessions SET status='ended', ended_at=?, updated_at=? WHERE id=?",
                (stamp, stamp, session_id),
            )
        background_tasks.add_task(_finalize_session_safe, session)
        with database() as connection:
            messages = list_messages(connection, session_id)
        ensure_session_memory(session["account_id"], session_id, messages)
        log_event("session_ended", session_id, reason="manual",
                  state=saved["state"] if saved else initial_state())
    return _session_payload({**session, "status": "ended", "ended_at": now_iso()})


async def speech_transcribe(request: Request, account: dict = Depends(require_account)):
    async with request.form() as form:
        upload = form.get("file") or form.get("audio")
        if not isinstance(upload, StarletteUploadFile):
            raise HTTPException(400, "Audio file is required")
        content = await upload.read()
        filename = upload.filename or "audio.webm"
        language = str(form.get("language") or "ja")
    if not content:
        raise HTTPException(400, "Audio file is empty")
    raw_text = await asyncio.to_thread(local_whisper.transcribe, content, filename, language)
    # Preserve the raw transcript for display, and keep the stop command out of the answer.
    command = re.search(r"(?:\bover\b|オーバー|オーバ|おーばー|おおばー)[\s.,!?。、！？]*$", raw_text, re.I)
    answer = raw_text[:command.start()].rstrip() if command else raw_text
    normalized = prepare_text(answer)
    return {"rawText": raw_text, **normalized, "endOfTurn": command is not None}


async def admin_accounts(account: dict = Depends(require_admin)):
    with database() as connection:
        rows = connection.execute(
            "SELECT id, role, display_name, is_active, created_at FROM accounts ORDER BY created_at DESC"
        ).fetchall()
    return {"accounts": [dict(row) for row in rows]}


async def create_operator(body: dict, account: dict = Depends(require_admin)):
    account_id = str(body.get("id") or "").strip() or new_id("operator")[:17]
    display_name = str(body.get("displayName") or "").strip() or account_id
    if not re.fullmatch(r"[A-Za-z0-9_-]{3,40}", account_id):
        raise HTTPException(400, "ID must be 3-40 letters, numbers, _ or -")
    try:
        with database() as connection:
            existing = row_dict(connection.execute(
                "SELECT id, role, is_active FROM accounts WHERE id=?", (account_id,)
            ).fetchone())
            if existing and existing["role"] != "operator":
                raise HTTPException(409, "That ID already exists")
            if existing and existing["is_active"]:
                raise HTTPException(409, "That ID already exists")
            if existing:
                connection.execute(
                    "UPDATE accounts SET display_name=?, is_active=1, updated_at=? WHERE id=?",
                    (display_name, now_iso(), account_id),
                )
            else:
                connection.execute(
                    "INSERT INTO accounts (id, role, display_name) VALUES (?, 'operator', ?)",
                    (account_id, display_name),
                )
    except Exception as error:
        if isinstance(error, HTTPException):
            raise
        raise HTTPException(409, "That ID already exists") from error
    from urllib.parse import quote
    return {
        "account": {"id": account_id, "role": "operator", "displayName": display_name},
        "id": account_id, "qrToken": f"audiointerview://login?id={quote(account_id)}",
    }


async def deactivate_operator(account_id: str, account: dict = Depends(require_admin)):
    with database() as connection:
        cursor = connection.execute(
            "UPDATE accounts SET is_active=0, updated_at=? WHERE id=? AND role='operator' AND is_active=1",
            (now_iso(), account_id),
        )
        if not cursor.rowcount:
            raise HTTPException(404, "Account not found")
    return {"ok": True}


async def admin_histories(account: dict = Depends(require_admin)):
    with database() as connection:
        rows = connection.execute(
            """SELECT interview_sessions.*, accounts.display_name,
               (SELECT COUNT(*) FROM messages WHERE messages.session_id=interview_sessions.id) AS message_count
               FROM interview_sessions JOIN accounts ON accounts.id=interview_sessions.account_id
               ORDER BY interview_sessions.updated_at DESC"""
        ).fetchall()
    return {"histories": [dict(row) for row in rows]}
