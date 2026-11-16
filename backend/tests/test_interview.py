import asyncio
from unittest.mock import AsyncMock, patch
import unittest

import backend_test_support  # Configure the import path and external inference boundary.
from interview.agent import ENDINGS, empty_extraction, initial_state, run_interview_turn, should_end, update_state
from interview.profile_agent import run_profile_turn


class InterviewTests(unittest.TestCase):
    def run_dive_turn(self, state, text, **extracted):
        info = {**empty_extraction(), **extracted}
        with patch("interview.agent.extract_turn", AsyncMock(return_value=info)), \
             patch("interview.agent.configured", return_value=False):
            return asyncio.run(run_interview_turn(state, text, [], "ja"))

    def test_dive_clarifies_then_asks_reason_then_returns_to_original_work(self):
        state = initial_state()
        state["target_work"] = "設備点検"
        first = self.run_dive_turn(state, "他のタスクの方が優先だから", deep_dive_opportunity=True,
                                   deep_dive_anchor="他のタスクの方が優先", deep_dive_needs_clarification=True)
        self.assertEqual(first["state"]["deep_dive"]["stage"], "clarify")
        self.assertIn("具体的には", first["text"])
        second = self.run_dive_turn(first["state"], "故障対応です", target_work="故障対応")
        self.assertEqual(second["state"]["deep_dive"]["stage"], "reason")
        self.assertEqual(second["state"]["target_work"], "設備点検")
        self.assertNotIn("対象業務: 故障対応", second["state"]["known_facts"])
        self.assertIn("理由", second["text"])
        self.assertIn("他のタスクの方が優先", second["text"])
        third = self.run_dive_turn(second["state"], "ラインが止まるためです", reasons=["ラインが止まるため"],
                                  deep_dive_opportunity=True, deep_dive_anchor="ラインが止まる")
        self.assertIsNone(third["state"]["deep_dive"])
        self.assertIn("元の対象業務『設備点検』", third["guide"]["guidance"])
        self.assertIn("理由: ラインが止まるため", third["state"]["known_facts"])

    def test_dive_skips_clarification_when_subject_is_clear(self):
        result = self.run_dive_turn(initial_state(), "点検より故障対応を優先します", deep_dive_opportunity=True,
                                    deep_dive_anchor="点検より故障対応を優先")
        self.assertEqual(result["state"]["deep_dive"]["stage"], "reason")
        self.assertIn("理由", result["text"])

    def test_reason_volunteered_during_clarification_is_not_asked_again(self):
        first = self.run_dive_turn(initial_state(), "他のタスクが優先", deep_dive_opportunity=True,
                                   deep_dive_anchor="他のタスクが優先", deep_dive_needs_clarification=True)
        result = self.run_dive_turn(first["state"], "ラインが止まるので故障対応です",
                                   deep_dive_reason_answered=True, reasons=["ラインが止まるので"])
        self.assertIsNone(result["state"]["deep_dive"])
        self.assertIn("同じ理由を聞き直したり", result["guide"]["guidance"])

    def test_dive_stops_after_one_reason_question_even_without_reason(self):
        first = self.run_dive_turn(initial_state(), "故障対応が優先", deep_dive_opportunity=True,
                                   deep_dive_anchor="故障対応が優先")
        result = self.run_dive_turn(first["state"], "いつもそうしています")
        self.assertIsNone(result["state"]["deep_dive"])
        self.assertIn("深掘りはここで終え", result["guide"]["guidance"])

    def test_resistance_and_stop_cancel_active_dive(self):
        for info in ({"signs_of_resistance": ["答えたくない"]}, {"wants_to_stop": True}):
            with self.subTest(info=info):
                first = self.run_dive_turn(initial_state(), "故障対応が優先", deep_dive_opportunity=True,
                                           deep_dive_anchor="故障対応が優先")
                result = self.run_dive_turn(first["state"], "終了", **info)
                self.assertIsNone(result["state"]["deep_dive"])
                if info.get("wants_to_stop"):
                    self.assertEqual(result["stateLabel"], "end")
                else:
                    self.assertIn("圧を下げて", result["guide"]["guidance"])

    def test_automatic_end_waits_for_pending_reason_answer(self):
        state = initial_state()
        state.update(target_work="設備点検", practice_covered=True, high_depth_turn_count=2)
        state["task_coverage_by_fram"] = {key: 0.1 for key in state["task_coverage_by_fram"]}
        first = self.run_dive_turn(state, "故障対応が優先", deep_dive_opportunity=True,
                                   deep_dive_anchor="故障対応が優先")
        self.assertEqual(first["stateLabel"], "running")
        second = self.run_dive_turn(first["state"], "ラインが止まるからです", reasons=["ラインが止まるから"])
        self.assertEqual(second["stateLabel"], "end")
        self.assertIsNone(second["state"]["deep_dive"])

    def test_separate_sessions_do_not_share_mutable_state(self):
        first, second = initial_state(), initial_state()
        first["known_facts"].append("事実")
        first["task_coverage_by_fram"]["input"] = 0.1
        self.assertEqual(second["known_facts"], [])
        self.assertEqual(second["task_coverage_by_fram"]["input"], 0)

    def test_fram_coverage_caps_and_includes_completion_bonus(self):
        state = initial_state()
        info = empty_extraction()
        for field in ("fram_input", "fram_precondition", "fram_resource", "fram_control", "fram_time", "fram_output"):
            info[field] = ["明示された事実"]
        update_state(state, info)
        self.assertAlmostEqual(state["task_coverage"], 0.7)
        for _ in range(4):
            update_state(state, info)
        self.assertEqual(state["task_coverage"], 1)
        self.assertTrue(all(value == 0.1 for value in state["task_coverage_by_fram"].values()))

    def test_deep_answers_alone_do_not_end_without_work_coverage(self):
        state = initial_state()
        info = {**empty_extraction(), "target_work": "設備点検", "practices": ["温度を確認"],
                "reasons": ["異常を見逃さない"], "sources": ["教育で学んだ"], "values": ["安全を優先"]}
        update_state(state, info)
        update_state(state, info)
        self.assertEqual(state["task_depth"], 5)
        self.assertFalse(should_end(state))
        state["task_coverage"] = 0.6
        self.assertTrue(should_end(state))

    def test_stop_request_returns_localized_ending_without_generation(self):
        info = {**empty_extraction(), "wants_to_stop": True}
        with patch("interview.agent.extract_turn", AsyncMock(return_value=info)), \
             patch("interview.agent.complete", AsyncMock()) as complete:
            result = asyncio.run(run_interview_turn(initial_state(), "stop", [], "en"))
        self.assertEqual(result["text"], ENDINGS["en"])
        self.assertEqual(result["stateLabel"], "end")
        complete.assert_not_awaited()

    def test_generation_failure_falls_back_and_keeps_turn_progress(self):
        info = {**empty_extraction(), "target_work": "設備点検", "practices": ["確認"]}
        with patch("interview.agent.extract_turn", AsyncMock(return_value=info)), \
             patch("interview.agent.configured", return_value=True), \
             patch("interview.agent.complete", AsyncMock(side_effect=RuntimeError("unavailable"))):
            result = asyncio.run(run_interview_turn(initial_state(), "回答", [], "ja"))
        self.assertEqual(result["stateLabel"], "running")
        self.assertEqual(result["state"]["turn_count"], 1)
        self.assertIn("設備点検", result["text"])

    def test_profile_interview_has_turn_limit(self):
        state = initial_state()
        state["turn_count"] = 8
        with patch("interview.profile_agent.configured", return_value=False):
            result = asyncio.run(run_profile_turn(state, "回答", [], "ja", {}))
        self.assertEqual(result["stateLabel"], "end")
        self.assertEqual(result["state"]["turn_count"], 9)
