"""术语库的单元测试。"""
import json
import os
import unittest

from libretranslate.campus.glossary import Glossary, Term
from libretranslate.tests.campus._support import cleanup, scratch_dir


TERMS = [
    Term(zh="数据结构", ru="структуры данных", en="data structures", domain="cs"),
    Term(zh="操作系统", ru="операционная система", en="operating system", domain="cs"),
    Term(zh="学分", ru="зачётная единица", en="credit", domain="admin", note="俄方亦作 кредит"),
]


class GlossaryTest(unittest.TestCase):
    def setUp(self):
        self.glossary = Glossary(list(TERMS), name="unit")

    def test_stats_and_domains(self):
        stats = self.glossary.stats()
        self.assertEqual(stats["count"], 3)
        self.assertEqual(stats["domains"]["cs"], 2)
        self.assertEqual(stats["with_note"], 1)

    def test_match_longest_wins(self):
        g = Glossary([Term(zh="数据", ru="данные"), Term(zh="数据结构", ru="структуры данных")])
        matches = g.match("数据结构课", "zh", "ru")
        self.assertEqual(len(matches), 1)
        self.assertEqual(matches[0].origin, "数据结构")

    def test_match_is_case_insensitive_for_russian(self):
        matches = self.glossary.match("Курс: СТРУКТУРЫ ДАННЫХ", "ru", "zh")
        self.assertEqual(len(matches), 1)
        self.assertEqual(matches[0].value, "数据结构")

    def test_yo_and_ye_are_interchangeable(self):
        g = Glossary([Term(zh="索洛维约夫", ru="Соловьёв")])
        self.assertTrue(g.match("Соловьев", "ru", "zh"))

    def test_mask_then_restore_roundtrip(self):
        outcome = self.glossary.mask("本课程讲授数据结构。", "zh", "ru")
        # 遮蔽时会顺手在中文与占位符之间补空格，避免回填后中外文粘连
        self.assertEqual(outcome.text, "本课程讲授 [[T1]]。")
        # 模拟引擎：中文外壳被翻译、占位符原样保留
        translated = outcome.text.replace("本课程讲授", "Курс охватывает").replace("。", ".")
        restored = self.glossary.restore(translated, outcome.table)
        self.assertEqual(restored.text, "Курс охватывает структуры данных.")
        self.assertTrue(restored.ok)

    def test_mask_non_strict_does_not_add_placeholders(self):
        outcome = self.glossary.mask("操作系统", "zh", "ru", strict=False)
        self.assertEqual(outcome.text, "операционная система")

    def test_english_source_is_supported(self):
        matches = self.glossary.match("Data structures and algorithms", "en", "ru")
        self.assertEqual(matches[0].value, "структуры данных")

    def test_translate_terms(self):
        table = self.glossary.translate_terms("zh", "ru")
        self.assertEqual(table["学分"], "зачётная единица")

    def test_coverage(self):
        self.assertAlmostEqual(self.glossary.coverage("数据结构", "zh", "ru"), 1.0)
        self.assertAlmostEqual(self.glossary.coverage("数据结构abc", "zh", "ru"), 4 / 7)

    def test_unknown_candidates_lists_unregistered_chunks(self):
        found = self.glossary.unknown_candidates("本课程讲授编译原理")
        self.assertTrue(any("编译" in item for item in found))

    def test_validate_flags_duplicates_and_ambiguity(self):
        g = Glossary([
            Term(zh="学分", ru="зачётная единица"),
            Term(zh="学分", ru="зачётная единица"),
            Term(zh="选修课", ru="дисциплина по выбору"),
            Term(zh="选修课", ru="факультатив"),
        ])
        codes = sorted(issue.code for issue in g.validate())
        self.assertIn("GLOSSARY_DUPLICATE", codes)
        self.assertIn("GLOSSARY_AMBIGUOUS_NO_NOTE", codes)

    def test_validate_flags_script_mixups(self):
        g = Glossary([Term(zh="数据结构", ru="структуры data"), Term(zh="操作系统", ru="операционная 系统")])
        codes = sorted(issue.code for issue in g.validate())
        self.assertIn("GLOSSARY_LATIN_IN_RU", codes)
        self.assertIn("GLOSSARY_CJK_IN_RU", codes)

    def test_json_roundtrip(self):
        payload = json.loads(self.glossary.to_json())
        self.assertEqual(payload["name"], "unit")
        folder = scratch_dir("glossary-roundtrip")
        try:
            path = os.path.join(folder, "campus_zh_ru.json")
            self.glossary.save(path)
            reloaded = Glossary.from_json_file(path)
            self.assertEqual(len(reloaded), 3)
            self.assertEqual(reloaded.name, "unit")
            # 文件里没写 name 时，用文件名兜底
            payload = json.loads(self.glossary.to_json())
            payload.pop("name")
            with open(path, "w", encoding="utf-8") as fh:
                json.dump(payload, fh, ensure_ascii=False)
            self.assertEqual(Glossary.from_json_file(path).name, "campus_zh_ru")
        finally:
            cleanup(folder)

    def test_load_profile_from_directory(self):
        folder = scratch_dir("glossary-profile")
        try:
            with open(os.path.join(folder, "campus_zh_ru.json"), "w", encoding="utf-8") as fh:
                fh.write(self.glossary.to_json())
            with open(os.path.join(folder, "campus_noise.json"), "w", encoding="utf-8") as fh:
                fh.write(json.dumps({"abbreviations": [], "names": []}))
            loaded = Glossary.from_json_dir(folder, profile="campus_zh_ru")
            self.assertEqual(len(loaded), 3)
        finally:
            cleanup(folder)

    def test_repository_glossary_is_valid(self):
        """仓库自带的术语库必须能加载且没有 error 级问题。"""
        repo_root = os.path.dirname(os.path.dirname(os.path.dirname(
            os.path.dirname(os.path.abspath(__file__)))))
        folder = os.path.join(repo_root, "data", "glossary")
        if not os.path.isdir(folder):
            self.skipTest("glossary data directory not present")
        glossary = Glossary.from_json_dir(folder, profile="campus_zh_ru")
        self.assertGreater(len(glossary), 50)
        errors = [issue for issue in glossary.validate() if issue.severity == "error"]
        self.assertEqual(errors, [], "术语库存在 error 级问题：%s" % errors)


if __name__ == "__main__":
    unittest.main()
