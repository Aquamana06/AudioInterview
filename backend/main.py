"""FastAPI application and backend entry point."""

import argparse
import asyncio
import time

import uvicorn

from api.settings import setting
from config import load_config

from contextlib import asynccontextmanager, suppress
import logging

from fastapi import FastAPI, HTTPException, Request
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException

from api.auth import ensure_admin
from api import routes
from api.settings import BACKEND_ROOT
from db.database import initialize_database
from db.memory import recover_session_memories
from llm.client import configured, model as llm_model, status as llm_status
from llm.local_qwen import warmup as warmup_qwen
from interview.diagnostics import configure_logging


@asynccontextmanager
async def lifespan(_: FastAPI):
    configure_logging()
    initialize_database()
    ensure_admin()
    logger = logging.getLogger("uvicorn.error")
    started = time.monotonic()
    if configured():
        logger.info("Warming Qwen: %s", llm_model())
        await asyncio.to_thread(warmup_qwen, llm_model())
    logger.info("Warming Whisper: %s", routes.local_whisper.model_name)
    await asyncio.to_thread(routes.local_whisper.warmup)
    logger.info("Models ready; startup warmup took %.1fs", time.monotonic() - started)
    recovery = asyncio.create_task(recover_session_memories())
    try:
        yield
    finally:
        recovery.cancel()
        with suppress(asyncio.CancelledError):
            await recovery


app = FastAPI(title="AudioInterview API", lifespan=lifespan)
app.add_middleware(
    CORSMiddleware,
    allow_origin_regex=r"https?://(localhost|127\.0\.0\.1|192\.168\.\d+\.\d+|100\.64\.\d+\.\d+)(:\d+)?",
    allow_credentials=True,
    allow_methods=["GET", "POST", "PUT", "DELETE", "OPTIONS", "HEAD"],
    allow_headers=["*"],
)
# URL・HTTP メソッド・処理関数・機能名の対応
app.add_api_route("/api/status", routes.status, methods=["GET"], summary="LLM 設定状態")
app.add_api_route("/api/local/mask-text", routes.mask_text, methods=["POST"], summary="テキストのマスキング")
app.add_api_route("/api/local/transcribe", routes.local_transcribe, methods=["POST"], summary="ローカル音声認識")
app.add_api_route("/api/auth/login", routes.auth_login, methods=["POST"], summary="ログイン")
app.add_api_route("/api/auth/logout", routes.auth_logout, methods=["POST"], summary="ログアウト")
app.add_api_route("/api/me", routes.me, methods=["GET"], summary="ログイン中のアカウント")
app.add_api_route("/api/me/password", routes.change_password, methods=["PUT"], summary="管理者パスワード変更")
app.add_api_route("/api/sessions", routes.sessions, methods=["GET"], summary="セッション一覧")
app.add_api_route("/api/sessions", routes.create_session, methods=["POST"], status_code=201, summary="セッション作成")
app.add_api_route("/api/sessions/{session_id}", routes.get_session, methods=["GET"], summary="セッション詳細")
app.add_api_route("/api/sessions/{session_id}/start", routes.start_session, methods=["POST"], summary="インタビュー開始")
app.add_api_route("/api/sessions/{session_id}/messages", routes.send_message, methods=["POST"], summary="回答の投稿・編集")
app.add_api_route("/api/sessions/{session_id}/end", routes.end_session, methods=["POST"], summary="インタビュー終了")
app.add_api_route("/api/speech/transcribe", routes.speech_transcribe, methods=["POST"], summary="音声ファイルの文字起こし")
app.add_api_route("/api/admin/accounts", routes.admin_accounts, methods=["GET"], summary="アカウント一覧")
app.add_api_route("/api/admin/accounts", routes.create_operator, methods=["POST"], status_code=201, summary="オペレータ発行")
app.add_api_route("/api/admin/accounts/{account_id}", routes.deactivate_operator, methods=["DELETE"], summary="オペレータ無効化")
app.add_api_route("/api/admin/histories", routes.admin_histories, methods=["GET"], summary="全インタビュー履歴")


@app.exception_handler(StarletteHTTPException)
async def http_error(_: Request, error: StarletteHTTPException):
    detail = error.detail if isinstance(error.detail, str) else "Request failed"
    return JSONResponse({"error": detail}, status_code=error.status_code, headers=error.headers)


@app.exception_handler(RequestValidationError)
async def validation_error(_: Request, error: RequestValidationError):
    return JSONResponse({"error": "Invalid request"}, status_code=422)


@app.exception_handler(Exception)
async def internal_error(_: Request, error: Exception):
    logging.getLogger(__name__).exception("Unhandled API error", exc_info=error)
    return JSONResponse({"error": str(error) or "Unexpected error"}, status_code=500)


@app.get("/health")
async def health():
    return {
        "status": "ok", "service": "audiointerview-backend",
        "models": {"llm": llm_status(), "whisper": {
            "model": routes.local_whisper.model_name,
            "device": routes.local_whisper.device,
            "computeType": routes.local_whisper.compute_type,
            "ready": routes.local_whisper.ready,
        }},
    }


FRONTEND_DIST = BACKEND_ROOT.parent / "frontend" / "dist"


@app.get("/{path:path}", include_in_schema=False)
async def frontend_files(path: str):
    if path.startswith("api/"):
        raise HTTPException(404, "Not found")
    candidate = (FRONTEND_DIST / path).resolve()
    try:
        candidate.relative_to(FRONTEND_DIST.resolve())
    except ValueError:
        raise HTTPException(404, "Not found")
    if candidate.is_file():
        return FileResponse(candidate)
    index = FRONTEND_DIST / "index.html"
    if index.is_file():
        return FileResponse(index)
    raise HTTPException(404, "Frontend build not found. Run npm run build in frontend/.")


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    server = load_config("api")["server"]
    parser = argparse.ArgumentParser(description="AudioInterview API サーバー")
    parser.add_argument("--host", default=setting("AUDIOINTERVIEW_HOST", server["host"]))
    parser.add_argument("--port", type=int, default=setting("AUDIOINTERVIEW_PORT", str(server["port"])))
    args = parser.parse_args(argv)
    if not 1 <= args.port <= 65535:
        parser.error("--port は 1〜65535 の範囲で指定してください")
    return args


def main(argv: list[str] | None = None) -> None:
    args = parse_args(argv)
    uvicorn.run(app, host=args.host, port=args.port)


if __name__ == "__main__":
    main()
