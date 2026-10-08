"""句对齐与模板的单元测试。"""
import unittest

from libretranslate.campus.templates import (
    BilingualDoc,
    NoticeFields,
    align_pairs,
    email_template,
    notice_template,
    slide_title_template,
    split_sentences,
)


class SplitSentencesTest(unittest.TestCase):
    def test_chinese_sentences(self):
        self.assertEqual(split_sentences("第一句。第二句！第三句？", "zh"),
                         ["第一句。", "第二句！", "第三句？"])

    def test_russian_initials_are_not_sentence_breaks(self):
        text = "И.И. Иванов пришёл. Он учится в МГУ-ППИ."
        self.assertEqual(split_sentences(text, "ru"),
                         ["И.И. Иванов пришёл.", "Он учится в МГУ-ППИ."])

    def test_russian_abbreviations_and_decimals(self):
        text = "См. рис. 3. Температура 3.14 градуса. Т.е. всё нормально."
        sentences = split_sentences(text, "ru")
        self.assertEqual(len(sentences), 3)
        self.assertIn("3.14", sentences[1])

    def test_empty_input(self):
        self.assertEqual(split_sentences("", "zh"), [])


class AlignPairsTest(unittest.TestCase):
    def test_one_to_one(self):
        result = align_pairs(["甲。", "乙。"], ["А.", "Б."])
        self.assertEqual(result.quality, 1.0)
        self.assertTrue(all(pair.ok for pair in result.pairs))

    def test_merge_when_translation_has_more_sentences(self):
        result = align_pairs(["甲。", "乙。"], ["А.", "Б.", "В."])
        self.assertEqual(len(result.pairs), 2)
        self.assertEqual(result.pairs[0].method, "merge")
        self.assertTrue(result.warnings)

    def test_split_when_translation_has_fewer_sentences(self):
        result = align_pairs(["甲。", "乙。", "丙。"], ["А.", "Б."])
        self.assertEqual(len(result.pairs), 2)
        self.assertEqual(result.pairs[0].method, "split")

    def test_empty_translation_is_marked(self):
        result = align_pairs(["甲。"], [])
        self.assertEqual(result.pairs[0].method, "unmatched")
        self.assertEqual(result.quality, 0.0)


class TemplateTest(unittest.TestCase):
    def test_notice_template_labels(self):
        fields = NoticeFields(title="选课通知", audience="全体本科生", body="请于本周五前完成选课。",
                              issuer="教务处", date="2026年5月12日", contact="jw@smbu.edu.cn")
        zh = notice_template(fields, "zh")
        ru = notice_template(fields, "ru")
        self.assertIn("标题：选课通知", zh)
        self.assertIn("Тема: 选课通知", ru)
        self.assertTrue(ru.rstrip().endswith("jw@smbu.edu.cn"))

    def test_email_template_uses_courtesy_lines(self):
        fields = NoticeFields(body="请提交材料。", issuer="Иванов И.И.")
        ru = email_template(fields, "ru")
        self.assertIn("Уважаемые преподаватели и студенты!", ru)
        self.assertIn("С уважением,", ru)
        zh = email_template(fields, "zh")
        self.assertIn("尊敬的老师、同学：", zh)

    def test_slide_title_template(self):
        out = slide_title_template("课程介绍", ["算法复杂度", "数据结构"])
        self.assertTrue(out.startswith("# 课程介绍"))
        self.assertEqual(out.count("- "), 2)


class BilingualDocTest(unittest.TestCase):
    def setUp(self):
        self.doc = BilingualDoc(
            title_zh="选课通知",
            title_ru="Объявление о выборе дисциплин",
            pairs=align_pairs(["第一句。", "第二句。"], ["Первое.", "Второе."]).pairs,
            meta={"术语命中": "2"},
            warnings=["示例提示"],
        )

    def test_interleaved_render(self):
        out = self.doc.render("interleaved")
        self.assertIn("## Объявление", out)
        self.assertIn("第一句。", out)
        self.assertIn("Первое.", out)
        self.assertIn("对齐提示", out)

    def test_table_render_has_header(self):
        out = self.doc.render("table", left_label="中文", right_label="Русский")
        self.assertIn("| 中文 | Русский |", out)
        self.assertIn("| --- | --- |", out)

    def test_side_by_side_and_paragraph_render(self):
        self.assertIn("｜", self.doc.render("side-by-side"))
        self.assertIn("第一句。\nПервое.", self.doc.render("paragraph"))

    def test_unknown_layout_raises(self):
        with self.assertRaises(ValueError):
            self.doc.render("diagonal")

    def test_render_plain(self):
        plain = self.doc.render_plain()
        self.assertIn("选课通知", plain)
        self.assertIn("Второе.", plain)


if __name__ == "__main__":
    unittest.main()
