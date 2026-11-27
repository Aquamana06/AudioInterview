"""List and export interviews without starting the API or loading models."""

import argparse
from contextlib import closing
from datetime import date, datetime
import json
from pathlib import Path
import secrets
import shutil
import sqlite3
from tempfile import TemporaryDirectory

from api.settings import BACKEND_ROOT, database_path
from db.archive import archive_root, recover_archives, session_directory, session_document
from db.database import initialize_database


EXPORT_ROOT = BACKEND_ROOT.parent / "tmp"


def parser() -> argparse.ArgumentParser:
    result = argparse.ArgumentParser(description="インタビューデータの参照・取り出し")
    commands = result.add_subparsers(dest="command", required=True)
    for name in ("list", "export"):
        command = commands.add_parser(name)
        selection = command.add_mutually_exclusive_group(required=name == "export")
        selection.add_argument("--all", action="store_true")
        selection.add_argument("--account-id")
        selection.add_argument("--user-name", "--display-name", dest="user_name", help="現在の表示名（完全一致）")
        selection.add_argument("--session-id")
        command.add_argument("--status", choices=("running", "ended", "all"), default="ended" if name == "export" else None)
        command.add_argument("--date", type=date.fromisoformat, help="開始日で絞り込み（日本時間、YYYY-MM-DD）")
        if name == "export":
            command.add_argument("--format", choices=("simple", "archive"), default="simple")
            command.add_argument("--include-audio", action="store_true")
            output = command.add_mutually_exclusive_group()
            output.add_argument("--output", type=Path)
            output.add_argument("--output-dir", type=Path)
    rebuild = commands.add_parser("rebuild", help="DBを更新し、終了済みJSONの出力を再試行")
    rebuild.add_argument("--force", action="store_true", help="出力済みJSONもDBから再生成")
    return result


def main(argv: list[str] | None = None) -> None:
    arguments = parser()
    args = arguments.parse_args(argv)
    path = database_path().resolve()
    if not path.is_file():
        arguments.error(f"DBがありません: {path}")
    if args.command == "rebuild":
        initialize_database()
        saved = recover_archives(force=args.force)
        with closing(sqlite3.connect(path.as_uri() + "?mode=ro", uri=True)) as db:
            pending = db.execute("""SELECT COUNT(*) FROM interview_archives a
                JOIN interview_sessions s ON s.id=a.session_id
                WHERE s.status='ended' AND a.status='pending'""").fetchone()[0]
        print(f"{saved}セッションのJSONを保存しました。未完了: {pending}。保存先: {archive_root()}")
        if pending:
            raise SystemExit(1)
        return
    if args.command == "export":
        if args.format == "archive" and args.output is not None:
            arguments.error("archive形式で出力先を指定する場合は --output-dir を使用してください")
        if args.format == "simple" and args.output_dir is not None:
            arguments.error("simple形式で出力先を指定する場合は --output を使用してください")
        if args.include_audio and args.format != "archive":
            arguments.error("--include-audio はarchive形式で指定してください")
    status = None if args.status == "all" else args.status
    try:
        with closing(sqlite3.connect(path.as_uri() + "?mode=ro", uri=True)) as db:
            db.row_factory = sqlite3.Row
            db.execute("BEGIN")
            account_id = args.account_id
            if args.user_name is not None:
                accounts = db.execute(
                    "SELECT id FROM accounts WHERE display_name=? ORDER BY id", (args.user_name,)
                ).fetchall()
                if not accounts:
                    arguments.error(f"表示名「{args.user_name}」のアカウントがありません")
                if len(accounts) > 1:
                    candidates = ", ".join(account["id"] for account in accounts)
                    arguments.error(
                        f"表示名「{args.user_name}」が複数あります。--account-id で指定してください: {candidates}"
                    )
                account_id = accounts[0]["id"]
            rows = db.execute("""
                SELECT s.id AS session_id, s.account_id, a.user_name, s.status,
                       s.started_at, a.status AS archive_status, a.last_error,
                       (SELECT COUNT(*) FROM messages m WHERE m.session_id=s.id) AS message_count
                FROM interview_sessions s JOIN interview_archives a ON a.session_id=s.id
                WHERE (? IS NULL OR s.account_id=?) AND (? IS NULL OR s.id=?)
                  AND (? IS NULL OR s.status=?)
                  AND (? IS NULL OR date(s.started_at, '+9 hours')=?) ORDER BY s.started_at, s.id
            """, (account_id, account_id, args.session_id, args.session_id, status, status,
                  args.date.isoformat() if args.date else None, args.date.isoformat() if args.date else None)).fetchall()
            if args.command == "list":
                print(json.dumps([dict(row) for row in rows], ensure_ascii=False, indent=2))
                return
            documents = [session_document(db, row["session_id"], simple=args.format == "simple") for row in rows]
        if not documents:
            arguments.error("条件に一致するセッションがありません")
        if args.output is None and args.output_dir is None:
            EXPORT_ROOT.mkdir(parents=True, exist_ok=True)
            name = f"interviews_{datetime.now():%Y%m%d_%H%M%S_%f}_{secrets.token_hex(3)}"
            if args.format == "simple":
                args.output = EXPORT_ROOT / f"{name}.json"
            else:
                args.output_dir = EXPORT_ROOT / name
        if args.output is not None:
            data = json.dumps(documents, ensure_ascii=False, indent=2) + "\n"
            with args.output.open("x", encoding="utf-8") as file:
                file.write(data)
            print(f"{len(documents)}セッションを {args.output} に出力しました")
            return
        destination = args.output_dir.resolve()
        if destination.exists():
            arguments.error("出力先が既に存在します。別のフォルダを指定してください")
        if destination.is_relative_to(archive_root().resolve()):
            arguments.error("出力先は元の音声保存フォルダの外に指定してください")
        with TemporaryDirectory(dir=destination.parent, prefix=".interview-export-") as temporary:
            stage = Path(temporary) / "export"
            stage.mkdir()
            for document in documents:
                folder = stage / document["session_id"]
                folder.mkdir()
                if args.include_audio:
                    source = session_directory(document["session_id"])
                    for message in document["messages"]:
                        audio_file = message.get("audio_file")
                        if audio_file and not (source / audio_file).is_file():
                            raise FileNotFoundError(f"音声がありません: {source / audio_file}")
                    if (source / "audio").is_dir():
                        shutil.copytree(source / "audio", folder / "audio", ignore=shutil.ignore_patterns(".pending-*"))
                (folder / "transcript.json").write_text(
                    json.dumps(document, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
                )
            stage.rename(destination)
        print(f"{len(documents)}セッションを {destination} に出力しました")
    except sqlite3.OperationalError as error:
        arguments.error(f"DBを読み取れません。バックエンドを再起動するか rebuild を実行してください: {error}")
    except (OSError, ValueError) as error:
        arguments.error(str(error))


if __name__ == "__main__":
    main()
