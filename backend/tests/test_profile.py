import asyncio
from unittest.mock import AsyncMock, patch
import unittest

from fastapi.testclient import TestClient

from backend_test_support import DatabaseTestCase, app, database
from db.database import update_state
from interview.agent import initial_state
from interview.profile_agent import CONFIG, EXPERIENCE_DECLINED_NOTE, EXPERIENCE_QUESTIONS, OPENINGS, PROFILE_FIELDS, meets_completion_criteria, run_profile_turn, starter


def profile_extraction(**overrides):
    return {**{field: [] for field in PROFILE_FIELDS}, "role": ["設備担当"],
            "experience": ["3年目"], "responsibilities": ["点検"],
            "typical_day": ["巡回"], "collaborators": ["同じ班"],
            "wants_to_stop": False, **overrides}


class ProfileTests(unittest.TestCase):
    def test_opening_asks_about_work_and_reserves_tenure_for_later(self):
        with patch("interview.profile_agent.configured", return_value=True), \
             patch("interview.profile_agent.complete", AsyncMock(return_value="普段はどんなお仕事をされていますか？")) as generate:
            self.assertEqual(asyncio.run(starter("ja")), "普段はどんなお仕事をされていますか？")
            self.assertIn("冒頭では経験年数を尋ねません", generate.call_args.args[0])
        with patch("interview.profile_agent.configured", return_value=False):
            for language in ("ja", "en", "de"):
                self.assertEqual(asyncio.run(starter(language)), OPENINGS[language])
            self.assertNotIn("何年目", asyncio.run(starter("ja")))

    def test_required_tenure_question_follows_two_answers_about_work(self):
        for language in ("ja", "en", "de"):
            with self.subTest(language=language), \
                 patch("interview.profile_agent.configured", return_value=True), \
                 patch("interview.profile_agent.complete_json", AsyncMock(return_value=profile_extraction(experience=[]))), \
                 patch("interview.profile_agent.complete", AsyncMock(return_value="普段の担当業務を教えてください。")) as generate:
                first = asyncio.run(run_profile_turn(initial_state(), "設備担当です", [], language, {}))
                self.assertNotEqual(first["text"], EXPERIENCE_QUESTIONS[language])
                second = asyncio.run(run_profile_turn(first["state"], "巡回しています", [], language, {}))
                self.assertEqual(second["text"], EXPERIENCE_QUESTIONS[language])
                self.assertTrue(second["state"]["profile_experience_asked"])
                self.assertEqual(generate.await_count, 1)

    def test_coverage_without_current_job_tenure_is_not_complete(self):
        state = {**initial_state(), "turn_count": CONFIG["min_turns"]}
        state["persona_notes"] = [f"初回プロフィール/{field}: 回答済み" for field in PROFILE_FIELDS]
        self.assertFalse(meets_completion_criteria(state))
        for duration in ("3年目", "半年", "6か月", "二十年", "2.5 years", "6 months", "3 Jahre", "6 Monate"):
            with self.subTest(duration=duration):
                state["persona_notes"][-1] = f"初回プロフィール/experience: {duration}"
                self.assertTrue(meets_completion_criteria(state))

    def test_explicit_stop_is_not_completion_even_with_enough_information(self):
        state = {**initial_state(), "turn_count": CONFIG["min_turns"] - 1}
        with patch("interview.profile_agent.configured", return_value=True), \
             patch("interview.profile_agent.complete_json", AsyncMock(return_value=profile_extraction(wants_to_stop=True))):
            result = asyncio.run(run_profile_turn(state, "終了します", [], "ja", {}))
        self.assertEqual(result["stateLabel"], "end")
        self.assertFalse(result["state"]["profile_completed"])
        self.assertEqual(result["state"]["profile_end_reason"], "participant_stop")

    def test_declining_tenure_is_recorded_and_not_asked_again(self):
        state = {**initial_state(), "turn_count": 1}
        with patch("interview.profile_agent.configured", return_value=True), \
             patch("interview.profile_agent.complete_json", AsyncMock(return_value=profile_extraction(experience=["経験年数は答えたくない"]))) as extract, \
             patch("interview.profile_agent.complete", AsyncMock(return_value="普段はどなたと仕事をされますか？")) as generate:
            result = asyncio.run(run_profile_turn(state, "経験年数は答えたくないです", [], "ja", {}))
        self.assertEqual(result["stateLabel"], "running")
        self.assertIn("初回プロフィール/experience: 経験年数は答えたくない", result["state"]["persona_notes"])
        self.assertIn(EXPERIENCE_DECLINED_NOTE, result["state"]["persona_notes"])
        self.assertNotEqual(result["text"], EXPERIENCE_QUESTIONS["ja"])
        self.assertIn("聞き直したり", generate.call_args.args[0])
        self.assertIn("回答拒否だけでは面談全体の終了希望にはせず", extract.call_args.args[0])

    def test_declining_tenure_can_satisfy_profile_completion(self):
        state = {**initial_state(), "turn_count": CONFIG["min_turns"] - 1}
        with patch("interview.profile_agent.configured", return_value=True), \
             patch("interview.profile_agent.complete_json", AsyncMock(return_value=profile_extraction(experience=["答えたくない"]))):
            result = asyncio.run(run_profile_turn(state, "年数は答えたくないです", [], "ja", {}))
        self.assertEqual(result["stateLabel"], "end")
        self.assertTrue(result["state"]["profile_completed"])
        self.assertEqual(result["state"]["profile_end_reason"], "completed")

    def test_turn_limit_without_tenure_is_not_completion(self):
        state = {**initial_state(), "turn_count": CONFIG["max_turns"] - 1}
        extraction = profile_extraction(experience=[], workplace_context=["工場"])
        with patch("interview.profile_agent.configured", return_value=True), \
             patch("interview.profile_agent.complete_json", AsyncMock(return_value=extraction)):
            result = asyncio.run(run_profile_turn(state, "点検を担当しています", [], "ja", {}))
        self.assertEqual(result["stateLabel"], "end")
        self.assertFalse(result["state"]["profile_completed"])
        self.assertEqual(result["state"]["profile_end_reason"], "turn_limit")

    def test_unknown_profile_point_is_remembered_and_not_asked_again(self):
        question = "そのお仕事は何年目になりますか？"
        state = {**initial_state(), "turn_count": 1}
        with patch("interview.profile_agent.configured", return_value=True), \
             patch("interview.profile_agent.complete_json", AsyncMock(return_value=profile_extraction(experience=[]))), \
             patch("interview.profile_agent.complete", AsyncMock(return_value=question)) as generate:
            result = asyncio.run(run_profile_turn(state, "よく分かりません", [{"role": "system", "content": question}], "ja", {}))
        self.assertEqual(result["state"]["unanswered_points"], [question])
        self.assertTrue(result["state"]["profile_experience_asked"])
        self.assertNotEqual(result["text"], question)
        self.assertIn(question, generate.call_args.args[0])

    def test_profile_cannot_exceed_the_global_twenty_answer_limit(self):
        state = {**initial_state(), "turn_count": 19}
        with patch.dict(CONFIG, {"max_turns": 30}), \
             patch("interview.profile_agent.configured", return_value=False):
            result = asyncio.run(run_profile_turn(state, "回答です", [], "ja", {}))
        self.assertEqual(result["stateLabel"], "end")
        self.assertEqual(result["state"]["turn_count"], 20)
        self.assertFalse(result["state"]["profile_completed"])


