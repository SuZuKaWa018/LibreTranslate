"""中俄对照排版（Bilingual alignment & templates）。

交付要求里明确写了"一键对照排版"，也就是把一份中文通知/邮件/课件标题
变成中俄对照的成品。要做到这点，除了翻译本身还要解决两件事：

1. **句子切分**：中文用 ``。！？``，俄语用 ``.!?``，并且要避开
   ``И.И.``、``т.е.``、``12.05.2026``、``3.14`` 这类假句末；
2. **句对对齐**：模型按句翻译时句数一般一致，但遇到合句/拆句要能降级处理，
   并给出对齐质量，让人知道哪一段需要人工看一眼。

本模块只做纯文本/Markdown 生成，DOCX 输出在 ``scripts/campus/translate_docs.py``。
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Dict, Iterable, List, Optional, Sequence, Tuple

# 句末标点（中俄共用 + 英文）
_END_CHARS = "。！？!?；;"
# 中文句号也算，但俄语里的 "." 要小心缩写
_ABBREV_GUARDS = (
    "т.е.", "т.д.", "т.п.", "др.", "г.", "гг.", "в.", "вв.", "см.", "рис.",
    "табл.", "стр.", "напр.", "им.", "ауд.", "корп.", "тыс.", "млн.", "млрд.",
)


def _guard_dots(text: str) -> str:
    """把"不是句末"的点替换成占位字符，避免切句时误断。

    三类要保护：
    * 缩写（``т.е.``、``ауд.``、``рис.`` …）；
    * 俄语姓名缩写（``И.И.``、``А. С.``）；
    * 小数点（``3.14``、``12.05.2026``）。
    """
    guard = "\x00"
    working = text
    for pattern in _ABBREV_GUARDS:
        working = re.sub(re.escape(pattern), pattern.replace(".", guard), working,
                         flags=re.IGNORECASE)
    # 连续的首字母缩写：И.И. / А. С. / J.R.R.
    working = re.sub(r"(?:\b[А-ЯA-Z]\.\s?){1,3}",
                     lambda m: m.group(0).replace(".", guard), working)
    # 小数点
    working = re.sub(r"(\d)\.(\d)", r"\1" + guard + r"\2", working)
    return working


def split_sentences(text: str, lang: str = "zh") -> List[str]:
    """按句切分，返回非空句子列表。"""
    if not text:
        return []
    working = _guard_dots(text)

    if lang.startswith("zh"):
        parts = re.split(r"(?<=[。！？；!?;])", working)
    else:
        parts = re.split(r"(?<=[.!?;])\s*", working)
    out: List[str] = []
    for part in parts:
        cleaned = part.replace("\x00", ".").strip()
        if cleaned:
            out.append(cleaned)
    return out


@dataclass
class AlignedPair:
    """一对中俄句子。"""

    index: int
    left: str
    right: str
    method: str = "1:1"   # 1:1 | merge | split | unmatched

    @property
    def ok(self) -> bool:
        return self.method == "1:1"


@dataclass
class AlignmentResult:
    pairs: List[AlignedPair] = field(default_factory=list)
    quality: float = 1.0
    warnings: List[str] = field(default_factory=list)

    @property
    def warnings_text(self) -> str:
        return "；".join(self.warnings)


def align_pairs(source_sentences: Sequence[str], target_sentences: Sequence[str]) -> AlignmentResult:
    """对齐两组句子。

    * 句数相同 —— 逐句 1:1 对齐；
    * 译文更多 —— 按长度比例合并译文（合并段标记 ``merge``）；
    * 译文更少 —— 把源句按比例挂到译文上（标记 ``split``）。
    """
    result = AlignmentResult()
    left = [s for s in source_sentences if s.strip()]
    right = [s for s in target_sentences if s.strip()]
    if not left and not right:
        return result
    if len(left) == len(right):
        for i, (src, tgt) in enumerate(zip(left, right)):
            result.pairs.append(AlignedPair(i, src, tgt, "1:1"))
        result.quality = 1.0
        return result

    if len(right) > len(left) and left:
        buckets = _distribute(len(right), len(left))
        cursor = 0
        for i, count in enumerate(buckets):
            chunk = right[cursor:cursor + count]
            cursor += count
            result.pairs.append(AlignedPair(i, left[i], " ".join(chunk), "merge"))
        result.warnings.append("译文句数(%d)多于原文(%d)，已按顺序合并" % (len(right), len(left)))
    elif right:
        buckets = _distribute(len(left), len(right))
        cursor = 0
        for i, count in enumerate(buckets):
            chunk = left[cursor:cursor + count]
            cursor += count
            result.pairs.append(AlignedPair(i, " ".join(chunk), right[i], "split"))
        result.warnings.append("译文句数(%d)少于原文(%d)，已按顺序拆分源句" % (len(right), len(left)))
    else:
        for i, src in enumerate(left):
            result.pairs.append(AlignedPair(i, src, "", "unmatched"))
        result.warnings.append("译文为空，全部标记为未对齐")
    total = max(len(left), len(right))
    result.quality = (sum(1 for p in result.pairs if p.ok) / float(total)) if total else 1.0
    return result


def _distribute(total: int, buckets: int) -> List[int]:
    """把 ``total`` 个元素尽量均匀分到 ``buckets`` 个桶里。"""
    if buckets <= 0:
        return []
    base, rest = divmod(total, buckets)
    return [base + (1 if i < rest else 0) for i in range(buckets)]


# ---------------------------------------------------------------------------
# 场景模板
# ---------------------------------------------------------------------------

LAYOUTS = ("side-by-side", "interleaved", "paragraph", "table")


@dataclass
class BilingualDoc:
    """一份中俄对照文档。"""

    title_zh: str = ""
    title_ru: str = ""
    pairs: List[AlignedPair] = field(default_factory=list)
    meta: Dict[str, str] = field(default_factory=dict)
    warnings: List[str] = field(default_factory=list)

    def render(self, layout: str = "interleaved", left_label: str = "中文",
               right_label: str = "Русский") -> str:
        if layout not in LAYOUTS:
            raise ValueError("unknown layout: %s" % layout)
        lines: List[str] = []
        if self.title_zh or self.title_ru:
            lines.append("# %s" % (self.title_zh or self.title_ru))
            if self.title_ru and self.title_ru != self.title_zh:
                lines.append("## %s" % self.title_ru)
            lines.append("")
        if self.meta:
            for key, value in self.meta.items():
                lines.append("> **%s**：%s" % (key, value))
            lines.append("")
        if layout == "table":
            if self.pairs:
                lines.append("| %s | %s |" % (left_label, right_label))
                lines.append("| --- | --- |")
                for pair in self.pairs:
                    lines.append("| %s | %s |" % (pair.left.replace("|", "\\|"),
                                                   pair.right.replace("|", "\\|")))
                lines.append("")
        else:
            for pair in self.pairs:
                if layout == "side-by-side":
                    lines.append("%s ｜ %s" % (pair.left, pair.right))
                else:  # interleaved / paragraph
                    lines.append(pair.left)
                    lines.append(pair.right)
                    lines.append("")
        if self.warnings:
            lines.append("> 对齐提示：%s" % "；".join(self.warnings))
        return "\n".join(lines).strip() + "\n"

    def render_plain(self, separator: str = "\n") -> str:
        out: List[str] = []
        if self.title_zh:
            out.append(self.title_zh)
        if self.title_ru:
            out.append(self.title_ru)
        for pair in self.pairs:
            out.append(pair.left)
            out.append(pair.right)
        return separator.join([line for line in out if line])


@dataclass
class NoticeFields:
    """校园通知/邮件的结构化字段。"""

    title: str = ""
    audience: str = ""       # 发送对象
    body: str = ""           # 正文
    issuer: str = ""         # 发文单位
    date: str = ""           # 日期（建议保留原文，不翻译）
    contact: str = ""        # 联系方式


NOTICE_LABELS: Dict[str, Dict[str, str]] = {
    "zh": {"title": "标题", "audience": "发送对象", "body": "正文",
           "issuer": "发文单位", "date": "日期", "contact": "联系方式"},
    "ru": {"title": "Тема", "audience": "Кому", "body": "Текст",
           "issuer": "Отправитель", "date": "Дата", "contact": "Контакты"},
}

# 中俄书信/通知的固定礼貌用语，直接由术语库之外的小词表兜底，
# 保证"敬语不出错"（机器翻译经常把"尊敬的"译得过于口语化）。
COURTESY: Dict[str, Dict[str, str]] = {
    "zh": {
        "salutation": "尊敬的老师、同学：",
        "closing": "此致\n敬礼",
        "signature": "深圳北理莫斯科大学",
    },
    "ru": {
        "salutation": "Уважаемые преподаватели и студенты!",
        "closing": "С уважением,",
        "signature": "Совместный университет МГУ-ППИ в Шэньчжэне",
    },
}


def notice_template(fields: NoticeFields, lang: str = "zh") -> str:
    """把结构化字段渲染成通知文本（单语）。"""
    is_ru = bool(lang.startswith("ru"))
    labels = NOTICE_LABELS["ru" if is_ru else "zh"]
    sep = ": " if is_ru else "："
    lines: List[str] = []
    if fields.title:
        lines.append("%s%s%s" % (labels["title"], sep, fields.title))
    if fields.audience:
        lines.append("%s%s%s" % (labels["audience"], sep, fields.audience))
    if fields.body:
        lines.append("")
        lines.append(fields.body)
    lines.append("")
    tail: List[str] = []
    if fields.issuer:
        tail.append(fields.issuer)
    if fields.date:
        tail.append(fields.date)
    if fields.contact:
        tail.append(fields.contact)
    lines.extend(tail)
    return "\n".join(lines).strip() + "\n"


def email_template(fields: NoticeFields, lang: str = "zh") -> str:
    """把结构化字段渲染成邮件正文（含中俄礼貌用语）。"""
    key = "ru" if lang.startswith("ru") else "zh"
    courtesy = COURTESY[key]
    lines = [courtesy["salutation"], ""]
    if fields.title:
        lines.append(fields.title)
        lines.append("")
    if fields.body:
        lines.append(fields.body)
    lines.append("")
    lines.append(courtesy["closing"])
    if fields.issuer:
        lines.append(fields.issuer)
    if fields.contact:
        lines.append(fields.contact)
    if fields.date:
        lines.append(fields.date)
    return "\n".join(lines).strip() + "\n"


def slide_title_template(title: str, bullets: Sequence[str], lang: str = "zh") -> str:
    """课件标题 + 要点（中俄对照时标题与要点分别成对）。"""
    lines = ["# %s" % title]
    for bullet in bullets:
        lines.append("- %s" % bullet)
    return "\n".join(lines).strip() + "\n"
