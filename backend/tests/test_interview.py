import asyncio
from unittest.mock import AsyncMock, patch
import unittest

import backend_test_support  # Configure the import path and external inference boundary.
from interview.agent import ENDINGS, empty_extraction, initial_state, run_interview_turn, should_end, update_state
from interview.profile_agent import run_profile_turn


class InterviewTests(unittest.TestCase):
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
