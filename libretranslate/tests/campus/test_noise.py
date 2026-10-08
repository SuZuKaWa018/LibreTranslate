"""校园噪音处理的单元测试：编号保护、规范化、缩写、姓名音译。"""
import os
import unittest

from libretranslate.campus.noise import (
    Abbreviation,
    AbbreviationBook,
    NameTransliterator,
    NoiseProtector,
    clean_translation,
    normalize_source,
)


class NoiseProtectorTest(unittest.TestCase):
    def setUp(self):
        self.protector = NoiseProtector()

    def test_protects_course_code_room_email_date(self):
        text = "请于 2026年5月12日 到 3-412 教室，联系 ivanov@smbu.edu.cn（课程号 МА101）。"
        outcome = self.protector.protect(text)
        rules = {rule for rule, _ in outcome.hits}
        self.assertEqual(rules, {"course_code", "room", "email", "date_zh"})
        self.assertNotIn("МА101", outcome.text)
        self.assertEqual(outcome.table.restore(outcome.text).text, text)

    def test_protects_urls_and_times(self):
        outcome = self.protector.protect("详见 https://smbu.edu.cn/x 会议 14:30 开始")
        rules = {rule for rule, _ in outcome.hits}
        self.assertIn("url", rules)
        self.assertIn("time", rules)

    def test_rule_subset_can_be_selected(self):
        outcome = self.protector.protect("教室 3-412，邮箱 a@b.cn", rules=["room"])
        self.assertEqual({rule for rule, _ in outcome.hits}, {"room"})
        self.assertIn("a@b.cn", outcome.text)

    def test_shared_table_with_glossary(self):
        from libretranslate.campus.glossary import Glossary, Term

        glossary = Glossary([Term(zh="数据结构", ru="структуры данных")])
        masked = glossary.mask("数据结构", "zh", "ru")
        table = masked.table
        self.protector.protect(masked.text + " 3-412", table=table)
        restored = table.restore("[[T1]] 3-412")
        self.assertEqual(restored.text, "структуры данных 3-412")
        self.assertEqual(len(table), 2)


class NormalizeTest(unittest.TestCase):
    def test_fullwidth_punctuation_and_spacing(self):
        out = normalize_source("课程名：数据结构，教师 Иванов")
        self.assertIn(": ", out)
        self.assertIn(", ", out)
        self.assertIn("教师 Иванов", out)

    def test_clean_translation_removes_space_before_punctuation(self):
        self.assertEqual(clean_translation("Привет , мир .", "ru"), "Привет, мир.")
        self.assertEqual(clean_translation("Привет ( мир )", "ru"), "Привет (мир)")


class AbbreviationTest(unittest.TestCase):
    def setUp(self):
        self.book = AbbreviationBook([
            Abbreviation(short="深北莫", lang="zh", full="深圳北理莫斯科大学",
                         translation="Совместный университет МГУ-ППИ в Шэньчжэне"),
            Abbreviation(short="МГУ-ППИ", lang="ru", full="Совместный университет МГУ и ППИ"),
        ])

    def test_expand_parenthetical_only_first_occurrence(self):
        out = self.book.expand("深北莫的通知，深北莫教务处")
        self.assertEqual(out.count("（深圳北理莫斯科大学）"), 1)

    def test_expand_replace_and_annotate(self):
        self.assertEqual(self.book.expand("深北莫", mode="replace"), "深圳北理莫斯科大学")
        self.assertIn("注释：", self.book.expand("深北莫", mode="annotate"))

    def test_find_and_translate(self):
        self.assertEqual(len(self.book.find("深北莫通知")), 1)
        self.assertEqual(self.book.translate_short("深北莫"),
                         "Совместный университет МГУ-ППИ в Шэньчжэне")


class NameTransliteratorTest(unittest.TestCase):
    def setUp(self):
        self.names = NameTransliterator()

    def test_dictionary_wins(self):
        guess = self.names.word("Иванов")
        self.assertEqual(guess.han, "伊万诺夫")
        self.assertEqual(guess.method, "dictionary")
        self.assertFalse(guess.review)

    def test_feminine_form_is_derived(self):
        self.assertEqual(self.names.word("Смирнова").han, "斯米尔诺娃")
        self.assertEqual(self.names.word("Иванова").han, "伊万诺娃")

    def test_full_name_keeps_initials(self):
        guess = self.names.full_name("Иванов И.И.")
        self.assertEqual(guess.han, "伊万诺夫 И.И.")

    def test_unknown_name_falls_back_to_syllables_and_flags_review(self):
        guess = self.names.word("Жуковский")
        self.assertTrue(guess.review)
        self.assertTrue(all("\u4e00" <= ch <= "\u9fff" for ch in guess.han))

    def test_scan_finds_names_in_text(self):
        found = self.names.scan("Преподаватель Иванов И.И. ведёт курс.")
        self.assertTrue(any(guess.han.startswith("伊万诺夫") for guess in found))

    def test_repository_name_table_loads(self):
        repo_root = os.path.dirname(os.path.dirname(os.path.dirname(
            os.path.dirname(os.path.abspath(__file__)))))
        path = os.path.join(repo_root, "data", "glossary", "campus_noise.json")
        if not os.path.exists(path):
            self.skipTest("noise data file not present")
        translator = NameTransliterator.from_json_file(path)
        self.assertEqual(translator.word("Смирнова").han, "斯米尔诺娃")
        book = AbbreviationBook.from_json_file(path)
        self.assertGreater(len(book), 5)
        self.assertEqual(book.translate_short("深北莫"),
                         "Совместный университет МГУ-ППИ в Шэньчжэне")


if __name__ == "__main__":
    unittest.main()
