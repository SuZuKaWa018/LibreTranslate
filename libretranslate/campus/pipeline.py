"""校园翻译流水线（Campus translation pipeline）。

一条完整的"中俄校园"翻译链路：

    normalize → 缩写展开 → 术语遮蔽 → 编号保护 → 机器翻译 → 排版清理 → 占位符回填

关键点是**引擎可注入**：:class:`CampusTranslator` 只要求一个
``translate_fn(texts, source, target) -> List[str]`` 回调，
既能接 LibreTranslate 自己的 Argos 引擎，也能接任何外部/测试用的假引擎。
因此本模块可以在没有语言模型的环境里做完整的单元测试，
这一点对课程作业式的小团队很重要：CI 不需要下载 GB 级模型也能跑。

链路分成两段，方便嵌入已有的 Flask 视图：

* :meth:`CampusTranslator.prepare` —— 生成待翻译文本与占位符表；
* :meth:`CampusTranslator.finish` —— 拿到引擎译文后回填并给出审计信息。

用法（不接模型，只做术语直出）::

    from libretranslate.campus import Glossary, CampusTranslator

    g = Glossary.from_json_dir("data/glossary", profile="campus_zh_ru")
    tr = CampusTranslator(lambda texts, s, t: texts)   # 直通引擎
    print(tr.translate("数据结构与操作系统", source="zh", target="ru").text)
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Callable, Dict, List, Optional, Sequence, Tuple

from .glossary import Glossary, GlossaryMatch
from .noise import (
    AbbreviationBook,
    NameGuess,
    NameTransliterator,
    NoiseProtector,
    clean_translation,
    normalize_source,
)
from .placeholders import PlaceholderTable, RestoreResult
from .templates import AlignmentResult, BilingualDoc, align_pairs, split_sentences

TranslateFn = Callable[[Sequence[str], str, str], Sequence[str]]


@dataclass
class CampusOptions:
    """一次翻译的开关集合。"""

    source: str = "zh"
    target: str = "ru"
    use_glossary: bool = True
    glossary_strict: bool = True          # True=占位符保护；False=术语直出替换
    protect_noise: bool = True
    protect_rules: Optional[Sequence[str]] = None
    normalize_input: bool = True
    clean_output: bool = True
    expand_abbreviations: bool = False
    suggest_names: bool = False
    glossary_appendix_on_loss: bool = True  # 占位符丢失时，在译文后附术语对照
    batch_size: int = 32

    @classmethod
    def from_flags(cls, source: str, target: str, campus: bool = False,
                   glossary: Optional[bool] = None, protect: Optional[bool] = None,
                   strict: Optional[bool] = None, names: Optional[bool] = None,
                   **kwargs) -> "CampusOptions":
        """由 HTTP 参数构造：``campus=true`` 一键开启全部增强。"""
        opts = cls(source=source, target=target, **kwargs)
        if campus:
            opts.use_glossary = True
            opts.protect_noise = True
        if glossary is not None:
            opts.use_glossary = bool(glossary)
        if protect is not None:
            opts.protect_noise = bool(protect)
        if strict is not None:
            opts.glossary_strict = bool(strict)
        if names is not None:
            opts.suggest_names = bool(names)
        return opts

    @property
    def enabled(self) -> bool:
        return bool(self.use_glossary or self.protect_noise or self.suggest_names)


@dataclass
class MaskedRequest:
    """遮蔽后的待翻译请求（交给引擎之前的中间状态）。"""

    text: str
    original: str
    table: PlaceholderTable = field(default_factory=PlaceholderTable)
    matches: List[GlossaryMatch] = field(default_factory=list)
    protected: List[Tuple[str, str]] = field(default_factory=list)
    names: List[NameGuess] = field(default_factory=list)
    coverage: float = 0.0
    options: CampusOptions = field(default_factory=CampusOptions)

    @property
    def changed(self) -> bool:
        return self.text != self.original


@dataclass
class CampusResult:
    """一次翻译的完整结果（含可审计信息）。"""

    text: str
    source: str = "zh"
    target: str = "ru"
    masked_text: str = ""
    matches: List[GlossaryMatch] = field(default_factory=list)
    protected: List[Tuple[str, str]] = field(default_factory=list)
    names: List[NameGuess] = field(default_factory=list)
    warnings: List[str] = field(default_factory=list)
    restore: Optional[RestoreResult] = None
    glossary_coverage: float = 0.0

    @property
    def restore_rate(self) -> float:
        return self.restore.restore_rate if self.restore else 1.0

    @property
    def has_issues(self) -> bool:
        return bool(self.warnings)

    def terms_used(self) -> List[Tuple[str, str]]:
        return [(m.term.zh, m.value) for m in self.matches]

    def to_dict(self) -> Dict[str, object]:
        return {
            "translatedText": self.text,
            "maskedText": self.masked_text,
            "source": self.source,
            "target": self.target,
            "glossaryMatches": [
                {"origin": m.origin, "target": m.value, "domain": m.term.domain,
                 "zh": m.term.zh, "ru": m.term.ru}
                for m in self.matches
            ],
            "protected": [{"rule": rule, "text": text} for rule, text in self.protected],
            "nameSuggestions": [
                {"source": g.source, "han": g.han, "method": g.method,
                 "confidence": g.confidence, "review": g.review} for g in self.names
            ],
            "glossaryCoverage": round(self.glossary_coverage, 4),
            "placeholderRestoreRate": round(self.restore_rate, 4),
            "warnings": list(self.warnings),
        }


@dataclass
class BilingualOutcome:
    """中俄对照结果。"""

    doc: BilingualDoc
    result: Optional[CampusResult] = None
    alignment: Optional[AlignmentResult] = None


class CampusTranslator:
    """把术语库、噪音保护、对齐排版串成一条链路。"""

    def __init__(self, translate_fn: TranslateFn,
                 glossary: Optional[Glossary] = None,
                 protector: Optional[NoiseProtector] = None,
                 abbreviations: Optional[AbbreviationBook] = None,
                 names: Optional[NameTransliterator] = None):
        self.translate_fn = translate_fn
        # 注意用 is None 判断：空术语库/空词表在布尔上下文里是 False，
        # 用 `or` 会悄悄换成默认实例，导致传入的（空）表被丢弃。
        self.glossary = Glossary() if glossary is None else glossary
        self.protector = NoiseProtector() if protector is None else protector
        self.abbreviations = AbbreviationBook() if abbreviations is None else abbreviations
        self.names = NameTransliterator() if names is None else names

    # -- 阶段一：遮蔽 -------------------------------------------------------
    def prepare(self, text: str, options: Optional[CampusOptions] = None,
                **kwargs) -> MaskedRequest:
        opts = options or CampusOptions(**kwargs)
        original = text or ""
        working = original
        if opts.normalize_input:
            working = normalize_source(working, opts.source)
        if opts.expand_abbreviations and len(self.abbreviations):
            working = self.abbreviations.expand(working, mode="parenthetical")

        table = PlaceholderTable()
        matches: List[GlossaryMatch] = []
        protected: List[Tuple[str, str]] = []
        if opts.use_glossary and len(self.glossary):
            outcome = self.glossary.mask(working, opts.source, opts.target,
                                         strict=opts.glossary_strict, table=table)
            working = outcome.text
            matches = outcome.matches
        if opts.protect_noise:
            outcome_p = self.protector.protect(working, opts.protect_rules, table=table)
            working = outcome_p.text
            protected = outcome_p.hits

        request = MaskedRequest(text=working, original=original, table=table,
                                matches=matches, protected=protected, options=opts,
                                coverage=self.glossary.coverage(original, opts.source, opts.target)
                                if len(self.glossary) else 0.0)
        if opts.suggest_names:
            request.names = self.names.scan(original)
        return request

    # -- 阶段二：回填 -------------------------------------------------------
    def finish(self, request: MaskedRequest, translated: str) -> CampusResult:
        opts = request.options
        result = CampusResult(text="", source=opts.source, target=opts.target,
                              masked_text=request.text, matches=request.matches,
                              protected=request.protected, names=request.names,
                              glossary_coverage=request.coverage)
        text = translated or ""
        if opts.clean_output:
            text = clean_translation(text, opts.target)
        restore = request.table.restore(text)
        result.restore = restore
        result.text = restore.text
        if restore.lost:
            result.warnings.append(
                "占位符丢失 %d 处（术语/编号未按预期保留）：%s"
                % (len(restore.lost), "、".join(slot.origin for slot in restore.lost[:5]))
            )
            if opts.glossary_appendix_on_loss:
                appendix = _appendix(restore.lost)
                if appendix:
                    result.text = result.text.rstrip() + "\n\n" + appendix
        if restore.duplicated:
            result.warnings.append("占位符重复出现 %d 处，已按术语表回填" % len(restore.duplicated))
        return result

    # -- 组合 ---------------------------------------------------------------
    def translate(self, text: str, options: Optional[CampusOptions] = None,
                  **kwargs) -> CampusResult:
        request = self.prepare(text, options, **kwargs)
        if not request.text.strip():
            return self.finish(request, "")
        try:
            outputs = list(self.translate_fn([request.text], request.options.source,
                                             request.options.target))
        except Exception as exc:  # 引擎异常不应静默：包装成可读警告
            result = self.finish(request, request.text)
            result.warnings.append("翻译引擎报错：%s" % exc)
            return result
        return self.finish(request, outputs[0] if outputs else "")

    def translate_many(self, texts: Sequence[str], options: Optional[CampusOptions] = None,
                       **kwargs) -> List[CampusResult]:
        opts = options or CampusOptions(**kwargs)
        return [self.translate(item, opts) for item in texts]

    # -- 术语直出（不需要模型） --------------------------------------------
    def terms_only(self, text: str, source: str = "zh", target: str = "ru") -> str:
        """只用术语库替换，不调用模型；离线/应急场景可用。"""
        masked = self.glossary.mask(text or "", source, target, strict=False)
        protected = self.protector.protect(masked.text)
        return protected.table.restore(protected.text).text

    # -- 中俄对照 -----------------------------------------------------------
    def bilingual(self, text: str, source: str = "zh", target: str = "ru",
                  layout: str = "interleaved", options: Optional[CampusOptions] = None,
                  title: Optional[str] = None) -> BilingualOutcome:
        """把一段文本翻成中俄对照文档（逐句对齐）。"""
        source_sentences = split_sentences(text, source)
        result = self.translate(text, options or CampusOptions(source=source, target=target))
        target_sentences = split_sentences(result.text, target)
        alignment = align_pairs(source_sentences, target_sentences)
        doc = BilingualDoc(
            title_zh=title or "",
            title_ru=title if target.startswith("ru") and title else "",
            pairs=list(alignment.pairs),
            warnings=list(alignment.warnings) + list(result.warnings),
            meta={"术语命中": str(len(result.matches)),
                  "术语回填率": "%.0f%%" % (result.restore_rate * 100),
                  "版式": layout},
        )
        return BilingualOutcome(doc=doc, result=result, alignment=alignment)

    # -- 运行状态 -----------------------------------------------------------
    def status(self) -> Dict[str, object]:
        return {
            "glossary": self.glossary.stats() if len(self.glossary) else {"count": 0},
            "protectRules": [p.name for p in self.protector.patterns],
            "abbreviations": len(self.abbreviations),
            "nameDictionary": len(self.names.dictionary),
        }


def _appendix(lost: Sequence[object]) -> str:
    """占位符丢失时附上术语对照，保证读者至少能看到正确译法。"""
    lines: List[str] = []
    for slot in lost:
        meta = getattr(slot, "meta", {}) or {}
        origin = getattr(slot, "origin", "")
        value = getattr(slot, "value", "")
        if not value:
            continue
        if meta.get("domain"):
            lines.append("* %s — %s（%s）" % (origin, value, meta.get("domain")))
        else:
            lines.append("* %s — %s" % (origin, value))
    if not lines:
        return ""
    return "术语对照（机翻未保留，供人工确认）：\n" + "\n".join(lines)


def build_campus_translator(translate_fn: TranslateFn, glossary_dir: Optional[str] = None,
                            profile: Optional[str] = None,
                            noise_file: Optional[str] = None) -> CampusTranslator:
    """按目录/文件装配一条校园翻译链路（缺文件时退回内置默认值）。"""
    import os

    glossary = Glossary()
    if glossary_dir and os.path.isdir(glossary_dir):
        try:
            glossary = Glossary.from_json_dir(glossary_dir, profile=profile)
        except (OSError, ValueError):
            glossary = Glossary()
    abbreviations = AbbreviationBook()
    names = NameTransliterator()
    if noise_file and os.path.exists(noise_file):
        abbreviations = AbbreviationBook.from_json_file(noise_file)
        names = NameTransliterator.from_json_file(noise_file)
    return CampusTranslator(translate_fn, glossary=glossary,
                            abbreviations=abbreviations, names=names)
