from copy import deepcopy
from unittest.mock import AsyncMock, patch

from fastapi.testclient import TestClient

from backend_test_support import DatabaseTestCase, app, database
from interview.agent import initial_state


class APITests(DatabaseTestCase):
    def setUp(self):
        super().setUp()
        self.client = self.enterContext(TestClient(app))
        # Unexpected model calls fail immediately rather than using the network.
        self.starter = self.enterContext(patch("api.routes.profile_starter", new_callable=AsyncMock))
        self.starter.return_value = "担当している業務について教えてください。"
        self.finalize = self.enterContext(patch("api.routes.finalize_session", new_callable=AsyncMock))

    def login(self, account_id="admin", password="admin"):
        response = self.client.post("/api/auth/login", json={"id": account_id, "password": password})
        self.assertEqual(response.status_code, 200, response.text)
        return response

    def operator(self, account_id):
        response = self.client.post("/api/admin/accounts", json={"id": account_id, "displayName": account_id})
        self.assertEqual(response.status_code, 201, response.text)
        return response.json()

    def session(self, language="ja"):
        response = self.client.post("/api/sessions", json={"language": language})
        self.assertEqual(response.status_code, 201, response.text)
        return response.json()["session"]["id"]

    async def generated_turn(self, state, user_input, history, language, known_profile, *, domain_knowledge=None):
        state = deepcopy(state)
        state["turn_count"] += 1
        return {"text": f"回答を受け取りました: {user_input}", "state": state,
                "stateLabel": "running", "extracted": {}, "guide": {}}

    def test_health_is_public_but_sessions_require_authentication(self):
        self.assertEqual(self.client.get("/health").json()["status"], "ok")
        response = self.client.get("/api/sessions")
        self.assertEqual(response.status_code, 401)
        self.assertEqual(response.json(), {"error": "Authentication required"})

    def test_admin_login_checks_password_and_sets_http_only_cookie(self):
        response = self.client.post("/api/auth/login", json={"id": "admin", "password": "wrong"})
        self.assertEqual(response.status_code, 401)
        response = self.login()
        self.assertIn("HttpOnly", response.headers["set-cookie"])
        self.assertEqual(self.client.get("/api/me").json()["account"]["role"], "admin")
        self.assertNotIn("password_hash", response.json()["account"])

    def test_logout_revokes_server_side_session(self):
        token = self.login().json()["token"]
        self.assertEqual(self.client.post("/api/auth/logout").status_code, 200)
        response = self.client.get("/api/me", headers={"Authorization": f"Bearer {token}"})
        self.assertEqual(response.status_code, 401)

    def test_expired_token_is_rejected(self):
        token = self.login().json()["token"]
        with database() as connection:
            connection.execute("UPDATE auth_sessions SET expires_at='2000-01-01T00:00:00Z' WHERE token=?", (token,))
        self.assertEqual(self.client.get("/api/me").status_code, 401)

    def test_password_change_rejects_old_password(self):
        self.login()
        self.assertEqual(self.client.put("/api/me/password", json={"password": "short"}).status_code, 400)
        self.assertEqual(self.client.put("/api/me/password", json={"password": "new-secret"}).status_code, 200)
        self.client.post("/api/auth/logout")
        self.assertEqual(self.client.post("/api/auth/login", json={"id": "admin", "password": "admin"}).status_code, 401)
        self.login(password="new-secret")

    def test_operator_qr_login_and_admin_authorization(self):
        self.login()
        issued = self.operator("operator_one")
        self.client.post("/api/auth/logout")
        response = self.client.post("/api/auth/login", json={"qrToken": issued["qrToken"]})
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["account"]["id"], "operator_one")
        self.assertEqual(self.client.get("/api/admin/accounts").status_code, 403)
        self.assertEqual(self.client.put("/api/me/password", json={"password": "new-secret"}).status_code, 403)

    def test_session_ownership_and_admin_visibility(self):
        self.login()
        self.operator("operator_one")
        self.operator("operator_two")
        self.login("operator_one", "")
        session_id = self.session()
        self.login("operator_two", "")
        self.assertEqual(self.client.get(f"/api/sessions/{session_id}").status_code, 404)
        self.assertEqual(self.client.get("/api/sessions").json()["sessions"], [])
        self.login()
        self.assertEqual(self.client.get(f"/api/sessions/{session_id}").status_code, 200)
        self.assertEqual(len(self.client.get("/api/admin/histories").json()["histories"]), 1)

    def test_deactivated_account_loses_access_and_can_be_reissued(self):
        self.login()
        self.operator("operator_one")
        token = self.login("operator_one", "").json()["token"]
        self.login()
        self.assertEqual(self.client.delete("/api/admin/accounts/operator_one").status_code, 200)
        self.assertEqual(self.client.get("/api/me", headers={"Authorization": f"Bearer {token}"}).status_code, 401)
        self.assertEqual(self.client.post("/api/auth/login", json={"id": "operator_one"}).status_code, 401)
        self.operator("operator_one")
        self.login("operator_one", "")

    def test_start_message_and_end_are_persisted(self):
        self.login()
        session_id = self.session()
        path = f"/api/sessions/{session_id}"
        self.client.post(path + "/start")
        self.assertEqual(len(self.client.post(path + "/start").json()["messages"]), 1)
        self.starter.assert_awaited_once()
        with patch("api.routes.run_profile_turn", side_effect=self.generated_turn):
            response = self.client.post(path + "/messages", json={"maskedText": "設備を確認しました", "inputMode": "voice"})
        self.assertEqual(response.status_code, 200, response.text)
        payload = self.client.get(path).json()
        self.assertEqual(payload["state"]["turn_count"], 1)
        self.assertEqual([m["role"] for m in payload["messages"]], ["system", "user", "system"])
        self.assertEqual(payload["messages"][1]["inputMode"], "voice")
        ended = self.client.post(path + "/end").json()
        repeated = self.client.post(path + "/end").json()
        self.assertEqual(ended["session"]["status"], "ended")
        self.assertEqual(len(ended["messages"]), len(repeated["messages"]))
        self.finalize.assert_awaited_once()
        self.assertEqual(self.client.post(path + "/messages", json={"maskedText": "続き"}).status_code, 409)

    def test_pending_memory_blocks_creation_and_opening_until_recorded(self):
        self.login()
        ended_id = self.session()
        waiting_id = self.session()
        self.client.post(f"/api/sessions/{ended_id}/end")
        details = self.client.get(f"/api/sessions/{ended_id}").json()
        self.assertEqual(details["memory"]["status"], "pending")
        self.assertTrue(details["memory"]["summary"])
        listing = self.client.get("/api/sessions").json()["sessions"]
        self.assertEqual(next(item for item in listing if item["id"] == ended_id)["memory_status"], "pending")
        response = self.client.post("/api/sessions", json={"language": "ja"})
        self.assertEqual(response.status_code, 409)
        self.assertIn("記録しています", response.json()["error"])
        self.assertEqual(self.client.post(f"/api/sessions/{waiting_id}/start").status_code, 409)
        self.starter.assert_not_awaited()
        self.assertEqual(len(self.client.get("/api/sessions").json()["sessions"]), 2)
        for status in ("ready", "fallback"):
            with self.subTest(status=status):
                with database() as connection:
                    connection.execute("UPDATE session_memory_jobs SET status=? WHERE session_id=?", (status, ended_id))
                self.assertEqual(self.client.get(f"/api/sessions/{ended_id}").json()["memory"]["status"], status)
                self.session()
        with patch("api.routes.longitudinal_starter", AsyncMock(return_value="前回の続きについて教えてください。")):
            self.assertEqual(self.client.post(f"/api/sessions/{waiting_id}/start").status_code, 200)

    def test_another_accounts_pending_memory_does_not_block_creation(self):
        self.login()
        self.operator("operator_one")
        self.login("operator_one", "")
        ended_id = self.session()
        self.client.post(f"/api/sessions/{ended_id}/end")
        self.login()
        self.session()

    def test_unexpected_finalization_failure_releases_pending_state(self):
        self.login()
        session_id = self.session()
        self.finalize.side_effect = RuntimeError("summary failed")
        self.assertEqual(self.client.post(f"/api/sessions/{session_id}/end").status_code, 200)
        memory = self.client.get(f"/api/sessions/{session_id}").json()["memory"]
        self.assertEqual(memory["status"], "fallback")
        self.assertTrue(memory["summary"])
        self.session()

    def test_edit_replays_history_and_discards_later_turns(self):
        self.login()
        path = f"/api/sessions/{self.session()}"
        self.client.post(path + "/start")
        with patch("api.routes.run_profile_turn", side_effect=self.generated_turn):
            first = self.client.post(path + "/messages", json={"maskedText": "一回目の回答"}).json()
            edit_id = first["messages"][1]["id"]
            self.client.post(path + "/messages", json={"maskedText": "後続の回答"})
            response = self.client.post(path + "/messages", json={"maskedText": "修正後の回答", "editMessageId": edit_id})
        self.assertEqual(response.status_code, 200, response.text)
        payload = response.json()
        self.assertEqual(payload["state"]["turn_count"], 1)
        self.assertEqual([m["content"] for m in payload["messages"] if m["role"] == "user"], ["修正後の回答"])

    def test_invalid_json_and_empty_answer_return_client_errors(self):
        self.login()
        path = f"/api/sessions/{self.session()}"
        self.assertEqual(self.client.post(path + "/messages", json={"maskedText": " "}).status_code, 400)
        response = self.client.post("/api/sessions", content="{", headers={"content-type": "application/json"})
        self.assertEqual(response.status_code, 422)
        self.assertIn("error", response.json())

    def test_masking_and_local_audio_upload(self):
        self.login()
        self.assertEqual(self.client.post("/api/local/mask-text", json={"text": "塩酸を使用"}).json()["maskedText"], "薬品Aを使用")
        with patch("api.routes.local_whisper.transcribe", return_value="塩酸を確認") as transcribe:
            response = self.client.post("/api/speech/transcribe", files={"audio": ("sample.webm", b"audio", "audio/webm")},
                                        data={"language": "ja"})
        self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual(response.json()["maskedText"], "薬品Aを確認")
        transcribe.assert_called_once_with(b"audio", "sample.webm", "ja")
        self.assertEqual(self.client.post("/api/speech/transcribe").status_code, 400)

    def test_local_transcribe_uses_local_whisper(self):
        self.login()
        with patch("api.routes.local_whisper.transcribe", return_value="塩酸を確認") as transcribe:
            response = self.client.post("/api/local/transcribe", files={"file": ("sample.webm", b"audio", "audio/webm")},
                                        data={"language": "ja"})
        self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual(response.json()["maskedText"], "薬品Aを確認")
        transcribe.assert_called_once_with(b"audio", "sample.webm", "ja")

    def test_speech_corrects_tower_context_without_changing_raw_transcript_or_numbers(self):
        self.login()
        raw = "15等の温度は15度です。オーバー。"
        with patch("api.routes.local_whisper.transcribe", return_value=raw):
            response = self.client.post("/api/speech/transcribe", files={"audio": ("sample.webm", b"audio", "audio/webm")})
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["rawText"], raw)
        self.assertEqual(response.json()["normalizedText"], "重合塔の温度は15度です。")
        self.assertEqual(response.json()["maskedText"], "重合塔の温度は15度です。")
        self.assertTrue(response.json()["endOfTurn"])

    def test_speech_endpoint_detects_and_removes_end_command_on_server(self):
        self.login()
        for text, expected, ended in [
            ("塩酸を確認。オーバー。", "薬品Aを確認。", True),
            ("inspection complete, over!", "inspection complete,", True),
            ("coverage is sufficient", "coverage is sufficient", False),
            ("オーバー", "", True),
            ("塩酸を確認。オーバー，", "薬品Aを確認。", True),
            ("塩酸を確認。おば、", "薬品Aを確認。", True),
            ("塩酸を確認。おばー。", "薬品Aを確認。", True),
            ("塩酸を確認。ｵｰﾊﾞｰ…", "薬品Aを確認。", True),
            ("オーバーフローを確認", "オーバーフローを確認", False),
        ]:
            with self.subTest(text=text), patch("api.routes.local_whisper.transcribe", return_value=text):
                response = self.client.post("/api/speech/transcribe", files={"audio": ("recording.wav", b"audio", "audio/wav")})
                self.assertEqual(response.status_code, 200, response.text)
                self.assertEqual(response.json()["rawText"], text)
                self.assertEqual(response.json()["maskedText"], expected)
                self.assertEqual(response.json()["endOfTurn"], ended)
