"""流水线的单元测试。

这里用一个**假引擎**（上标标记 + 保留占位符）代替 Argos，
既验证 prepare/finish 两阶段、也验证降级策略；
同时用「会吞掉占位符的引擎」验证丢失告警与术语附录。
"""
import unittest

from libretranslate.campus.glossary import Glossary, Term
from libretranslate.campus.noise import AbbreviationBook, Abbreviation
from libretranslate.campus.pipeline import (
    CampusOptions,
    CampusTranslator,
    build_campus_translator,
)


GLOSSARY = Glossary([
    Term(zh="数据结构", ru="структуры данных", domain="cs"),
    Term(zh="操作系统", ru="операционная система", domain="cs"),
], name="unit")


def echo_engine(texts, source, target):
    """原样返回（占位符全部保留）。"""
    return list(texts)


def prefix_engine(texts, source, target):
    """模拟"翻译"：加前缀，保留占位符。"""
    return ["ПЕРЕВОД: " + text for text in texts]


def dropping_engine(texts, source, target):
    """模拟会吞占位符的引擎。"""
    import re

    return [re.sub(r"\[\[T\d+\]\]", "нечто", text) for text in texts]


class PrepareFinishTest(unittest.TestCase):
    def setUp(self):
        self.translator = CampusTranslator(prefix_engine, glossary=GLOSSARY)

    def test_prepare_masks_glossary_and_noise(self):
        request = self.translator.prepare(
            "数据结构课上讲到 3-412 教室。", CampusOptions()
        )
        self.assertIn("[[T1]]", request.text)
        self.assertIn("[[T2]]", request.text)
        self.assertEqual(len(request.matches), 1)
        self.assertEqual([rule for rule, _ in request.protected], ["room"])

    def test_finish_restores_terms(self):
        request = self.translator.prepare("数据结构是核心课。", CampusOptions())
        result = self.translator.finish(request, "ПЕРЕВОД: " + request.text)
        self.assertEqual(result.text, "ПЕРЕВОД: структуры данных 是核心课.")
        self.assertEqual(result.restore_rate, 1.0)
        self.assertEqual(result.warnings, [])

    def test_translate_roundtrip_with_audit_info(self):
        result = self.translator.translate("操作系统与数据结构。", CampusOptions())
        self.assertIn("операционная система", result.text)
        self.assertIn("структуры данных", result.text)
        self.assertEqual(len(result.matches), 2)
        payload = result.to_dict()
        self.assertEqual(payload["placeholderRestoreRate"], 1.0)
        self.assertEqual(len(payload["glossaryMatches"]), 2)

    def test_noise_is_restored_unchanged(self):
        result = self.translator.translate("请到 3-412 教室，邮箱 a@b.cn。", CampusOptions())
        self.assertIn("3-412", result.text)
        self.assertIn("a@b.cn", result.text)

    def test_disabled_options_keep_upstream_behaviour(self):
        result = self.translator.translate("数据结构", CampusOptions(use_glossary=False,
                                                               protect_noise=False))
        self.assertEqual(result.text, "ПЕРЕВОД: 数据结构")
        self.assertEqual(result.matches, [])


class DegradationTest(unittest.TestCase):
    def setUp(self):
        self.translator = CampusTranslator(dropping_engine, glossary=GLOSSARY)

    def test_lost_placeholder_is_warned_and_appended(self):
        result = self.translator.translate("数据结构", CampusOptions())
        self.assertTrue(result.warnings)
        self.assertIn("术语对照", result.text)
        self.assertIn("структуры данных", result.text)
        self.assertEqual(result.restore_rate, 0.0)

    def test_appendix_can_be_switched_off(self):
        result = self.translator.translate(
            "数据结构", CampusOptions(glossary_appendix_on_loss=False)
        )
        self.assertNotIn("术语对照", result.text)
        self.assertTrue(result.warnings)

    def test_engine_exception_becomes_warning(self):
        def broken(texts, source, target):
            raise RuntimeError("engine down")

        translator = CampusTranslator(broken, glossary=GLOSSARY)
        result = translator.translate("数据结构", CampusOptions())
        self.assertIn("引擎报错", " ".join(result.warnings))
        self.assertEqual(result.text, "структуры данных")


class OptionTest(unittest.TestCase):
    def test_from_flags_campus_switch(self):
        opts = CampusOptions.from_flags("zh", "ru", campus=True)
        self.assertTrue(opts.use_glossary)
        self.assertTrue(opts.protect_noise)
        self.assertTrue(opts.enabled)

    def test_from_flags_explicit_override(self):
        opts = CampusOptions.from_flags("zh", "ru", campus=True, glossary=False, protect=False)
        self.assertFalse(opts.use_glossary)
        self.assertFalse(opts.protect_noise)
        self.assertFalse(opts.enabled)

    def test_terms_only_needs_no_engine(self):
        translator = CampusTranslator(None, glossary=GLOSSARY)
        out = translator.terms_only("数据结构与操作系统", "zh", "ru")
        self.assertEqual(out, "структуры данных 与 операционная система")

    def test_bilingual_alignment(self):
        source = "第一句讲数据结构。第二句讲操作系统。"
        result = self.translator_bilingual(source)
        self.assertEqual(len(result.doc.pairs), 2)
        self.assertTrue(result.doc.render("interleaved"))

    def translator_bilingual(self, source):
        translator = CampusTranslator(prefix_engine, glossary=GLOSSARY)

        def session_engine(texts, s, t):
            # 逐句翻译，模拟真实引擎的句级输出
            from libretranslate.campus.templates import split_sentences

            out = []
            for text in texts:
                out.append(" ".join("ПЕРЕВОД " + s for s in split_sentences(text, "zh")))
            return out

        translator.translate_fn = session_engine
        return translator.bilingual(source)

    def test_status_reports_configuration(self):
        translator = CampusTranslator(echo_engine, glossary=GLOSSARY)
        status = translator.status()
        self.assertEqual(status["glossary"]["count"], 2)
        self.assertIn("course_code", status["protectRules"])
        self.assertGreater(status["nameDictionary"], 50)


class BuilderTest(unittest.TestCase):
    def test_builder_without_data_files_still_works(self):
        translator = build_campus_translator(echo_engine, glossary_dir="/nonexistent/path")
        self.assertEqual(len(translator.glossary), 0)
        result = translator.translate("你好", CampusOptions())
        self.assertEqual(result.text, "你好")

    def test_builder_with_abbreviation_book(self):
        translator = CampusTranslator(
            echo_engine, glossary=GLOSSARY,
            abbreviations=AbbreviationBook([Abbreviation(short="深北莫", lang="zh",
                                                         full="深圳北理莫斯科大学")]),
        )
        result = translator.translate("深北莫", CampusOptions(expand_abbreviations=True))
        self.assertIn("深圳北理莫斯科大学", result.text)


if __name__ == "__main__":
    unittest.main()
