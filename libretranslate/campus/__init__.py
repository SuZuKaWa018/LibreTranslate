"""中俄双语校园翻译增强（Campus ZH⇄RU toolkit）。

这个包是 LibreTranslate 的一个**面向场景的增强层**，服务于中外合作办学
（以深圳北理莫斯科大学为代表）里的中俄双语场景：课程术语、教学通知、
邮件、课件标题、成绩与学籍材料等。

模块划分：

* :mod:`libretranslate.campus.placeholders` —— 占位符保护与回填；
* :mod:`libretranslate.campus.glossary` —— 校园术语库（加载/匹配/遮蔽/自检）；
* :mod:`libretranslate.campus.noise` —— 校园噪音：编号保护、姓名音译、缩写展开；
* :mod:`libretranslate.campus.templates` —— 句对齐与通知/邮件/课件模板；
* :mod:`libretranslate.campus.pipeline` —— 串起整条链路（引擎可注入）。

设计原则：**不把语言模型当作依赖**。除 :func:`CampusTranslator.translate`
会调用注入的翻译回调外，其余功能都是纯逻辑，可在无模型环境下单元测试。
"""
from .glossary import Glossary, GlossaryIssue, GlossaryMatch, MaskOutcome, Term
from .noise import (
    Abbreviation,
    AbbreviationBook,
    NameGuess,
    NameTransliterator,
    NoiseProtector,
    ProtectedPattern,
    clean_translation,
    normalize_source,
)
from .pipeline import (
    BilingualOutcome,
    CampusOptions,
    CampusResult,
    CampusTranslator,
    build_campus_translator,
)
from .placeholders import PlaceholderTable, RestoreResult, Slot
from .templates import (
    AlignedPair,
    AlignmentResult,
    BilingualDoc,
    NoticeFields,
    align_pairs,
    email_template,
    notice_template,
    slide_title_template,
    split_sentences,
)

__all__ = [
    "Abbreviation",
    "AbbreviationBook",
    "AlignedPair",
    "AlignmentResult",
    "BilingualDoc",
    "BilingualOutcome",
    "CampusOptions",
    "CampusResult",
    "CampusTranslator",
    "Glossary",
    "GlossaryIssue",
    "GlossaryMatch",
    "MaskOutcome",
    "NameGuess",
    "NameTransliterator",
    "NoiseProtector",
    "NoticeFields",
    "PlaceholderTable",
    "ProtectedPattern",
    "RestoreResult",
    "Slot",
    "Term",
    "align_pairs",
    "build_campus_translator",
    "clean_translation",
    "email_template",
    "normalize_source",
    "notice_template",
    "slide_title_template",
    "split_sentences",
]

__version__ = "0.1.0"
