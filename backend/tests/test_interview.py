import asyncio
from unittest.mock import AsyncMock, patch
import unittest

import backend_test_support  # Configure the import path and external inference boundary.
from backend_test_support import irregular_evidence
from interview.agent import ENDINGS, FRAM_MEANINGS, empty_extraction, initial_state, run_interview_turn, should_end, update_state
from interview.profile_agent import CONFIG as PROFILE_CONFIG, run_profile_turn


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

    def test_unknown_or_unconsidered_answer_records_the_point_and_stops_the_dive(self):
        question = "故障対応を先にするのはなぜですか？"
        for answer in ("わかんないです", "そこまで考えてないです", "答えたくないです"):
            with self.subTest(answer=answer):
                state = initial_state()
                state["target_work"] = "設備点検"
                state["deep_dive"] = {"anchor": "故障対応が優先", "return_target_work": "設備点検", "stage": "clarify"}
                with patch("interview.agent.configured", return_value=False):
                    result = asyncio.run(run_interview_turn(state, answer, [{"role": "system", "content": question}], "ja",
                                                           extracted=empty_extraction()))
                self.assertIsNone(result["state"]["deep_dive"])
                self.assertEqual(result["state"]["unanswered_points"], [question])
                self.assertIn("別の場面・行動・観点", result["guide"]["guidance"])
                self.assertNotEqual(result["text"], question)
                self.assertEqual(result["state"]["resistance_count"], 0)
                self.assertEqual(initial_state()["unanswered_points"], [])

    def test_unanswered_point_survives_history_truncation_and_exact_reask_is_replaced(self):
        question = "その判断を大事にしている理由は何ですか？"
        state = initial_state()
        state.update(target_work="設備点検", unanswered_points=[question])
        history = [{"role": "system", "content": question}] + [{"role": "user", "content": "別の話です"}] * 35
        with patch("interview.agent.configured", return_value=True), \
             patch("interview.agent.complete", AsyncMock(return_value=question)) as generate:
            result = asyncio.run(run_interview_turn(state, "次は巡回しました", history, "ja", extracted=empty_extraction()))
        self.assertIn(question, generate.call_args.args[0])
        self.assertIn("coverageやdepthの不足よりこの制約を優先", generate.call_args.args[0])
        self.assertEqual(result["state"]["unanswered_points"], [question])
        self.assertNotEqual(result["text"], question)

    def test_describing_how_to_handle_unknowns_is_not_an_unanswered_point(self):
        for answer in ("分からないときは資料を確認します", "分からない場合は同僚に聞きます", "「分からない」と新人に言われたので説明しました"):
            with self.subTest(answer=answer), patch("interview.agent.configured", return_value=False):
                result = asyncio.run(run_interview_turn(initial_state(), answer, [], "ja", extracted=empty_extraction()))
                self.assertEqual(result["state"]["unanswered_points"], [])

    def test_twentieth_answer_ends_even_during_a_dive_or_user_question(self):
        for language in ("ja", "en", "de"):
            with self.subTest(language=language):
                state = initial_state()
                state.update(turn_count=19, deep_dive={"anchor": "故障対応", "return_target_work": "設備点検", "stage": "reason"})
                with patch("interview.agent.complete", AsyncMock()) as generate:
                    result = asyncio.run(run_interview_turn(state, "どういう意味ですか？", [], language,
                                                           extracted={**empty_extraction(), "user_questions": ["どういう意味？"]}))
                self.assertEqual(result["state"]["turn_count"], 20)
                self.assertEqual(result["stateLabel"], "end")
                self.assertEqual(result["text"], ENDINGS[language])
                self.assertIsNone(result["state"]["deep_dive"])
                self.assertEqual(result["guide"]["end_reason"], "turn_limit")
                generate.assert_not_awaited()

    def test_nineteenth_answer_does_not_end_only_because_of_the_limit(self):
        state = initial_state()
        state["turn_count"] = 18
        with patch("interview.agent.configured", return_value=False):
            result = asyncio.run(run_interview_turn(state, "特にありません", [], "ja", extracted=empty_extraction()))
        self.assertEqual(result["stateLabel"], "running")
        self.assertEqual(result["state"]["turn_count"], 19)

    def test_automatic_end_waits_for_pending_reason_answer(self):
        state = initial_state()
        state.update(target_work="設備点検", practice_covered=True, task_depth=5, high_depth_turn_count=2,
                     irregular_coverage=0.6, irregular_evidence=irregular_evidence())
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

    def test_fram_breadth_bonus_counts_categories_with_even_partial_coverage(self):
        for count, score, expected in (
            (0, 0.05, 0), (1, 0.05, 0.05),
            (2, 0.05, 0.15), (2, 0.1, 0.25),
            (3, 0.05, 0.25), (3, 0.1, 0.4),
            (4, 0.05, 0.4), (4, 0.1, 0.6),
            (5, 0.05, 0.45), (6, 0.05, 0.7), (6, 0.1, 1),
        ):
            with self.subTest(count=count, score=score):
                state = initial_state()
                for field in list(state["task_coverage_by_fram"])[:count]:
                    state["task_coverage_by_fram"][field] = score
                update_state(state, empty_extraction())
                self.assertEqual(state["task_coverage"], expected)

    def test_fram_breadth_bonus_is_not_added_again_on_each_turn(self):
        state = initial_state()
        info = {**empty_extraction(), "fram_input": ["依頼", "対象物"],
                "fram_resource": ["計器"], "fram_output": ["点検完了"]}
        update_state(state, info)
        self.assertEqual(state["task_coverage"], 0.25)
        for _ in range(3):
            update_state(state, empty_extraction())
            self.assertEqual(state["task_coverage"], 0.25)
        for _ in range(3):
            update_state(state, info)
            self.assertEqual(state["task_coverage"], 0.4)

    def test_deep_answers_alone_do_not_end_without_work_coverage(self):
        state = initial_state()
        info = {**empty_extraction(), "target_work": "設備点検", "practices": ["温度を確認"],
                "reasons": ["異常を見逃さない"], "sources": ["教育で学んだ"], "values": ["安全を優先"]}
        update_state(state, info)
        update_state(state, info)
        self.assertEqual(state["task_depth"], 5)
        self.assertFalse(should_end(state))
        state["task_coverage"] = 0.44
        self.assertFalse(should_end(state))
        state["task_coverage"] = 0.45
        self.assertFalse(should_end(state))
        state["irregular_coverage"] = 0.25
        self.assertFalse(should_end(state))
        state["irregular_coverage"] = 0.59
        self.assertFalse(should_end(state))
        state["irregular_coverage"] = 0.6
        self.assertTrue(should_end(state))

    def test_missing_precondition_is_asked_alone_when_returning_from_dive(self):
        state = initial_state()
        state["target_work"] = "ダスターの交換"
        state["task_coverage_by_fram"] = {key: 0.05 for key in state["task_coverage_by_fram"]}
        state["task_coverage_by_fram"]["precondition"] = 0
        state["task_coverage_by_fram"]["output"] = 0
        state["deep_dive"] = {"anchor": "次のシフトへの配慮", "stage": "reason",
                              "return_target_work": "ダスターの交換"}
        result = self.run_dive_turn(state, "次の人が作業しやすいようにしています")
        self.assertEqual(result["guide"]["fram_focus"], "precondition")
        self.assertEqual(result["text"], "ダスターの交換に取りかかる前に、普段どのようなことをしていますか？")
        self.assertIsNone(result["state"]["deep_dive"])

    def test_return_from_anchor_uses_coverage_threshold_and_preserves_depth_five_transition(self):
        for depth in (3, 5):
            with self.subTest(depth=depth):
                state = initial_state()
                state.update(target_work="ダスター交換", task_depth=depth)
                state["task_coverage_by_fram"] = {"input": 0.05, "precondition": 0, "resource": 0.05,
                                                  "control": 0.05, "time": 0.05, "output": 0.05}
                state["deep_dive"] = {"anchor": "二組で回す", "stage": "reason", "return_target_work": "ダスター交換"}
                result = self.run_dive_turn(state, "決まっているからです", reasons=["決まっているから"])
                self.assertEqual(result["state"]["task_coverage"], 0.45)
                self.assertNotIn("fram_focus", result["guide"])
                self.assertIsNone(result["state"]["deep_dive"])
                if depth < 5:
                    self.assertIn("まだ得られていない段階", result["guide"]["guidance"])
                    self.assertNotIn("現場がどんな状態", result["text"])
                else:
                    self.assertIn("予定どおりに進まない", result["guide"]["guidance"])

    def test_legacy_no_information_flag_does_not_cancel_anchor_or_change_guidance(self):
        state = initial_state()
        state["target_work"] = "ダスター交換"
        state["deep_dive"] = {"anchor": "二組で回す", "stage": "clarify", "return_target_work": "ダスター交換"}
        result = self.run_dive_turn(state, "決まりだから", signs_of_no_information=["決まりだから"])
        self.assertEqual(result["state"]["deep_dive"]["stage"], "reason")
        self.assertNotIn("圧を下げて", result["guide"]["guidance"])
        self.assertNotIn("決まりだから", result["state"]["asked_points"])

    def test_friction_apologizes_and_continues_coverage_depth_or_anchor_questions(self):
        for stage in ("coverage", "depth", "anchor"):
            with self.subTest(stage=stage):
                state = initial_state()
                state["target_work"] = "ダスター交換"
                if stage == "depth":
                    state["task_coverage_by_fram"] = {key: 0.1 for key in state["task_coverage_by_fram"]}
                    state["task_depth"] = 3
                if stage == "anchor":
                    state["deep_dive"] = {"anchor": "二組で回す", "stage": "clarify", "return_target_work": "ダスター交換"}
                result = self.run_dive_turn(state, "そういう意味ではないです", signs_of_friction=["聞き手の誤解"])
                self.assertIn("質問を一つ続ける", result["guide"]["guidance"])
                self.assertNotIn("質問しない", result["guide"]["guidance"])
                self.assertTrue(result["text"].startswith("失礼しました。"))
                self.assertIn("？", result["text"])
                if stage == "coverage":
                    self.assertIn("fram_focus", result["guide"])
                elif stage == "depth":
                    self.assertIn("まだ得られていない段階", result["guide"]["guidance"])
                else:
                    self.assertEqual(result["state"]["deep_dive"]["stage"], "reason")

    def test_coverage_question_targets_missing_fram_even_if_generation_fails(self):
        for language in ("ja", "en", "de"):
            with self.subTest(language=language):
                state = initial_state()
                state["target_work"] = "ダスター交換"
                state["task_coverage_by_fram"] = {key: 0.05 for key in state["task_coverage_by_fram"]}
                state["task_coverage_by_fram"]["precondition"] = 0
                state["task_coverage_by_fram"]["output"] = 0
                with patch("interview.agent.extract_turn", AsyncMock(return_value=empty_extraction())), \
                     patch("interview.agent.configured", return_value=True), \
                     patch("interview.agent.complete", AsyncMock(side_effect=RuntimeError("unavailable"))):
                    result = asyncio.run(run_interview_turn(state, "はい", [], language))
                self.assertEqual(result["guide"]["fram_focus"], "precondition")
                self.assertIn("ダスター交換", result["text"])
                self.assertEqual(result["text"].count("?") + result["text"].count("？"), 1)

    def test_selected_input_meaning_and_guidance_follow_the_recent_material_conversation(self):
        state = initial_state()
        state.update(target_work="ドリンク作り", task_depth=1)
        state["task_coverage_by_fram"] = {"input": 0, "precondition": 0.05, "resource": 0.1,
                                          "control": 0, "time": 0, "output": 0.05}
        state["known_facts"] = ["FRAM resource: ミルク", "FRAM output: 100杯くらい作った"]
        history = [{"role": "system", "content": "他にどんな材料を使いましたか。"},
                   {"role": "user", "content": "ミルク以外は特にありません"}]
        response = "混雑時の注文は、どこで受け取っていましたか。"
        with patch("interview.agent.configured", return_value=True), \
             patch("interview.agent.complete", AsyncMock(return_value=response)) as generate:
            result = asyncio.run(run_interview_turn(state, history[-1]["content"], history, "ja",
                                                   extracted=empty_extraction()))
        prompt = generate.call_args.args[0]
        self.assertEqual(result["guide"]["fram_focus"], "input")
        self.assertEqual(result["state"]["task_coverage_by_fram"]["resource"], 0.1)
        self.assertIn(f"input = {FRAM_MEANINGS['input']}", prompt)
        self.assertGreater(prompt.index("今の方針:"), prompt.rindex("直前の回答:"))
        self.assertGreater(prompt.index("今回尋ねるFRAM項目:"), prompt.rindex("ミルク以外は特にありません"))
        self.assertIn(f"今回の質問: {response}", result["state"]["asked_points"])

    def test_japanese_questions_without_question_marks_are_recorded_but_reflections_are_not(self):
        for response, expected in (
            ("注文はどこで受け取っていましたか。", True),
            ("注文はどこで受け取っていましたか", True),
            ("注文の受け取り方を教えてください。", True),
            ("注文がたくさん入っていたのですね。", False),
            ("大変な状況だったのですね。", False),
        ):
            with self.subTest(response=response):
                state = initial_state()
                state["target_work"] = "ドリンク作り"
                with patch("interview.agent.configured", return_value=True), \
                     patch("interview.agent.complete", AsyncMock(return_value=response)):
                    result = asyncio.run(run_interview_turn(state, "回答", [], "ja", extracted=empty_extraction()))
                self.assertEqual(bool(result["state"]["asked_points"]), expected)
                self.assertEqual(result["state"]["consecutive_questions"], int(expected))
                self.assertEqual(result["state"]["turns_since_reflection"], int(expected))
                self.assertEqual(result["state"]["rapport"] > 0, not expected)

    def test_missing_resource_keeps_broad_resource_scope_when_generation_is_unavailable(self):
        for language in ("ja", "en", "de"):
            with self.subTest(language=language):
                state = initial_state()
                state["target_work"] = "ダスター交換"
                state["task_coverage_by_fram"] = {key: 0.05 for key in state["task_coverage_by_fram"]}
                state["task_coverage_by_fram"]["resource"] = 0
                state["task_coverage_by_fram"]["output"] = 0
                with patch("interview.agent.configured", return_value=False):
                    result = asyncio.run(run_interview_turn(state, "回答", [], language, extracted=empty_extraction()))
                self.assertEqual(result["guide"]["fram_focus"], "resource")
                self.assertIn(FRAM_MEANINGS["resource"], result["guide"]["guidance"])
                self.assertIn("ダスター交換", result["text"])
                self.assertEqual(result["text"].count("?") + result["text"].count("？"), 1)

    def test_reported_state_asks_about_irregular_cases_before_ending(self):
        state = initial_state()
        state.update(target_work="ダスターの交換", practice_covered=True, task_depth=5, high_depth_turn_count=6)
        state["task_coverage_by_fram"] = {"input": 0.05, "precondition": 0, "resource": 0.05,
                                          "control": 0.1, "time": 0.05, "output": 0.1}
        result = self.run_dive_turn(state, "そうですね")
        self.assertEqual(result["state"]["task_coverage"], 0.55)
        self.assertEqual(result["stateLabel"], "running")
        self.assertEqual(result["state"]["irregular_coverage"], 0)
        self.assertIn("予定どおりに進まない", result["guide"]["guidance"])
        self.assertIn("？", result["text"])
        followup = self.run_dive_turn(result["state"], "交換用がなければ洗浄を先に行います",
                                      irregular_responses=["交換用がなければ洗浄を先に行う"])
        self.assertEqual(followup["state"]["irregular_coverage"], 0.2)
        self.assertEqual(followup["stateLabel"], "running")
        more_situations = self.run_dive_turn(followup["state"], "次の組の洗浄が終わっていない時です",
                                             irregular_situations=["次の組の洗浄が終わっていない"])
        self.assertEqual(more_situations["state"]["irregular_coverage"], 0.2)
        reasons = self.run_dive_turn(more_situations["state"], "清潔なものがないと安全に作業できないからです",
                                     irregular_reasons=["清潔なものがないと安全に作業できない"])
        self.assertEqual(reasons["state"]["irregular_coverage"], 0.4)
        self.assertEqual(reasons["stateLabel"], "running")
        final = self.run_dive_turn(reasons["state"], "過去の経験からお客さんの信頼を守りたいからです",
                                   irregular_deeper_reasons=["過去の経験からお客さんの信頼を守りたい"])
        self.assertEqual(final["state"]["irregular_coverage"], 0.6)
        self.assertEqual(final["stateLabel"], "end")

    def test_missing_irregular_information_takes_priority_over_a_new_anchor(self):
        state = initial_state()
        state.update(target_work="ダスター交換", practice_covered=True, task_depth=5, high_depth_turn_count=2)
        state["task_coverage_by_fram"] = {key: 0.1 for key in state["task_coverage_by_fram"]}
        result = self.run_dive_turn(state, "チームワークを大切にしています", deep_dive_opportunity=True,
                                    deep_dive_anchor="チームワークを大切にする")
        self.assertIsNone(result["state"]["deep_dive"])
        self.assertEqual(result["stateLabel"], "running")
        self.assertIn("予定どおりに進まない", result["guide"]["guidance"])

    def test_third_consecutive_point_four_ends_without_inventing_deeper_evidence(self):
        state = initial_state()
        state.update(target_work="設備点検", practice_covered=True, task_depth=5, high_depth_turn_count=2,
                     irregular_evidence=irregular_evidence(2))
        state["task_coverage_by_fram"] = {key: 0.1 for key in state["task_coverage_by_fram"]}
        for count in range(1, 4):
            result = self.run_dive_turn(state, "回答です", deep_dive_opportunity=True, deep_dive_anchor="安全を優先する")
            state = result["state"]
            self.assertEqual(state["irregular_coverage"], 0.4)
            self.assertEqual(state["irregular_partial_turn_count"], count)
            self.assertEqual(result["stateLabel"], "running" if count < 3 else "end")
            self.assertEqual(state["irregular_evidence"]["irregular_deeper_reasons"], [])

    def test_partial_irregular_streak_does_not_bypass_other_end_conditions(self):
        for missing in ("coverage", "depth"):
            with self.subTest(missing=missing):
                state = initial_state()
                state.update(target_work="設備点検", practice_covered=True,
                             task_depth=3 if missing == "depth" else 5, high_depth_turn_count=2,
                             irregular_evidence=irregular_evidence(2))
                if missing != "coverage":
                    state["task_coverage_by_fram"] = {key: 0.1 for key in state["task_coverage_by_fram"]}
                for _ in range(3):
                    result = self.run_dive_turn(state, "回答です")
                    state = result["state"]
                self.assertEqual(state["irregular_partial_turn_count"], 3)
                self.assertEqual(result["stateLabel"], "running")

    def test_point_two_does_not_trigger_partial_end_and_full_coverage_resets_streak(self):
        state = initial_state()
        state.update(target_work="設備点検", practice_covered=True, task_depth=5, high_depth_turn_count=2,
                     irregular_evidence=irregular_evidence(1))
        state["task_coverage_by_fram"] = {key: 0.1 for key in state["task_coverage_by_fram"]}
        for _ in range(3):
            state = self.run_dive_turn(state, "回答です")["state"]
            self.assertEqual(state["irregular_partial_turn_count"], 0)
            self.assertFalse(should_end(state))
        for _ in range(2):
            state = self.run_dive_turn(state, "事故を防ぐためです", irregular_reasons=["事故を防ぐため"])["state"]
        self.assertEqual(state["irregular_partial_turn_count"], 2)
        result = self.run_dive_turn(state, "仲間の信頼を守るためです", irregular_deeper_reasons=["仲間との信頼を大切にする"])
        self.assertEqual(result["state"]["irregular_coverage"], 0.6)
        self.assertEqual(result["state"]["irregular_partial_turn_count"], 0)
        self.assertEqual(result["stateLabel"], "end")

    def test_asking_about_irregular_cases_alone_does_not_satisfy_the_end_condition(self):
        state = initial_state()
        state.update(target_work="ダスター交換", practice_covered=True, task_depth=5, high_depth_turn_count=2)
        state["task_coverage_by_fram"] = {key: 0.1 for key in state["task_coverage_by_fram"]}
        for _ in range(2):
            result = self.run_dive_turn(state, "普段どおりです")
            state = result["state"]
            self.assertEqual(result["stateLabel"], "running")
            self.assertEqual(state["irregular_coverage"], 0)
        result = self.run_dive_turn(state, "終了します", wants_to_stop=True)
        self.assertEqual(result["stateLabel"], "end")

    def test_user_question_is_answered_before_ending_at_or_above_irregular_threshold(self):
        for level in range(4):
            coverage = round(level * 0.2, 2)
            with self.subTest(irregular_coverage=coverage):
                state = initial_state()
                state.update(target_work="レジ業務", practice_covered=True, task_depth=5,
                             high_depth_turn_count=3, irregular_coverage=coverage,
                             irregular_evidence=irregular_evidence(level))
                state["task_coverage_by_fram"] = {key: 0.1 for key in state["task_coverage_by_fram"]}
                question = "あえてっていうのはどういうことなんだ？"
                info = {**empty_extraction(), "user_questions": [question],
                        "signs_of_friction": ["聞き方の意図を確認"]}
                answer = "分かりにくい言い方で失礼しました。普段の対応を選びにくい場合を想定していました。"
                with patch("interview.agent.configured", return_value=True), \
                     patch("interview.agent.complete", AsyncMock(return_value=answer)) as generate:
                    result = asyncio.run(run_interview_turn(state, question, [], "ja", extracted=info))
                generate.assert_awaited_once()
                self.assertIn("相手の質問に短く答え", result["guide"]["guidance"])
                self.assertEqual(result["text"], answer)
                self.assertEqual(result["stateLabel"], "running")
                self.assertEqual(result["state"]["irregular_coverage"], coverage)
                self.assertNotIn("should_end", result["guide"])
                following = self.run_dive_turn(result["state"], "わかりました")
                self.assertEqual(following["stateLabel"], "end" if coverage >= 0.6 else "running")

    def test_user_question_defers_ending_when_same_answer_reaches_irregular_threshold(self):
        state = initial_state()
        state.update(target_work="レジ業務", practice_covered=True, task_depth=5,
                     high_depth_turn_count=3, irregular_coverage=0.4, irregular_evidence=irregular_evidence(2))
        state["task_coverage_by_fram"] = {key: 0.1 for key in state["task_coverage_by_fram"]}
        result = self.run_dive_turn(state, "過去の経験から信頼を大切にしています。あえてってどういう意味ですか？",
                                   irregular_deeper_reasons=["過去の経験から信頼を大切にする"], user_questions=["あえてとは？"])
        self.assertEqual(result["state"]["irregular_coverage"], 0.6)
        self.assertEqual(result["stateLabel"], "running")
        self.assertIn("相手の質問に短く答え", result["guide"]["guidance"])

    def test_explicit_stop_still_takes_priority_over_a_user_question(self):
        result = self.run_dive_turn(initial_state(), "その質問の意味は何ですか？ でももう終了してください。",
                                   user_questions=["その質問の意味は何ですか？"], wants_to_stop=True)
        self.assertEqual(result["stateLabel"], "end")
        self.assertEqual(result["text"], ENDINGS["ja"])

    def test_pending_anchor_finishes_before_the_required_irregular_question(self):
        state = initial_state()
        state.update(target_work="ダスター交換", practice_covered=True, task_depth=5, high_depth_turn_count=2)
        state["task_coverage_by_fram"] = {key: 0.1 for key in state["task_coverage_by_fram"]}
        state["deep_dive"] = {"anchor": "二組で回す", "stage": "clarify", "return_target_work": "ダスター交換"}
        first = self.run_dive_turn(state, "交換用と洗浄用の二組です")
        self.assertEqual(first["state"]["deep_dive"]["stage"], "reason")
        second = self.run_dive_turn(first["state"], "作業が止まらないようにするためです")
        self.assertIsNone(second["state"]["deep_dive"])
        self.assertEqual(second["stateLabel"], "running")
        self.assertIn("予定どおりに進まない", second["guide"]["guidance"])

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

    def test_profile_interview_ends_at_seven_answers_when_information_is_available(self):
        state = initial_state()
        state["persona_notes"] = [
            f"初回プロフィール/{field}: 回答済み"
            for field in ("role", "experience", "responsibilities", "collaborators", "personally_important_topics")
        ]
        state["persona_notes"][1] = "初回プロフィール/experience: 3年目"
        with patch("interview.profile_agent.configured", return_value=False):
            for answer in range(1, PROFILE_CONFIG["min_turns"] + 1):
                result = asyncio.run(run_profile_turn(state, "回答", [], "ja", {}))
                self.assertEqual(result["stateLabel"], "running" if answer < PROFILE_CONFIG["min_turns"] else "end")
                state = result["state"]
        self.assertTrue(result["state"]["profile_completed"])

    def test_profile_interview_has_turn_limit(self):
        state = initial_state()
        state["turn_count"] = PROFILE_CONFIG["max_turns"] - 2
        with patch("interview.profile_agent.configured", return_value=False):
            for answer in range(PROFILE_CONFIG["max_turns"] - 1, PROFILE_CONFIG["max_turns"] + 1):
                result = asyncio.run(run_profile_turn(state, "回答", [], "ja", {}))
                self.assertEqual(result["stateLabel"], "running" if answer < PROFILE_CONFIG["max_turns"] else "end")
                state = result["state"]
        self.assertEqual(result["stateLabel"], "end")
        self.assertEqual(result["state"]["turn_count"], PROFILE_CONFIG["max_turns"])
        self.assertFalse(result["state"]["profile_completed"])
