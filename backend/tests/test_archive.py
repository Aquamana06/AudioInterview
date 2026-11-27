import contextlib
import io
import json
import sqlite3
from unittest.mock import AsyncMock, patch

from fastapi.testclient import TestClient

from backend_test_support import DatabaseTestCase, app, database, initialize_database
from api.settings import database_path
from db.archive import archive_root, recover_archives, save_recording, session_directory
from db.database import MIGRATIONS, insert_message
from interview.agent import initial_state
from tools.interviews import main as interviews_command


class ArchiveAPITests(DatabaseTestCase):
    def setUp(self):
        super().setUp()
        self.client = self.enterContext(TestClient(app))
        self.enterContext(patch("api.routes.profile_starter", AsyncMock(return_value="質問です。")))
        self.finalize = self.enterContext(patch("api.routes.finalize_session", AsyncMock()))
        self.turn = self.enterContext(patch("api.routes._run_turn", AsyncMock(return_value={
            "text": "次の質問です。", "state": initial_state(), "stateLabel": "running",
            "extracted": {}, "guide": {},
        })))
        self.login()
        self.session_id = self.client.post("/api/sessions", json={}).json()["session"]["id"]
        self.path = f"/api/sessions/{self.session_id}"
        self.client.post(self.path + "/start")

    def login(self, account_id="admin", password="admin"):
        response = self.client.post("/api/auth/login", json={"id": account_id, "password": password})
        self.assertEqual(response.status_code, 200, response.text)

    def upload(self, recording_id="recording_001", content=b"whole recorded answer", **fields):
        data = {"sessionId": self.session_id, "recordingId": recording_id, "language": "ja", **fields}
        with patch("api.routes.local_whisper.transcribe", return_value="温度を確認しました。オーバー。"):
            return self.client.post("/api/speech/transcribe", data=data,
                                    files={"audio": ("answer.webm", content, "audio/webm;codecs=opus")})

    def answer(self, recording_id="recording_001"):
        return self.client.post(self.path + "/messages", json={
            "maskedText": "温度を確認しました。", "inputMode": "voice", "recordingId": recording_id,
        })

    def document(self):
        return json.loads((session_directory(self.session_id) / "transcript.json").read_text(encoding="utf-8"))

    def test_full_recording_and_path_are_saved_and_manual_end_archives_conversation(self):
        upload = self.upload()
        self.assertEqual(upload.status_code, 200, upload.text)
        audio_file = upload.json()["audioFile"]
        self.assertEqual((session_directory(self.session_id) / audio_file).read_bytes(), b"whole recorded answer")
        self.assertEqual(self.answer().status_code, 200)
        response = self.client.post(self.path + "/end")
        self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual(response.json()["archive"]["status"], "ready")
        document = self.document()
        self.assertEqual(set(document), {"account_id", "user_name", "session_id", "messages"})
        self.assertEqual(document["account_id"], "admin")
        self.assertEqual(document["user_name"], "Administrator")
        self.assertEqual(document["session_id"], self.session_id)
        users = [m for m in document["messages"] if m["role"] == "user"]
        self.assertEqual(len(users), 1)
        self.assertEqual(users[0]["audio_file"], audio_file)
        with database() as db:
            recording = db.execute("SELECT * FROM interview_recordings").fetchone()
        self.assertEqual(recording["message_id"], users[0]["message_id"])
        self.assertTrue(all(set(m) == {"role", "message"} for m in document["messages"] if m["role"] == "system"))
        self.assertEqual(document["messages"][-1]["message"], response.json()["messages"][-1]["content"])
        self.client.post(self.path + "/end")
        self.assertEqual(self.document(), document)

    def test_automatic_end_archives_even_when_summary_generation_fails(self):
        self.upload()
        self.turn.return_value = {**self.turn.return_value, "stateLabel": "end", "text": "ありがとうございました。"}
        self.finalize.side_effect = RuntimeError("summary failed")
        response = self.answer()
        self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual(response.json()["archive"]["status"], "ready")
        self.assertEqual(self.document()["messages"][-1]["message"], "ありがとうございました。")
        self.assertIsNotNone(self.document()["messages"][1]["audio_file"])

    def test_preview_is_not_archived_and_text_answer_has_no_audio(self):
        with patch("api.routes.local_whisper.transcribe", return_value="オーバー"):
            response = self.client.post("/api/speech/transcribe", files={"audio": ("preview.wav", b"preview", "audio/wav")})
        self.assertEqual(response.status_code, 200)
        with database() as db:
            self.assertEqual(db.execute("SELECT COUNT(*) FROM interview_recordings").fetchone()[0], 0)
        self.assertFalse(archive_root().exists())
        self.client.post(self.path + "/messages", json={"maskedText": "テキスト回答"})
        self.client.post(self.path + "/end")
        self.assertIsNone(self.document()["messages"][1]["audio_file"])

    def test_duplicate_upload_and_answer_do_not_duplicate_records(self):
        self.assertEqual(self.upload().status_code, 200)
        self.assertEqual(self.upload().status_code, 200)
        self.assertEqual(self.upload(content=b"different audio").status_code, 409)
        self.assertEqual(self.answer().status_code, 200)
        self.assertEqual(self.answer().status_code, 200)
        self.turn.assert_awaited_once()
        with database() as db:
            self.assertEqual(db.execute("SELECT COUNT(*) FROM interview_recordings").fetchone()[0], 1)
            self.assertEqual(db.execute("SELECT COUNT(*) FROM messages WHERE role='user'").fetchone()[0], 1)

    def test_another_session_cannot_use_recording_and_other_operator_cannot_upload(self):
        self.upload()
        other = self.client.post("/api/sessions", json={}).json()["session"]["id"]
        response = self.client.post(f"/api/sessions/{other}/messages", json={
            "maskedText": "回答", "inputMode": "voice", "recordingId": "recording_001",
        })
        self.assertEqual(response.status_code, 400)
        self.client.post("/api/admin/accounts", json={"id": "other_operator", "displayName": "他の利用者"})
        self.login("other_operator", "")
        self.assertEqual(self.upload("other_recording").status_code, 404)

    def test_invalid_recording_ids_and_ended_uploads_are_rejected(self):
        self.assertEqual(self.upload("../escape").status_code, 400)
        self.assertEqual(self.upload("", sessionId=self.session_id).status_code, 400)
        self.client.post(self.path + "/end")
        self.assertEqual(self.upload().status_code, 409)

    def test_audio_survives_transcription_failure(self):
        with patch("api.routes.local_whisper.transcribe", side_effect=RuntimeError("recognition failed")):
            response = self.client.post("/api/speech/transcribe",
                data={"sessionId": self.session_id, "recordingId": "failed_recognition"},
                files={"audio": ("answer.ogg", b"saved before inference", "audio/ogg")})
        self.assertEqual(response.status_code, 502)
        with database() as db:
            row = db.execute("SELECT * FROM interview_recordings WHERE id='failed_recognition'").fetchone()
        self.assertIsNone(row["message_id"])
        self.assertEqual((session_directory(self.session_id) / row["audio_file"]).read_bytes(), b"saved before inference")

    def test_json_failure_remains_pending_and_is_recovered_without_models(self):
        with patch("db.archive.atomic_write", side_effect=OSError("disk unavailable")):
            response = self.client.post(self.path + "/end")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["archive"]["status"], "pending")
        self.assertIn("disk unavailable", response.json()["archive"]["last_error"])
        self.assertEqual(recover_archives(), 1)
        self.assertTrue(self.document()["messages"])
        self.assertEqual(recover_archives(), 0)
        (session_directory(self.session_id) / "transcript.json").unlink()
        self.assertEqual(recover_archives(), 1)

    def test_display_name_is_snapshotted_at_session_creation(self):
        with database() as db:
            db.execute("UPDATE accounts SET display_name='新しい名前' WHERE id='admin'")
        initialize_database()
        self.client.post(self.path + "/end")
        self.assertEqual(self.document()["user_name"], "Administrator")

    def test_export_simple_and_audio_bundle(self):
        self.upload()
        self.answer()
        self.client.post(self.path + "/end")
        simple = database_path().parent / "simple.json"
        bundle = database_path().parent / "bundle"
        with contextlib.redirect_stdout(io.StringIO()):
            interviews_command(["export", "--all", "--format", "simple", "--output", str(simple)])
            interviews_command(["export", "--session-id", self.session_id, "--format", "archive",
                                "--include-audio", "--output-dir", str(bundle)])
        document = json.loads(simple.read_text())[0]
        self.assertTrue(all(set(message) == {"role", "message"} for message in document["messages"]))
        copied = json.loads((bundle / self.session_id / "transcript.json").read_text())
        audio_file = copied["messages"][1]["audio_file"]
        self.assertEqual((bundle / self.session_id / audio_file).read_bytes(), b"whole recorded answer")
        with contextlib.redirect_stderr(io.StringIO()), self.assertRaises(SystemExit):
            interviews_command(["export", "--all", "--output", str(simple)])


