import asyncio
from unittest.mock import AsyncMock, patch

from backend_test_support import DatabaseTestCase, database
from db.database import insert_message, list_messages
from db.memory import (empty_profile, ensure_session_memory, finalize_session, get_session_memory,
                       load_participant_memory, recover_session_memories, save_session_memory)
from interview.longitudinal import select_relevant


class MemoryTests(DatabaseTestCase):
    def ended_session(self, session_id="memory_test"):
        self.add_session(session_id)
        with database() as connection:
            connection.execute("UPDATE interview_sessions SET status='ended', ended_at='2026-11-01T00:00:00Z' WHERE id=?", (session_id,))
            insert_message(connection, session_id, "system", "作り物の理由", "system", "ja")
            insert_message(connection, session_id, "user", "ダスターを交換しました", "text", "ja")
            return list_messages(connection, session_id)

    def record(self, session_id="memory_test"):
        with database() as connection:
            return get_session_memory(connection, session_id)

    def test_generation_failure_preserves_verbatim_answers_and_next_session_can_retrieve_them(self):
        messages = self.ended_session()
        with patch("db.memory.configured", return_value=True), \
             patch("db.memory.complete_json", AsyncMock(side_effect=RuntimeError("invalid JSON"))), \
             self.assertLogs("audiointerview", level="INFO"):
            asyncio.run(finalize_session("admin", "memory_test", "ja", messages))
        record = self.record()
        self.assertEqual(record["status"], "fallback")
        self.assertIn("ダスターを交換しました", record["summary"])
        self.assertNotIn("作り物の理由", record["summary"])
        selected = select_relevant(load_participant_memory("admin"), "ダスター交換をしていました")
        self.assertEqual(selected["summaries"][0]["session_id"], "memory_test")

    def test_success_replaces_excerpts_and_marks_ready_in_same_transaction(self):
        messages = self.ended_session()
        ensure_session_memory("admin", "memory_test", messages)
        self.assertEqual(self.record()["status"], "pending")
        update = {"summary": "ダスターを交換した。", "profile_patch": {}, "nodes": [], "edges": []}
        with patch("db.memory.configured", return_value=True), \
             patch("db.memory.complete_json", AsyncMock(return_value=update)):
            asyncio.run(finalize_session("admin", "memory_test", "ja", messages))
        self.assertEqual(self.record(), {"summary": update["summary"], "status": "ready"})
        with database() as connection:
            row = connection.execute("SELECT ended_at FROM longitudinal_session_summaries").fetchone()
        self.assertEqual(row["ended_at"], "2026-11-01T00:00:00Z")

    def test_legacy_empty_summary_is_replaced_even_without_model(self):
        messages = self.ended_session()
        save_session_memory("admin", "memory_test", empty_profile(), {"summary": "", "nodes": [], "edges": []})
        with patch("db.memory.configured", return_value=False):
            asyncio.run(finalize_session("admin", "memory_test", "ja", messages))
        self.assertEqual(self.record()["status"], "fallback")
        self.assertIn("ダスターを交換しました", self.record()["summary"])

    def test_invalid_memory_update_rolls_back_without_losing_excerpts(self):
        messages = self.ended_session()
        for update in ({"summary": ""}, {"summary": "要約", "nodes": [None]}):
            with self.subTest(update=update), patch("db.memory.configured", return_value=True), \
                 patch("db.memory.complete_json", AsyncMock(return_value=update)), \
                 self.assertLogs("audiointerview", level="INFO"):
                asyncio.run(finalize_session("admin", "memory_test", "ja", messages))
            self.assertEqual(self.record()["status"], "fallback")
            self.assertIn("ダスターを交換しました", self.record()["summary"])

    def test_recovery_resumes_pending_and_missing_memories_but_keeps_ready_and_running_sessions(self):
        pending = self.ended_session("pending")
        ensure_session_memory("admin", "pending", pending)
        self.ended_session("missing")
        self.ended_session("ready")
        save_session_memory("admin", "ready", empty_profile(), {"summary": "保存済み", "nodes": [], "edges": []})
        self.add_session("running")
        with patch("db.memory.configured", return_value=True), \
             patch("db.memory.complete_json", AsyncMock(return_value={"summary": "復旧した要約", "nodes": [], "edges": []})) as generate:
            asyncio.run(recover_session_memories())
        self.assertEqual(generate.await_count, 2)
        self.assertEqual(self.record("pending")["status"], "ready")
        self.assertEqual(self.record("missing")["summary"], "復旧した要約")
        self.assertEqual(self.record("ready")["summary"], "保存済み")
        self.assertIsNone(self.record("running")["summary"])

    def test_japanese_retrieval_ignores_particles_and_does_not_match_polite_endings_alone(self):
        memory = {"recent_summaries": [
            {"session_id": "duster", "summary": "ダスターの交換は2時間おきです"},
            {"session_id": "unrelated", "summary": "会議をしていました"},
        ], "nodes": [{"id": "node", "text": "ダスターを交換する", "confidence": 0.8}]}
        for text in ("ダスター交換をしていました", "ダスターの交換をしていました", "ﾀﾞｽﾀｰ交換です"):
            with self.subTest(text=text):
                result = select_relevant(memory, text)
                self.assertEqual([item["session_id"] for item in result["summaries"]], ["duster"])
                self.assertEqual(len(result["nodes"]), 1)
        self.assertEqual(select_relevant(memory, "そうしていました")["summaries"], [])
