import asyncio
import itertools
import unittest
from unittest.mock import AsyncMock, patch

import backend_test_support  # Configure the import path and inference boundary.
from interview.agent import DEPTH_FIELDS, EXTRACT_SCHEMA, extract_turn, initial_state, update_state


class DepthExtractionTests(unittest.TestCase):
    def extract(self, result):
        with patch("interview.agent.configured", return_value=True), \
             patch("interview.agent.complete_json", AsyncMock(return_value=result)):
            return asyncio.run(extract_turn("今回の回答", initial_state(), []))

    def test_schema_requests_one_category_instead_of_parallel_depth_arrays(self):
        for field in DEPTH_FIELDS:
            self.assertNotIn(field, EXTRACT_SCHEMA["properties"])
            self.assertNotIn(field, EXTRACT_SCHEMA["required"])
        classification = EXTRACT_SCHEMA["properties"]["depth_classification"]
        self.assertEqual(classification["properties"]["category"]["enum"], [*DEPTH_FIELDS, None])
        self.assertFalse(classification["additionalProperties"])

    def test_each_category_maps_to_one_existing_field_and_its_depth(self):
        for level, field in enumerate(DEPTH_FIELDS, 3):
            with self.subTest(field=field):
                info = self.extract({
                    "target_work": "設備点検", "practices": ["温度を確認"],
                    "depth_classification": {"category": field, "facts": ["本人が明示した説明"]},
                })
                self.assertEqual([key for key in DEPTH_FIELDS if info[key]], [field])
                self.assertEqual(info[field], ["本人が明示した説明"])
                self.assertNotIn("depth_classification", info)
                state = update_state(initial_state(), info)
                self.assertEqual(state["task_depth"], level)
                self.assertTrue(state["practice_covered"])

    def test_parallel_arrays_from_nonconforming_model_keep_only_shallower_category(self):
        for shallow, deep in itertools.combinations(DEPTH_FIELDS, 2):
            with self.subTest(shallow=shallow, deep=deep):
                info = self.extract({
                    "target_work": "設備点検", shallow: ["浅い分類の説明"], deep: ["深い分類かもしれない説明"],
                })
                self.assertEqual([field for field in DEPTH_FIELDS if info[field]], [shallow])
                self.assertEqual(update_state(initial_state(), info)["task_depth"], DEPTH_FIELDS.index(shallow) + 3)

    def test_reason_and_value_conflict_does_not_raise_depth_to_five(self):
        info = self.extract({
            "target_work": "設備点検", "reasons": ["安全のために必要だから"],
            "depth_classification": {"category": "values", "facts": ["安全が重要だから"]},
        })
        state = update_state(initial_state(), info)
        self.assertEqual(info["values"], [])
        self.assertEqual(state["task_depth"], 3)
        self.assertEqual(state["high_depth_turn_count"], 0)
        self.assertFalse(any(fact.startswith("価値観:") for fact in state["known_facts"]))

    def test_abstention_and_invalid_classification_do_not_add_depth(self):
        for classification in (
            {"category": None, "facts": []},
            {"category": "unknown", "facts": ["推測"]},
            {"category": ["reasons", "values"], "facts": ["推測"]},
            {"category": "values", "facts": "配列ではない"},
            {"category": "values", "facts": [None, " "]},
        ):
            with self.subTest(classification=classification):
                info = self.extract({"target_work": "設備点検", "practices": ["点検した"],
                                     "depth_classification": classification})
                self.assertFalse(any(info[field] for field in DEPTH_FIELDS))
                self.assertEqual(update_state(initial_state(), info)["task_depth"], 2)

    def test_other_extraction_fields_and_deep_dive_flags_remain_independent(self):
        independent = {
            "target_work": "設備点検", "practices": ["温度確認"], "fram_control": ["点検手順書"],
            "fram_time": ["2時間おき"], "irregular_situations": ["異常な温度"],
            "irregular_responses": ["停止"], "irregular_reasons": ["事故を防ぐ"],
            "irregular_deeper_reasons": ["同僚の安全を守る"],
            "deep_dive_opportunity": False, "deep_dive_anchor": "二組で回す",
            "deep_dive_reason_answered": True, "deep_dive_needs_clarification": False,
        }
        info = self.extract({**independent, "depth_classification": {
            "category": "reasons", "facts": [" 事故を防ぐ ", "事故を防ぐ"],
        }})
        for field, expected in independent.items():
            self.assertEqual(info[field], expected)
        self.assertEqual(info["reasons"], ["事故を防ぐ"])
        state = update_state(initial_state(), info)
        self.assertEqual(state["task_depth"], 3)
        self.assertEqual(state["irregular_coverage"], 0.6)

    def test_a_later_explicit_value_can_increase_depth_without_parallel_categories(self):
        state = update_state(initial_state(), self.extract({
            "target_work": "設備点検", "depth_classification": {"category": "reasons", "facts": ["安全のため"]},
        }))
        self.assertEqual(state["task_depth"], 3)
        state = update_state(state, self.extract({
            "depth_classification": {"category": "values", "facts": ["速さよりも仲間が無事に帰れることを優先したい"]},
        }))
        self.assertEqual(state["task_depth"], 5)

    def test_inference_failure_preserves_practice_only_fallback(self):
        with patch("interview.agent.configured", return_value=True), \
             patch("interview.agent.complete_json", AsyncMock(side_effect=RuntimeError("unavailable"))):
            info = asyncio.run(extract_turn("設備の温度を確認しました", initial_state(), []))
        self.assertTrue(info["practices"])
        self.assertFalse(any(info[field] for field in DEPTH_FIELDS))