class ExportCommandTests(DatabaseTestCase):
    def test_date_filter_uses_japan_calendar_day_and_includes_running_sessions(self):
        cases = [
            ("before", "2026-11-26T14:59:59Z", "ended"),
            ("start", "2026-11-26T15:00:00Z", "running"),
            ("last", "2026-11-27T14:59:59Z", "ended"),
            ("after", "2026-11-27T15:00:00Z", "ended"),
        ]
        for session_id, started_at, status in cases:
            self.add_session(session_id)
            with database() as db:
                db.execute("UPDATE interview_sessions SET started_at=?, status=? WHERE id=?", (started_at, status, session_id))
        output = database_path().parent / "today.json"
        with contextlib.redirect_stdout(io.StringIO()):
            interviews_command(["export", "--all", "--status", "all", "--date", "2026-11-27", "--output", str(output)])
        self.assertEqual({document["session_id"] for document in json.loads(output.read_text())}, {"start", "last"})

    def test_current_display_name_selects_only_that_accounts_full_history(self):
        with database() as db:
            db.execute("INSERT INTO accounts (id, role, display_name) VALUES ('mana_id', 'operator', '以前の名前')")
        ended = self.add_session("mana_ended", "mana_id")
        self.add_session("mana_running", "mana_id")
        self.add_session("someone_else")
        with database() as db:
            db.execute("UPDATE accounts SET display_name='Mana' WHERE id='mana_id'")
            db.execute("UPDATE interview_sessions SET status='ended' WHERE id=?", (ended,))
        root = database_path().parent / "exports"
        with patch("tools.interviews.EXPORT_ROOT", root), contextlib.redirect_stdout(io.StringIO()):
            interviews_command(["export", "--user-name", "Mana", "--status", "all"])
        documents = json.loads(next(root.glob("*.json")).read_text())
        self.assertEqual({document["session_id"] for document in documents}, {"mana_ended", "mana_running"})
        self.assertTrue(all(document["account_id"] == "mana_id" for document in documents))
        self.assertTrue(all(document["user_name"] == "以前の名前" for document in documents))
        with contextlib.redirect_stdout(io.StringIO()) as output:
            interviews_command(["list", "--display-name", "Mana"])
        self.assertEqual(len(json.loads(output.getvalue())), 2)

    def test_duplicate_display_names_require_account_id_without_creating_export(self):
        with database() as db:
            db.executemany("INSERT INTO accounts (id, role, display_name) VALUES (?, 'operator', 'Mana')",
                           [("mana_one",), ("mana_two",)])
        root = database_path().parent / "exports"
        with patch("tools.interviews.EXPORT_ROOT", root), contextlib.redirect_stderr(io.StringIO()) as errors:
            with self.assertRaises(SystemExit) as error:
                interviews_command(["export", "--user-name", "Mana"])
        self.assertEqual(error.exception.code, 2)
        self.assertIn("--account-id", errors.getvalue())
        self.assertIn("mana_one, mana_two", errors.getvalue())
        self.assertFalse(root.exists())

    def test_unknown_display_name_does_not_export_other_accounts(self):
        self.add_session()
        root = database_path().parent / "exports"
        with patch("tools.interviews.EXPORT_ROOT", root), contextlib.redirect_stderr(io.StringIO()) as errors:
            with self.assertRaises(SystemExit):
                interviews_command(["export", "--user-name", "Missing"])
        self.assertIn("アカウントがありません", errors.getvalue())
        self.assertFalse(root.exists())

    def test_default_output_creates_new_files_and_folders_on_every_export(self):
        session_id = self.add_session()
        with database() as db:
            insert_message(db, session_id, "user", "保存した回答", "text", "ja")
            db.execute("UPDATE interview_sessions SET status='ended' WHERE id=?", (session_id,))
        root = database_path().parent / "exports"
        with patch("tools.interviews.EXPORT_ROOT", root), contextlib.redirect_stdout(io.StringIO()) as output:
            for format_name in ("simple", "archive"):
                for _ in range(2):
                    interviews_command(["export", "--account-id", "admin", "--format", format_name])
        files = list(root.glob("*.json"))
        folders = [path for path in root.iterdir() if path.is_dir()]
        self.assertEqual(len(files), 2)
        self.assertEqual(len(folders), 2)
        for path in files:
            document = json.loads(path.read_text())[0]
            self.assertEqual(document["messages"], [{"role": "user", "message": "保存した回答"}])
            self.assertIn(str(path), output.getvalue())
        for folder in folders:
            self.assertTrue((folder / session_id / "transcript.json").is_file())
            self.assertIn(str(folder), output.getvalue())


