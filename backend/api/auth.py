from hashlib import sha256
from datetime import timedelta
from urllib.parse import quote

from fastapi import HTTPException, Request

from db.database import database, new_id, now_iso, row_dict
from config import load_config


COOKIE_NAME = "ai_session"
SESSION_TTL = timedelta(days=load_config("api")["auth"]["session_ttl_days"])


def hash_password(password: str, salt: str) -> str:
    return sha256(f"{salt}:{password}".encode()).hexdigest()


def ensure_admin() -> None:
    with database() as connection:
        if connection.execute("SELECT 1 FROM accounts WHERE id='admin'").fetchone():
            return
        salt = new_id("salt")
        connection.execute(
            "INSERT INTO accounts (id, role, display_name, password_hash, password_salt) VALUES (?, 'admin', 'Administrator', ?, ?)",
            ("admin", hash_password("admin", salt), salt),
        )


def public_account(account: dict) -> dict:
    with database() as connection:
        acknowledged = connection.execute(
            "SELECT 1 FROM manual_acknowledgements WHERE account_id=?", (account["id"],)
        ).fetchone() is not None
    return {"id": account["id"], "role": account["role"], "displayName": account["display_name"],
            "manualAcknowledged": acknowledged}


def login(account_id: str, password: str | None) -> tuple[dict, str]:
    ensure_admin()
    with database() as connection:
        account = row_dict(connection.execute(
            "SELECT * FROM accounts WHERE id = ? AND is_active = 1", (account_id.strip(),)
        ).fetchone())
        if not account:
            raise HTTPException(401, "Unknown or inactive account")
        if account["role"] == "admin":
            if not password or not account["password_hash"] or not account["password_salt"]:
                raise HTTPException(401, "Admin password is required")
            if hash_password(password, account["password_salt"]) != account["password_hash"]:
                raise HTTPException(401, "Invalid admin password")
        token = new_id("sess")
        from datetime import datetime, timezone

        expires = (datetime.now(timezone.utc) + SESSION_TTL).isoformat(timespec="milliseconds").replace("+00:00", "Z")
        connection.execute(
            "INSERT INTO auth_sessions (token, account_id, expires_at, created_at) VALUES (?, ?, ?, ?)",
            (token, account["id"], expires, now_iso()),
        )
        return public_account(account), token


def logout(token: str | None) -> None:
    if token:
        with database() as connection:
            connection.execute("DELETE FROM auth_sessions WHERE token = ?", (token,))


def request_token(request: Request) -> str | None:
    authorization = request.headers.get("authorization", "")
    if authorization.lower().startswith("bearer "):
        return authorization[7:].strip()
    return request.cookies.get(COOKIE_NAME)


def require_account(request: Request) -> dict:
    token = request_token(request)
    if not token:
        raise HTTPException(401, "Authentication required")
    with database() as connection:
        account = row_dict(connection.execute(
            """SELECT accounts.* FROM auth_sessions
               JOIN accounts ON accounts.id = auth_sessions.account_id
               WHERE auth_sessions.token = ? AND auth_sessions.expires_at > ? AND accounts.is_active = 1""",
            (token, now_iso()),
        ).fetchone())
    if not account:
        raise HTTPException(401, "Authentication required")
    return account


def require_admin(request: Request) -> dict:
    account = require_account(request)
    if account["role"] != "admin":
        raise HTTPException(403, "Admin access required")
    return account


def set_auth_cookie(response, request: Request, token: str, clear: bool = False) -> None:
    secure = request.url.scheme == "https" or request.headers.get("x-forwarded-proto") == "https"
    response.set_cookie(
        COOKIE_NAME,
        "" if clear else token,
        max_age=0 if clear else int(SESSION_TTL.total_seconds()),
        httponly=True,
        secure=secure,
        samesite="lax",
        path="/",
    )