class ProfileProgressionTests(DatabaseTestCase):
    def setUp(self):
        super().setUp()
        self.client = self.enterContext(TestClient(app))
        self.enterContext(patch("interview.profile_agent.configured", return_value=True))
        self.extraction = self.enterContext(patch("interview.profile_agent.complete_json", AsyncMock(return_value=profile_extraction())))
        self.enterContext(patch("interview.profile_agent.complete", AsyncMock(return_value="担当している業務について教えてください。")))
        self.regular_starter = self.enterContext(patch("api.routes.longitudinal_starter", AsyncMock(return_value="直前まで何をしていましたか？")))

        async def finish_memory(account_id, session_id, language, messages):
            with database() as connection:
                connection.execute("UPDATE session_memory_jobs SET status='fallback' WHERE session_id=?", (session_id,))

        self.enterContext(patch("api.routes.finalize_session", AsyncMock(side_effect=finish_memory)))
        self.request("/auth/login", {"id": "admin", "password": "admin"})

    def request(self, path, body=None):
        response = self.client.post("/api" + path, json=body or {})
        self.assertLess(response.status_code, 400, response.text)
        return response.json()

    def start(self):
        session_id = self.request("/sessions")["session"]["id"]
        return session_id, self.request(f"/sessions/{session_id}/start")

    def finish_profile(self, session_id, turns=None):
        for _ in range(turns or CONFIG["min_turns"]):
            result = self.request(f"/sessions/{session_id}/messages", {"maskedText": "3年目で、点検と巡回を班の同僚と担当しています。"})
        return result

    def test_repeated_manual_ends_keep_profile_mode(self):
        for _ in range(3):
            session_id, start = self.start()
            self.assertEqual(start["state"]["interview_mode"], "profile")
            self.request(f"/sessions/{session_id}/messages", {"maskedText": "3年目です"})
            ended = self.request(f"/sessions/{session_id}/end")
            self.assertFalse(ended["state"]["profile_completed"])
            self.assertEqual(ended["state"]["profile_end_reason"], "manual")
        self.regular_starter.assert_not_awaited()

    def test_successful_automatic_end_unlocks_normal_mode_and_is_account_scoped(self):
        session_id, _ = self.start()
        ended = self.finish_profile(session_id)
        self.assertEqual(ended["session"]["status"], "ended")
        self.assertTrue(ended["state"]["profile_completed"])
        self.assertEqual(ended["state"]["profile_end_reason"], "completed")
        # An idempotent end request must not clear an already completed profile.
        self.assertTrue(self.request(f"/sessions/{session_id}/end")["state"]["profile_completed"])
        _, normal = self.start()
        self.assertEqual(normal["state"]["interview_mode"], "interview")
        self.regular_starter.assert_awaited_once()
        self.request("/admin/accounts", {"id": "another", "displayName": "別の人"})
        self.request("/auth/login", {"id": "another"})
        _, other = self.start()
        self.assertEqual(other["state"]["interview_mode"], "profile")

    def test_turn_limit_retries_profile_even_after_all_other_fields_are_covered(self):
        self.extraction.return_value = profile_extraction(experience=[], workplace_context=["工場"])
        session_id, _ = self.start()
        ended = self.finish_profile(session_id, CONFIG["max_turns"])
        self.assertEqual(ended["session"]["status"], "ended")
        self.assertFalse(ended["state"]["profile_completed"])
        _, retry = self.start()
        self.assertEqual(retry["state"]["interview_mode"], "profile")

    def test_stop_request_retries_profile(self):
        self.extraction.return_value = profile_extraction(wants_to_stop=True)
        session_id, _ = self.start()
        ended = self.request(f"/sessions/{session_id}/messages", {"maskedText": "ここで終了します"})
        self.assertEqual(ended["session"]["status"], "ended")
        self.assertFalse(ended["state"]["profile_completed"])
        _, retry = self.start()
        self.assertEqual(retry["state"]["interview_mode"], "profile")

    def test_refusal_survives_a_retry_and_allows_normal_mode_after_completion(self):
        self.extraction.return_value = profile_extraction(experience=[])
        session_id, _ = self.start()
        for _ in range(2):
            result = self.request(f"/sessions/{session_id}/messages", {"maskedText": "設備の点検と巡回をしています"})
        self.assertEqual(result["messages"][-1]["content"], EXPERIENCE_QUESTIONS["ja"])
        self.extraction.return_value = profile_extraction(experience=["年数は言いたくない"])
        declined = self.request(f"/sessions/{session_id}/messages", {"maskedText": "年数は言いたくないです"})
        self.assertIn(EXPERIENCE_DECLINED_NOTE, declined["state"]["persona_notes"])
        self.assertEqual(declined["session"]["status"], "running")
        self.request(f"/sessions/{session_id}/end")
        self.extraction.return_value = profile_extraction(experience=[])
        retry_id, retry = self.start()
        self.assertIn(EXPERIENCE_DECLINED_NOTE, retry["state"]["persona_notes"])
        for _ in range(CONFIG["min_turns"]):
            result = self.request(f"/sessions/{retry_id}/messages", {"maskedText": "点検と巡回を同じ班の同僚と担当しています"})
            self.assertNotEqual(result["messages"][-1]["content"], EXPERIENCE_QUESTIONS["ja"])
        self.assertEqual(result["session"]["status"], "ended")
        self.assertTrue(result["state"]["profile_completed"])
        _, normal = self.start()
        self.assertEqual(normal["state"]["interview_mode"], "interview")

    def test_an_in_progress_profile_keeps_its_mode_after_another_attempt_completes(self):
        waiting_id, _ = self.start()
        completed_id, _ = self.start()
        self.finish_profile(completed_id)
        continued = self.request(f"/sessions/{waiting_id}/messages", {"maskedText": "3年目です"})
        self.assertEqual(continued["state"]["interview_mode"], "profile")
        self.assertFalse(continued["state"]["profile_completed"])

    def test_manual_end_cannot_approve_an_unfinished_profile_with_sufficient_notes(self):
        session_id, _ = self.start()
        state = {**initial_state(), "turn_count": CONFIG["min_turns"], "interview_mode": "profile"}
        state["persona_notes"] = [f"初回プロフィール/{key}: {value}" for key, values in profile_extraction().items()
                                  if isinstance(values, list) for value in values]
        self.assertTrue(meets_completion_criteria(state))
        with database() as connection:
            update_state(connection, session_id, state, "running")
        ended = self.request(f"/sessions/{session_id}/end")
        self.assertFalse(ended["state"]["profile_completed"])
        _, retry = self.start()
        self.assertEqual(retry["state"]["interview_mode"], "profile")
