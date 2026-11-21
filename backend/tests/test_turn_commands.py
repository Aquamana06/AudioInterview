import unittest

from whisper.terminology.turn_commands import split_turn_command


class TurnCommandTests(unittest.TestCase):
    def test_spelling_punctuation_and_width_variations(self):
        for command in (
            "オーバー", "オーバ", "オバ", "オバー", "おーばー", "おーば",
            "おおばー", "おば", "おばー", "ｵｰﾊﾞｰ", "over", "OVER", "ＯＶＥＲ",
        ):
            for punctuation in ("", "、", "。", "，", "．", "！？", "…", "\"", "」", " \n"):
                with self.subTest(command=command, punctuation=punctuation):
                    text = "確認しました。 " + command + punctuation
                    self.assertEqual(split_turn_command(text), ("確認しました。", True))
                    self.assertEqual(split_turn_command(command + punctuation), ("", True))

    def test_repeated_and_quoted_commands_are_removed(self):
        self.assertEqual(split_turn_command("確認しました。オーバー、オーバー。"), ("確認しました。", True))
        self.assertEqual(split_turn_command("確認しました。「おばー」"), ("確認しました。", True))
        self.assertEqual(split_turn_command("確認しましたオーバー，"), ("確認しました", True))

    def test_words_and_commands_inside_an_answer_do_not_end_the_turn(self):
        for text in (
            "", "。", "オーバーフローを確認しました", "オーバーホール", "タイムオーバー",
            "あおば", "アオバ", "おばさん", "おばけ", "coverage", "leftover", "game over time",
            "オーバーと言ってから停止します", "おば、と認識されました",
        ):
            with self.subTest(text=text):
                self.assertEqual(split_turn_command(text), (text, False))