class ArchiveMigrationTests(DatabaseTestCase):
    def test_failed_file_replace_does_not_register_audio_and_cleans_up(self):
        session_id = self.add_session()
        with patch("db.archive.os.replace", side_effect=OSError("disk unavailable")):
            with self.assertRaisesRegex(OSError, "disk unavailable"):
                save_recording(session_id, "recording_failed", b"audio", "answer.webm", "audio/webm")
        with database() as db:
            self.assertEqual(db.execute("SELECT COUNT(*) FROM interview_recordings").fetchone()[0], 0)
        self.assertEqual(list((session_directory(session_id) / "audio").iterdir()), [])

    def test_existing_database_is_migrated_repeatedly_without_losing_conversation(self):
        path = database_path().parent / "legacy.sqlite3"
        with contextlib.closing(sqlite3.connect(path)) as db:
            for migration in sorted(MIGRATIONS.glob("*.sql")):
                if migration.name < "0006":
                    db.executescript(migration.read_text())
            db.execute("INSERT INTO accounts (id, role, display_name) VALUES ('baba', 'operator', '馬場')")
            db.execute("INSERT INTO interview_sessions (id, account_id, title, status) VALUES ('legacy', 'baba', 'old', 'ended')")
            db.execute("INSERT INTO messages (id, session_id, role, content) VALUES ('old_message', 'legacy', 'user', '過去の回答')")
            db.commit()
        with patch.dict("os.environ", {"DATABASE_PATH": str(path)}):
            initialize_database()
            initialize_database()
            self.assertEqual(recover_archives(), 1)
            document = json.loads((session_directory("legacy") / "transcript.json").read_text())
            self.assertEqual(document["user_name"], "馬場")
            self.assertEqual(document["messages"], [{"message_id": "old_message", "role": "user", "message": "過去の回答", "audio_file": None}])
