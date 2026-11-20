import asyncio
from unittest.mock import AsyncMock, patch

from fastapi.testclient import TestClient

from backend_test_support import DatabaseTestCase, app, database, initialize_database
from config import load_config
from api.routes import _run_turn
from db.database import insert_message, list_messages
from db.memory import empty_profile, finalize_session, load_participant_profile, save_session_memory
from interview.agent import empty_extraction, initial_state


class DomainKnowledgeTests(DatabaseTestCase):
    def learned_session(self, session_id="learned", meaning="カラフェとピッチャーを交換する作業"):
        self.add_session(session_id)
        with database() as connection:
            connection.execute("UPDATE interview_sessions SET status='ended', ended_at='2026-11-01T00:00:00Z' WHERE id=?",
                               (session_id,))
            system_id = insert_message(connection, session_id, "system", "全交換とは何ですか？", "system", "ja")
            user_id = insert_message(connection, session_id, "user", f"全交換は{meaning}です", "text", "ja")
        return {"term": "全交換", "meaning": meaning, "scope": "店舗業務", "evidence_message_ids": [user_id]}, system_id

    def save(self, session_id, entries):
        save_session_memory("admin", session_id, empty_profile(), {
            "summary": "用語について教わった。", "domain_knowledge": entries, "nodes": [], "edges": [],
        })

    def test_finalization_persists_definitions_for_startup_and_survives_database_reinitialization(self):
        entry, _ = self.learned_session()
        with database() as connection:
            messages = list_messages(connection, "learned")
        update = {"summary": "全交換について説明した。", "profile_patch": {},
                  "nodes": [], "edges": [], "domain_knowledge": [entry]}
        with patch("db.memory.configured", return_value=True), \
             patch("db.memory.complete_json", AsyncMock(return_value=update)) as generate:
            asyncio.run(finalize_session("admin", "learned", "ja", messages))
        initialize_database()
        participant = load_participant_profile("admin")
        self.assertEqual(participant["domain_knowledge"], [{
            "term": entry["term"], "meaning": entry["meaning"], "scope": entry["scope"], "source_session_id": "learned",
        }])
        self.assertIn("domain_knowledge", generate.call_args.args[1]["required"])
        self.assertNotIn("messages", participant)
        self.assertNotIn("recent_summaries", participant)

    def test_only_current_respondent_evidence_is_saved_and_other_accounts_do_not_receive_it(self):
        entry, system_id = self.learned_session()
        other_entry, _ = self.learned_session("other_session")
        entries = [
            {**entry, "term": "聞き手だけの推測", "evidence_message_ids": [system_id]},
            {**entry, "term": "別のセッション", "evidence_message_ids": other_entry["evidence_message_ids"]},
            {**entry, "term": "出典不明", "evidence_message_ids": []},
            entry,
        ]
        self.save("learned", entries)
        self.assertEqual([item["term"] for item in load_participant_profile("admin")["domain_knowledge"]], ["全交換"])
        with database() as connection:
            connection.execute("INSERT INTO accounts (id,role,display_name) VALUES ('other','operator','別の参加者')")
        self.assertEqual(load_participant_profile("other")["domain_knowledge"], [])

    def test_correction_replaces_same_definition_and_keeps_other_terms(self):
        entry, _ = self.learned_session()
        self.save("learned", [entry, {**entry, "term": "バー", "meaning": "ドリンクを作る場所"}])
        corrected, _ = self.learned_session("corrected", "カラフェをすべて交換する作業")
        self.save("corrected", [corrected])
        # Re-running finalization must not duplicate entries.
        self.save("corrected", [corrected])
        entries = {item["term"]: item for item in load_participant_profile("admin")["domain_knowledge"]}
        self.assertEqual(len(entries), 2)
        self.assertEqual(entries["全交換"]["meaning"], corrected["meaning"])
        self.assertEqual(entries["全交換"]["source_session_id"], "corrected")
        self.assertEqual(entries["バー"]["source_session_id"], "learned")

    def test_start_passes_learned_vocabulary_before_task_search(self):
        entry, _ = self.learned_session()
        self.save("learned", [entry])
        with TestClient(app) as client:
            client.post("/api/auth/login", json={"id": "admin", "password": "admin"})
            session_id = client.post("/api/sessions", json={}).json()["session"]["id"]
            with patch("api.routes.longitudinal_starter", AsyncMock(return_value="先ほどは何をしていましたか？")) as starter, \
                 patch("api.routes.load_task_memory", side_effect=AssertionError("No task yet")), \
                 patch("db.memory.load_participant_memory", side_effect=AssertionError("Do not load past conversations")):
                response = client.post(f"/api/sessions/{session_id}/start")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(starter.call_args.kwargs["domain_knowledge"][0]["meaning"], entry["meaning"])

    def test_vocabulary_reaches_questions_without_matching_task_history_and_does_not_add_scores(self):
        entry, _ = self.learned_session()
        self.save("learned", [entry])
        memory = load_participant_profile("admin")
        phases = [(None, 0, 0), ("別の業務", 0, 0), ("別の業務", 0.5, 3), ("別の業務", 0.5, 5)]
        for target, coverage, depth in phases:
            with self.subTest(target=target, depth=depth):
                state = initial_state()
                state.update(target_work=target, task_coverage=coverage, task_depth=depth)
                if coverage:
                    state["task_coverage_by_fram"] = {key: 0.05 for key in state["task_coverage_by_fram"]}
                    scoring = load_config("interview")["scoring"]
                    coverage = round(0.3 + max(bonus for count, bonus in scoring["fram_bonuses"].items() if count <= 6), 2)
                    state["task_coverage"] = coverage
                with patch("api.routes.extract_turn", AsyncMock(return_value=empty_extraction())), \
                     patch("interview.agent.configured", return_value=True), \
                     patch("interview.agent.complete", AsyncMock(return_value="そのときは何を使いましたか？")) as generate:
                    result = asyncio.run(_run_turn(state, "そうですね", [], "ja", memory, session_id="new"))
                prompt = generate.call_args.args[0]
                self.assertIn(entry["meaning"], prompt)
                self.assertIn("説明済みの用語の意味は聞き直さず", prompt)
                self.assertEqual(result["state"]["task_coverage"], coverage)
                self.assertEqual(result["state"]["task_depth"], max(1 if target else 0, depth))
                self.assertEqual(result["state"]["known_facts"], [])
                self.assertEqual(result["state"]["irregular_coverage"], 0)
