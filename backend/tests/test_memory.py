import asyncio
from unittest.mock import AsyncMock, call, patch

from backend_test_support import DatabaseTestCase, database
from db.database import insert_message, list_messages
from db.memory import (CONFIG, empty_profile, ensure_session_memory, finalize_session, get_session_memory,
                       load_participant_memory, recover_session_memories, run_memory_recovery, save_session_memory)
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
        fallback = self.ended_session("fallback")
        with patch("db.memory.configured", return_value=False):
            asyncio.run(finalize_session("admin", "fallback", "ja", fallback))

        async def recovered_summary(*args):
            self.assertEqual(self.record("fallback")["status"], "fallback")
            return {"summary": "復旧した要約", "nodes": [], "edges": []}

        with patch("db.memory.configured", return_value=True), \
             patch("db.memory.complete_json", AsyncMock(side_effect=recovered_summary)) as generate:
            asyncio.run(recover_session_memories())
        self.assertEqual(generate.await_count, 3)
        self.assertEqual(self.record("pending")["status"], "ready")
        self.assertEqual(self.record("missing")["summary"], "復旧した要約")
        self.assertEqual(self.record("ready")["summary"], "保存済み")
        self.assertIsNone(self.record("running")["summary"])
        self.assertEqual(self.record("fallback")["status"], "ready")

    def test_failed_summary_is_retried_without_restart_and_uses_a_shorter_prompt(self):
        messages = self.ended_session()
        update = {"summary": "復旧した要約", "profile_patch": {"role": "設備担当"}, "nodes": [], "edges": []}
        with patch("db.memory.configured", return_value=True), \
             patch("db.memory.complete_json", AsyncMock(side_effect=[RuntimeError("invalid JSON"), update])) as generate, \
             self.assertLogs("audiointerview", level="INFO"):
            asyncio.run(finalize_session("admin", "memory_test", "ja", messages))
            self.assertEqual(self.record()["status"], "fallback")
            with database() as connection:
                connection.execute("UPDATE session_memory_jobs SET updated_at='2000-01-01T00:00:00Z'")
            asyncio.run(recover_session_memories(retry_only=True))
        self.assertEqual(generate.await_count, 2)
        self.assertIn("300字", generate.call_args_list[0].args[0])
        self.assertIn("150字", generate.call_args_list[1].args[0])
        self.assertEqual(self.record(), {"summary": "復旧した要約", "status": "ready"})
        self.assertEqual(load_participant_memory("admin")["profile"]["role"], "設備担当")
        with database() as connection:
            self.assertEqual(list_messages(connection, "memory_test"), messages)

    def test_periodic_recovery_waits_for_delay_and_processes_a_bounded_batch(self):
        for session_id in ("oldest", "recent_failure", "newer", "ready"):
            messages = self.ended_session(session_id)
            ensure_session_memory("admin", session_id, messages)
        with database() as connection:
            connection.execute("UPDATE session_memory_jobs SET status='fallback'")
            connection.execute("UPDATE session_memory_jobs SET updated_at='2000-01-01T00:00:00Z' WHERE session_id='oldest'")
            connection.execute("UPDATE session_memory_jobs SET updated_at='2001-01-01T00:00:00Z' WHERE session_id='newer'")
            connection.execute("UPDATE session_memory_jobs SET status='ready' WHERE session_id='ready'")

        async def summarize(prompt, schema):
            self.assertEqual(self.record("oldest")["status"], "fallback")
            # A background retry must not block the next interview.
            from api.routes import _require_memory_complete
            _require_memory_complete("admin")
            return {"summary": "復旧", "nodes": [], "edges": []}

        with patch("db.memory.configured", return_value=True), \
             patch("db.memory.complete_json", AsyncMock(side_effect=summarize)) as generate:
            asyncio.run(recover_session_memories(retry_only=True))
        generate.assert_awaited_once()
        self.assertEqual(self.record("oldest")["status"], "ready")
        self.assertEqual(self.record("newer")["status"], "fallback")
        self.assertEqual(self.record("recent_failure")["status"], "fallback")

    def test_concurrent_finalization_of_the_same_session_runs_once(self):
        messages = self.ended_session()

        async def scenario():
            started, release = asyncio.Event(), asyncio.Event()

            async def summarize(*args):
                started.set()
                await release.wait()
                return {"summary": "一度だけ生成", "nodes": [], "edges": []}

            with patch("db.memory.configured", return_value=True), \
                 patch("db.memory.complete_json", AsyncMock(side_effect=summarize)) as generate:
                task = asyncio.create_task(finalize_session("admin", "memory_test", "ja", messages))
                await started.wait()
                try:
                    await finalize_session("admin", "memory_test", "ja", messages)
                    generate.assert_awaited_once()
                finally:
                    release.set()
                    await task
                # A completed job must also remain untouched by later retry calls.
                await finalize_session("admin", "memory_test", "ja", messages)
                generate.assert_awaited_once()

        asyncio.run(scenario())
        self.assertEqual(self.record()["status"], "ready")

    def test_recovery_worker_keeps_running_after_a_queue_error_and_can_be_cancelled(self):
        with patch.dict(CONFIG, {"recovery_enabled": True}), \
             patch("db.memory.recover_session_memories", AsyncMock(side_effect=[RuntimeError("database busy"), None])) as recover, \
             patch("db.memory.asyncio.sleep", AsyncMock(side_effect=[None, asyncio.CancelledError])) as sleep, \
             self.assertLogs("audiointerview", level="ERROR"):
            with self.assertRaises(asyncio.CancelledError):
                asyncio.run(run_memory_recovery())
        self.assertEqual(recover.await_args_list, [call(retry_only=False), call(retry_only=True)])
        self.assertEqual(sleep.await_count, 2)

    def test_disabled_recovery_does_not_run_at_startup_or_schedule_periodic_retries(self):
        with patch.dict(CONFIG, {"recovery_enabled": False}), \
             patch("db.memory.recover_session_memories", AsyncMock()) as recover, \
             patch("db.memory.asyncio.sleep", AsyncMock()) as sleep:
            # Starting the backend again must not restart the stopped recovery.
            asyncio.run(run_memory_recovery())
            asyncio.run(run_memory_recovery())
        recover.assert_not_awaited()
        sleep.assert_not_awaited()

    def test_unexpected_recovery_failure_preserves_record_and_releases_pending_state(self):
        self.ended_session()
        with patch("db.memory.finalize_session", AsyncMock(side_effect=RuntimeError("summary failed"))), \
             self.assertLogs("audiointerview", level="ERROR"):
            asyncio.run(recover_session_memories())
        self.assertEqual(self.record()["status"], "fallback")
        self.assertIn("ダスターを交換しました", self.record()["summary"])

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
