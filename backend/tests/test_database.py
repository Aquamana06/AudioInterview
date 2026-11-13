import sqlite3

from backend_test_support import DatabaseTestCase, database, initialize_database
from db.database import get_state, insert_message, list_messages, public_message, update_state
from db.memory import empty_profile, load_participant_memory, save_session_memory


class DatabaseTests(DatabaseTestCase):
    def test_migrations_can_run_repeatedly_without_losing_records(self):
        self.add_session()
        initialize_database()
        with database() as connection:
            self.assertEqual(connection.execute("SELECT COUNT(*) FROM interview_sessions").fetchone()[0], 1)

    def test_transaction_rolls_back_on_error(self):
        with self.assertRaises(RuntimeError):
            with database() as connection:
                connection.execute("INSERT INTO accounts (id, role, display_name) VALUES ('rollback', 'operator', 'test')")
                raise RuntimeError("abort")
        with database() as connection:
            self.assertIsNone(connection.execute("SELECT id FROM accounts WHERE id='rollback'").fetchone())

    def test_message_requires_existing_session(self):
        with self.assertRaises(sqlite3.IntegrityError):
            with database() as connection:
                insert_message(connection, "missing", "user", "回答", "text", "ja")

    def test_messages_preserve_order_and_public_fields(self):
        session_id = self.add_session()
        with database() as connection:
            ids = [insert_message(connection, session_id, "user", text, "text", "ja", {"internal": True})
                   for text in ("最初", "次")]
            rows = list_messages(connection, session_id)
        self.assertEqual([row["id"] for row in rows], ids)
        public = public_message(rows[0])
        self.assertEqual(public["inputMode"], "text")
        self.assertIn("createdAt", public)
        self.assertNotIn("meta_json", public)

    def test_state_upsert_replaces_existing_snapshot(self):
        session_id = self.add_session()
        with database() as connection:
            self.assertIsNone(get_state(connection, session_id))
            update_state(connection, session_id, {"turn_count": 1}, "running")
            update_state(connection, session_id, {"turn_count": 2}, "end")
            self.assertEqual(get_state(connection, session_id), {"state": {"turn_count": 2}, "stateLabel": "end"})
            self.assertEqual(connection.execute("SELECT COUNT(*) FROM interview_states").fetchone()[0], 1)

    def test_memory_merges_profile_evidence_and_relations(self):
        session_id = self.add_session()
        update = {
            "summary": "設備を点検した",
            "profile_patch": {**empty_profile(), "role": "運転員", "responsibilities": ["点検"]},
            "nodes": [
                {"key": "practice", "kind": "adjustment", "text": "設備を確認", "confidence": 0.8,
                 "evidence_message_ids": ["msg_one"]},
                {"key": "reason", "kind": "reason", "text": "安全のため", "confidence": 0.7,
                 "evidence_message_ids": ["msg_one"]},
            ],
            "edges": [{"from_key": "practice", "to_key": "reason", "relation": "because",
                       "evidence_message_ids": ["msg_one"]}],
        }
        save_session_memory("admin", session_id, empty_profile(), update)
        memory = load_participant_memory("admin")
        update["nodes"][0]["evidence_message_ids"] = ["msg_one", "msg_two"]
        update["nodes"][0]["confidence"] = 0.2
        save_session_memory("admin", session_id, memory["profile"], update)
        memory = load_participant_memory("admin")
        self.assertEqual(memory["profile"]["responsibilities"], ["点検"])
        self.assertEqual(len(memory["nodes"]), 2)
        self.assertEqual(len(memory["edges"]), 1)
        node = next(node for node in memory["nodes"] if node["kind"] == "adjustment")
        self.assertEqual(node["evidence_message_ids"], ["msg_one", "msg_two"])
        self.assertEqual(node["confidence"], 0.8)
        self.assertEqual(len(memory["recent_summaries"]), 1)
