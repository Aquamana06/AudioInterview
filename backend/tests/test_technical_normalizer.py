import unittest

from whisper.terminology import normalize_technical_terms


class TechnicalNormalizerTests(unittest.TestCase):
    def test_tower_homophone_requires_an_equipment_attribute(self):
        for source, expected in (
            ("15等の温度を確認しました", "重合塔の温度を確認しました"),
            ("次に１５等の圧力を見ました", "次に重合塔の圧力を見ました"),
            ("十五等内の液面が上がりました", "重合塔内の液面が上がりました"),
            ("じゅうごう塔を点検しました", "重合塔を点検しました"),
        ):
            with self.subTest(source=source):
                self.assertEqual(normalize_technical_terms(source), expected)

    def test_numbers_grades_building_ids_and_ambiguous_phrases_are_preserved(self):
        for text in (
            "温度は15度です", "温度は115度です", "15。", "15、20、25です",
            "重合度は15です", "15分待って15個回収しました", "15等の賞品です",
            "15棟の温度を確認しました", "215等の温度", "第15等の温度",
            "0.15等の温度", "1〜15等の温度", "15等で作業しました",
            "樹脂をろ過したケーキを回収しました",
        ):
            with self.subTest(text=text):
                self.assertEqual(normalize_technical_terms(text), text)
