import asyncio
from contextlib import contextmanager
from copy import deepcopy
import json
import sqlite3
from unittest.mock import AsyncMock, patch

from fastapi.testclient import TestClient

from backend_test_support import DatabaseTestCase, app, database, irregular_evidence
from api.routes import _run_turn
from db.database import insert_message, update_state
from db.memory import empty_profile, load_participant_memory, load_participant_profile, load_task_memory, save_session_memory
from interview.agent import empty_extraction, initial_state, run_interview_turn
from interview.longitudinal import task_match_score


class TaskMemoryTests(DatabaseTestCase):
    def history(self, session_id, work, summary, *, account_id="admin", ended_at="2026-01-01T00:00:00Z"):
        self.add_session(session_id, account_id)
        state = initial_state()
        state.update(target_work=work, task_depth=6, task_coverage=1, high_depth_turn_count=10)
        state["known_facts"] = ["FRAM time: 2時間おきに交換", "理由: 次のシフトへの配慮"]
        with database() as connection:
            connection.execute("UPDATE interview_sessions SET status='ended', ended_at=? WHERE id=?", (ended_at, session_id))
            update_state(connection, session_id, state, "end")
            insert_message(connection, session_id, "system", "交換はどのくらいの間隔ですか？", "system", "ja")
            insert_message(connection, session_id, "user", "2時間おきに交換しています", "text", "ja")
        save_session_memory(account_id, session_id, empty_profile(), {
            "summary": summary, "nodes": [{"key": session_id, "kind": "practice", "text": summary}], "edges": [],
        })

    def test_all_past_sessions_are_searchable_by_task_and_other_tasks_and_accounts_are_excluded(self):
        self.history("old_duster", "ダスターの交換", "ダスターを2時間おきに交換する")
        for i in range(7):
            self.history(f"new_filter_{i}", "フィルター交換", "フィルター交換でダスターも使う",
                         ended_at=f"2026-02-{i + 1:02}T00:00:00Z")
        with database() as connection:
            connection.execute("INSERT INTO accounts (id,role,display_name) VALUES ('other','operator','別の参加者')")
        self.history("other_duster", "ダスター交換", "別の参加者のダスター交換", account_id="other")
        memory = load_participant_memory("admin")
        self.assertNotIn("old_duster", [row["session_id"] for row in memory["recent_summaries"]])
        result = load_task_memory("admin", "ダスター交換", exclude_session_id="current", profile=memory["profile"])
        self.assertEqual([row["session_id"] for row in result["sessions"]], ["old_duster"])
        self.assertNotIn("messages", result["sessions"][0])
        self.assertIn("FRAM time: 2時間おきに交換", result["sessions"][0]["info"]["known_facts"])
        self.assertEqual([node["text"] for node in result["nodes"]], ["ダスターを2時間おきに交換する"])
        excluded = load_task_memory("admin", "ダスター交換", exclude_session_id="old_duster", profile={})
        self.assertEqual(excluded["sessions"], [])

    def test_first_answer_is_extracted_once_before_same_task_history_reaches_question_generation(self):
        self.history("past", "ダスターの交換", "2時間おきに交換する。次のシフトへの配慮。")
        memory = load_participant_profile("admin")
        self.assertNotIn("recent_summaries", memory)
        self.assertNotIn("nodes", memory)
        extracted = {**empty_extraction(), "target_work": "ダスター交換"}
        state = initial_state()
        expected = "今回のダスター交換では、いつもと違うことはありましたか？"
        with patch("api.routes.extract_turn", AsyncMock(return_value=extracted)) as extract, \
             patch("interview.agent.extract_turn", AsyncMock(side_effect=AssertionError("duplicate extraction"))), \
             patch("interview.agent.configured", return_value=True), \
             patch("interview.agent.complete", AsyncMock(return_value=expected)) as generate:
            result = asyncio.run(_run_turn(state, "さっきはあの布を取り替えていました", [], "ja", memory, session_id="new"))
        extract.assert_awaited_once()
        prompt = generate.call_args.args[0]
        self.assertIn('"session_id": "past"', prompt)
        self.assertNotIn("交換はどのくらいの間隔ですか？", prompt)
        self.assertNotIn("2時間おきに交換しています", prompt)
        self.assertIn("FRAM time: 2時間おきに交換", prompt)
        self.assertIn("過去の情報を質問文に入れる必要はありません", prompt)
        self.assertIn("まず今回いつもと違うこと", result["guide"]["guidance"])
        self.assertNotIn("fram_focus", result["guide"])
        self.assertTrue(result["guide"]["past_memory_used"])
        self.assertEqual(result["text"], expected)
        self.assertEqual(result["state"]["task_coverage"], 0)
        self.assertEqual(result["state"]["task_depth"], 1)
        self.assertEqual(result["state"]["high_depth_turn_count"], 0)
        self.assertNotIn("2時間おきに交換しています", result["state"]["known_facts"])

    def test_same_task_checks_variation_then_returns_to_normal_coverage_when_the_answer_is_usual(self):
        self.history("past", "ダスター交換", "2時間おきに交換する")
        memory = load_task_memory("admin", "ダスター交換", exclude_session_id="new", profile={})
        with patch("interview.agent.configured", return_value=False):
            first = asyncio.run(run_interview_turn(initial_state(), "ダスター交換です", [], "ja",
                                                  extracted={**empty_extraction(), "target_work": "ダスター交換"}, task_memory=memory))
            self.assertIn("いつもと違うこと", first["text"])
            self.assertEqual(first["state"]["task_revisit_work"], "ダスター交換")
            second = asyncio.run(run_interview_turn(first["state"], "いつも通りです", [], "ja",
                                                   extracted={**empty_extraction(), "usual_work": True}, task_memory=memory))
            self.assertEqual(second["guide"]["fram_focus"], "input")
            self.assertNotIn("2時間おき", second["text"])
            self.assertNotIn("いつもと違うこと", second["text"])
            self.assertEqual(second["state"]["task_coverage_by_fram"]["time"], 0)
            self.assertEqual(second["state"]["irregular_coverage"], 0)
            third = asyncio.run(run_interview_turn(second["state"], "今回も2時間おきです", [], "ja",
                                                  extracted={**empty_extraction(), "fram_time": ["今回も2時間おき"]}, task_memory=memory))
            self.assertEqual(third["state"]["task_coverage_by_fram"]["time"], 0.05)
            self.assertNotIn("いつもと違うこと", third["text"])
            fourth = asyncio.run(run_interview_turn(third["state"], "いつも通りです", [], "ja",
                                                   extracted={**empty_extraction(), "usual_work": True}, task_memory=memory))
            self.assertNotIn("2時間おき", fourth["text"])

    def test_past_history_and_usual_answer_do_not_change_normal_guidance_in_any_phase(self):
        self.history("past", "ダスター交換", "2時間おきに交換する")
        memory = load_task_memory("admin", "ダスター交換", exclude_session_id="new", profile={})
        for phase in ("coverage", "depth", "anchor", "irregular", "end"):
            with self.subTest(phase=phase):
                state = initial_state()
                state.update(target_work="ダスター交換", task_revisit_work="ダスター交換")
                info = empty_extraction()
                if phase != "coverage":
                    state["task_coverage_by_fram"] = {key: 0.1 for key in state["task_coverage_by_fram"]}
                if phase in ("irregular", "end"):
                    state["task_depth"] = 5
                if phase == "anchor":
                    info.update(deep_dive_opportunity=True, deep_dive_anchor="二組で回す")
                if phase == "end":
                    state.update(practice_covered=True, high_depth_turn_count=2, irregular_coverage=0.6,
                                 irregular_evidence=irregular_evidence())
                with patch("interview.agent.configured", return_value=False):
                    normal = asyncio.run(run_interview_turn(deepcopy(state), "回答", [], "ja", extracted=info))
                    repeated = asyncio.run(run_interview_turn(deepcopy(state), "いつも通りです", [], "ja",
                                                              extracted={**info, "usual_work": True}, task_memory=memory))
                self.assertEqual(repeated["guide"].get("guidance"), normal["guide"].get("guidance"))
                self.assertEqual(repeated["guide"].get("fram_focus"), normal["guide"].get("fram_focus"))
                self.assertEqual(repeated["stateLabel"], normal["stateLabel"])
                self.assertEqual(repeated["text"], normal["text"])

    def test_already_described_usual_or_unusual_work_is_not_asked_again_at_the_start(self):
        self.history("past", "ダスター交換", "2時間おきに交換する")
        memory = load_task_memory("admin", "ダスター交換", exclude_session_id="new", profile={})
        for extra in ({"usual_work": True}, {"irregular_situations": ["洗浄が遅れた"]}):
            with self.subTest(extra=extra), patch("interview.agent.configured", return_value=False):
                result = asyncio.run(run_interview_turn(initial_state(), "ダスター交換についての回答", [], "ja",
                                                       extracted={**empty_extraction(), "target_work": "ダスター交換", **extra}, task_memory=memory))
                self.assertNotIn("いつもと違うこと", result["text"])
                self.assertEqual(result["state"]["task_revisit_work"], "ダスター交換")

    def test_without_matching_history_the_task_starts_with_normal_coverage(self):
        with patch("interview.agent.configured", return_value=False):
            result = asyncio.run(run_interview_turn(initial_state(), "ダスター交換です", [], "ja",
                                                   extracted={**empty_extraction(), "target_work": "ダスター交換"}, task_memory={"sessions": []}))
        self.assertIn("fram_focus", result["guide"])
        self.assertNotIn("いつもと違うこと", result["text"])

    def test_short_followup_keeps_referencing_original_task(self):
        self.history("past", "ダスター交換", "次のシフトを考えて交換する")
        memory = load_participant_profile("admin")
        state = initial_state()
        state["target_work"] = "ダスター交換"
        with patch("api.routes.extract_turn", AsyncMock(return_value=empty_extraction())), \
             patch("interview.agent.configured", return_value=False), \
             self.assertLogs("audiointerview", level="INFO") as logs:
            result = asyncio.run(_run_turn(state, "はい", [], "ja", memory, session_id="new"))
        self.assertTrue(any('"session_id": "past"' in record for record in logs.output))
        self.assertEqual(result["guide"]["fram_focus"], "input")
        self.assertIn("不足が最も大きい FRAM 項目", result["guide"]["guidance"])
        self.assertNotIn("前回", result["text"])
        self.assertEqual(result["state"]["target_work"], "ダスター交換")

    def test_unknown_task_does_not_pull_unrelated_history(self):
        self.history("past", "ダスター交換", "ダスター交換の履歴")
        result = load_task_memory("admin", None, exclude_session_id="new", profile={})
        self.assertEqual(result["sessions"], [])

    def test_profile_loading_cannot_read_summary_nodes_or_conversation_tables(self):
        self.history("past", "ダスター交換", "開始時に読み込まない要約")
        with database() as connection:
            @contextmanager
            def profile_database():
                yield connection

            def authorize(action, table, column, database_name, trigger):
                if action == sqlite3.SQLITE_READ and table not in ("participant_profiles", "participant_domain_knowledge", "interview_sessions"):
                    return sqlite3.SQLITE_DENY
                return sqlite3.SQLITE_OK

            connection.set_authorizer(authorize)
            with patch("db.memory.database", profile_database):
                participant = load_participant_profile("admin")
        self.assertEqual(participant["session_count"], 1)
        self.assertEqual(set(participant), {"account_id", "session_count", "profile", "domain_knowledge"})

    def test_start_uses_only_long_term_profile_and_defers_task_search(self):
        self.history("past", "ダスター交換", "開始時に読み込まない要約")
        save_session_memory("admin", "past", empty_profile(), {
            "summary": "開始時に読み込まない要約", "profile_patch": {"role": "時間帯責任者"}, "nodes": [], "edges": [],
        })
        with TestClient(app) as client:
            self.assertEqual(client.post("/api/auth/login", json={"id": "admin", "password": "admin"}).status_code, 200)
            session_id = client.post("/api/sessions", json={}).json()["session"]["id"]
            with patch("db.memory.load_participant_memory", side_effect=AssertionError("Broad history must not be loaded")), \
                 patch("api.routes.load_task_memory", side_effect=AssertionError("No task has been identified")), \
                 self.assertLogs("audiointerview", level="INFO") as logs:
                response = client.post(f"/api/sessions/{session_id}/start")
        self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual(len(response.json()["messages"]), 1)
        events = [json.loads(record.getMessage().split("[interview] ", 1)[1]) for record in logs.records]
        start = next(event for event in events if event["event"] == "session_started")
        self.assertEqual(start["memory"]["profile"]["role"], "時間帯責任者")
        self.assertEqual(set(start["memory"]), {"account_id", "session_count", "profile", "domain_knowledge"})
        self.assertNotIn("開始時に読み込まない要約", str(events))
        self.assertFalse(any(event["event"] == "memory_referenced" for event in events))

    def test_task_search_waits_until_an_answer_identifies_the_task(self):
        self.history("past", "ダスター交換", "ダスター交換の要約")
        participant = load_participant_profile("admin")
        with patch("api.routes.extract_turn", AsyncMock(return_value=empty_extraction())), \
             patch("api.routes.load_task_memory", side_effect=AssertionError("Task is still unknown")), \
             patch("interview.agent.configured", return_value=False):
            result = asyncio.run(_run_turn(initial_state(), "えーと", [], "ja", participant, session_id="new"))
        self.assertIsNone(result["state"]["target_work"])

    def test_task_name_normalization_does_not_match_a_different_replacement_task(self):
        for old in ("ダスターの交換", "ﾀﾞｽﾀｰ交換", "ダスター 交換"):
            self.assertGreater(task_match_score("ダスター交換", old), 0)
        self.assertEqual(task_match_score("ダスター交換", "フィルター交換"), 0)
        self.assertEqual(task_match_score("交換", "ダスター交換"), 0)

    def test_reference_excerpts_are_bounded(self):
        self.history("past", "ダスター交換", "要約" * 1000)
        with database() as connection:
            state = initial_state()
            state.update(target_work="ダスター交換", known_facts=[f"事実{i}" + "内容" * 1000 for i in range(30)])
            update_state(connection, "past", state, "end")
        from config import load_config
        config = load_config("interview")["retrieval"]
        with patch.dict(config, {"task_context_chars": 400, "summary_chars": 100, "message_chars": 80}):
            result = load_task_memory("admin", "ダスター交換", exclude_session_id="new", profile={})
        session = result["sessions"][0]
        self.assertLessEqual(len(session["summary"]) + sum(len(value) for values in session["info"].values() for value in values), 400)

    def test_task_retrieval_does_not_read_past_messages(self):
        self.history("past", "ダスター交換", "ダスター交換の要約")
        with patch("db.memory.list_messages", side_effect=AssertionError("Past messages must not be read")):
            result = load_task_memory("admin", "ダスター交換", exclude_session_id="current", profile={})
        self.assertEqual(result["sessions"][0]["summary"], "ダスター交換の要約")
        self.assertNotIn("messages", result["sessions"][0])

    def test_coverage_uses_memory_in_background_without_requiring_a_spoken_reference(self):
        state = initial_state()
        state["target_work"] = "ダスター交換"
        state["task_coverage_by_fram"] = {key: 0.05 for key in state["task_coverage_by_fram"]}
        state["task_coverage_by_fram"]["control"] = 0
        state["task_coverage_by_fram"]["output"] = 0
        memory = {"sessions": [{"session_id": "past", "summary": "以前は決まった手順でダスターを交換した"}]}
        with patch("interview.agent.configured", return_value=True), \
             patch("interview.agent.complete", AsyncMock(return_value="今回はどのように進め方を決めましたか？")) as generate:
            result = asyncio.run(run_interview_turn(state, "交換しました", [], "ja",
                                                   extracted=empty_extraction(), task_memory=memory))
        prompt = generate.call_args.args[0]
        self.assertEqual(result["guide"]["fram_focus"], "control")
        self.assertTrue(result["guide"]["past_memory_used"])
        self.assertIn("同じことを聞き直さず、今の質問方針に沿って", prompt)
        self.assertIn("同じだったことや違いがあったことは決めつけない", prompt)
        self.assertIn("オープンエンド", prompt)
        self.assertIn("過去の情報を質問文に入れる必要はありません", prompt)
        self.assertNotIn("今回も2時間おきだったか", prompt)
        self.assertNotIn("以前", result["text"])

    def test_past_memory_is_available_for_depth_but_not_irregular_or_reflection(self):
        memory = {"sessions": [{"session_id": "past", "summary": "過去にしかない固有の情報"}],
                  "profile": {"role": "時間帯責任者"}}
        for stage in ("depth", "irregular", "reflection", "dive", "dive_depth", "friction"):
            with self.subTest(stage=stage):
                state = initial_state()
                state["target_work"] = "ダスター交換"
                state["task_coverage_by_fram"] = {key: 0.1 for key in state["task_coverage_by_fram"]}
                state["task_depth"] = 1 if stage in ("depth", "dive_depth") else 5
                if stage == "reflection":
                    state["irregular_coverage"] = 0.6
                    state["irregular_evidence"] = irregular_evidence()
                info = empty_extraction()
                if stage in ("dive", "dive_depth"):
                    info.update(deep_dive_opportunity=True, deep_dive_anchor="二組で回す")
                if stage == "friction":
                    info["signs_of_friction"] = ["違います"]
                with patch("interview.agent.configured", return_value=True), \
                     patch("interview.agent.complete", AsyncMock(return_value="今回の話を聞かせてください。")) as generate:
                    result = asyncio.run(run_interview_turn(state, "回答", [], "ja", extracted=info, task_memory=memory))
                expected = stage in ("depth", "dive_depth")
                self.assertEqual(result["guide"]["past_memory_used"], expected)
                if expected:
                    self.assertIn("過去にしかない固有の情報", generate.call_args.args[0])
                    self.assertIn("時間帯責任者", generate.call_args.args[0])
                else:
                    self.assertNotIn("過去にしかない固有の情報", generate.call_args.args[0])

    def test_first_session_coverage_keeps_the_same_progression_without_inventing_a_reference(self):
        state = initial_state()
        state["target_work"] = "ダスター交換"
        with patch("interview.agent.configured", return_value=True), \
             patch("interview.agent.complete", AsyncMock(return_value="交換が必要になったきっかけは何でしたか？")) as generate:
            result = asyncio.run(run_interview_turn(state, "交換しました", [], "ja", extracted=empty_extraction()))
        self.assertEqual(result["guide"]["fram_focus"], "input")
        self.assertFalse(result["guide"]["past_memory_used"])
        self.assertNotIn("過去セッションからの参照情報", generate.call_args.args[0])

    def test_depth_can_use_profile_without_matched_task_sessions(self):
        state = initial_state()
        state["target_work"] = "ダスター交換"
        state["task_coverage_by_fram"] = {key: 0.1 for key in state["task_coverage_by_fram"]}
        memory = {"profile": {"role": "時間帯責任者", "typical_day": ["新人の支援"]}, "sessions": []}
        with patch("interview.agent.configured", return_value=True), \
             patch("interview.agent.complete", AsyncMock(return_value="その決まりを大切にするようになった経験はありますか？")) as generate:
            result = asyncio.run(run_interview_turn(state, "決まっているからです", [], "ja", extracted=empty_extraction(), task_memory=memory))
        self.assertTrue(result["guide"]["past_memory_used"])
        self.assertIn("時間帯責任者", generate.call_args.args[0])
        self.assertIn("長期プロフィール", generate.call_args.args[0])

    def test_current_history_is_separate_from_completed_session_references(self):
        state = initial_state()
        state["target_work"] = "ダスター交換"
        state["known_facts"] = ["今回だけの新しい事実"]
        state["asked_points"] = ["過去の質問: 今回の途中で聞いた質問"]
        memory = {"current_session_id": "current", "sessions": [
            {"session_id": "past", "summary": "別セッションの記憶", "messages": [{"content": "過去の本文は渡さない"}]},
            {"session_id": "current", "summary": "現在セッションを過去扱いしない"},
        ]}
        with patch("interview.agent.configured", return_value=True), \
             patch("interview.agent.complete", AsyncMock(return_value="質問ですか？")) as generate:
            asyncio.run(run_interview_turn(state, "回答", [{"role": "user", "content": "今回の会話本文"}], "ja",
                                           extracted=empty_extraction(), task_memory=memory))
        prompt = generate.call_args.args[0]
        self.assertIn("別セッションの記憶", prompt)
        self.assertNotIn("現在セッションを過去扱いしない", prompt)
        self.assertNotIn("過去の本文は渡さない", prompt)
        self.assertIn("今回の会話本文", prompt)
        self.assertIn("今回の質問: 今回の途中で聞いた質問", prompt)
        self.assertNotIn("過去の質問: 今回の途中で聞いた質問", prompt)
        self.assertIn("今回の会話を別セッションの発言として引用せず", prompt)
