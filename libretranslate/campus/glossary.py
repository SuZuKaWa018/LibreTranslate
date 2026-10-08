"""校园术语库（Glossary）。

设计目标
--------
* **可审计**：每条术语带 ``domain`` / ``source`` / ``note``，能回答"这个词谁定的、
  依据是什么"；
* **可增量**：术语以 JSON 文件按域拆分存放，翻译时按 profile 组合加载；
* **翻译时优先采用**：命中术语先用占位符遮蔽，译为规范译法后再回填，
  避免模型把"数据结构"译成随机说法；
* **可自检**：:meth:`Glossary.validate` 能查出重复、歧义、非法字符等问题，
  CI 或入库脚本可直接调用。

本模块不依赖翻译引擎，可单独单元测试。
"""
from __future__ import annotations

import json
import os
import re
import unicodedata
from dataclasses import asdict, dataclass, field
from typing import Dict, Iterable, List, Optional, Sequence, Tuple

from .placeholders import PlaceholderTable, RestoreResult, Slot

CJK_RE = re.compile(r"[\u3400-\u4dbf\u4e00-\u9fff\uf900-\ufaff]")
CYRILLIC_RE = re.compile(r"[\u0400-\u04ff]")
LATIN_RE = re.compile(r"[A-Za-z]")
SPACE_RE = re.compile(r"\s+")

VALID_DOMAINS = ("cs", "math", "physics", "econ", "campus", "admin", "general")


@dataclass
class Term:
    """一条术语。"""

    zh: str
    ru: str
    en: str = ""
    domain: str = "general"
    note: str = ""
    source: str = ""
    do_not_translate: bool = False

    def as_dict(self) -> Dict[str, object]:
        return asdict(self)

    def target(self, lang: str) -> str:
        """返回该术语在指定语言下的写法（找不到时返回空串）。"""
        lang = (lang or "").lower()
        if lang.startswith("zh"):
            return self.zh
        if lang.startswith("ru"):
            return self.ru
        if lang.startswith("en"):
            return self.en
        return ""

    @classmethod
    def from_dict(cls, data: Dict[str, object]) -> "Term":
        return cls(
            zh=str(data.get("zh", "")).strip(),
            ru=str(data.get("ru", "")).strip(),
            en=str(data.get("en", "")).strip(),
            domain=str(data.get("domain", "general")).strip() or "general",
            note=str(data.get("note", "")).strip(),
            source=str(data.get("source", "")).strip(),
            do_not_translate=bool(data.get("do_not_translate", False)),
        )


@dataclass
class GlossaryIssue:
    """术语库自检发现的问题。"""

    code: str
    message: str
    zh: str = ""
    severity: str = "warning"  # warning | error


@dataclass
class GlossaryMatch:
    """一次术语命中。"""

    start: int
    end: int
    origin: str
    term: Term
    value: str  # 目标语言写法
    slot: Optional[Slot] = None

    @property
    def span(self) -> Tuple[int, int]:
        return (self.start, self.end)


@dataclass
class MaskOutcome:
    """遮蔽结果。"""

    text: str
    matches: List[GlossaryMatch] = field(default_factory=list)
    table: Optional[PlaceholderTable] = None
    source: str = ""
    target: str = ""


def _norm(text: str) -> str:
    """匹配用的归一化：NFKC + 大小写折叠 + 空白压缩。"""
    return SPACE_RE.sub(" ", unicodedata.normalize("NFKC", text or "").strip()).casefold()


_CJK_L = r"\u4e00-\u9fff"
_SCRIPT_L = r"A-Za-z\u0400-\u04ff"
_SPACE_BEFORE_TOKEN = re.compile(r"([%s])(\[\[T\d+\]\])" % _CJK_L)
_SPACE_AFTER_TOKEN = re.compile(r"(\[\[T\d+\]\])([%s])" % _CJK_L)
_SPACE_BEFORE_SCRIPT = re.compile(r"([%s])(?=[%s])" % (_CJK_L, _SCRIPT_L))
_SPACE_AFTER_SCRIPT = re.compile(r"(?<=[%s])([%s])" % (_SCRIPT_L, _CJK_L))


def _space_boundaries(text: str) -> str:
    """中文与西里尔/拉丁之间补空格。

    术语被替换成俄语后，如果原文是"讲授数据结构"这种无空格的中文，
    回填结果会粘成"охватываетструктуры данных"；在这里补一个空格，
    引擎的断句和最终排版都会更好。
    """
    out = _SPACE_BEFORE_TOKEN.sub(r"\1 \2", text)
    out = _SPACE_AFTER_TOKEN.sub(r"\1 \2", out)
    out = _SPACE_BEFORE_SCRIPT.sub(r"\1 ", out)
    out = _SPACE_AFTER_SCRIPT.sub(r" \1", out)
    return out


def _key_pattern(key: str) -> "re.Pattern":
    """把归一化词条编译成正则。

    * 词条内部空格允许匹配任意空白；
    * 忽略大小写（拉丁与西里尔都适用）；
    * 俄语 ``ё`` 与 ``е`` 互通，因为学生常把 ``Соловьёв`` 写成 ``Соловьев``。
    """
    parts = [re.escape(part) for part in key.split(" ") if part]
    body = r"\s+".join(parts)
    body = body.replace("ё", "[её]").replace("Ё", "[ЕЁ]")
    return re.compile(body, re.IGNORECASE | re.UNICODE)


class Glossary:
    """一份术语库（可由多个 JSON 文件合并而来）。"""

    def __init__(self, terms: Optional[Iterable[Term]] = None, name: str = "default",
                 version: str = "", description: str = ""):
        self.name = name
        self.version = version
        self.description = description
        self._terms: List[Term] = list(terms or [])
        self._index: Optional[Dict[str, List[Term]]] = None
        self._patterns: Optional[List[Tuple[str, "re.Pattern", List[Term]]]] = None

    # -- 构建 ---------------------------------------------------------------
    @classmethod
    def from_dicts(cls, rows: Iterable[Dict[str, object]], **kwargs) -> "Glossary":
        return cls([Term.from_dict(r) for r in rows], **kwargs)

    @classmethod
    def from_json_file(cls, path: str, name: Optional[str] = None) -> "Glossary":
        with open(path, "r", encoding="utf-8") as handle:
            payload = json.load(handle)
        if isinstance(payload, dict):
            rows = payload.get("terms", [])
            meta = {k: payload.get(k) for k in ("name", "version", "description")}
        else:
            rows, meta = payload, {}
        return cls.from_dicts(
            rows,
            name=name or meta.get("name") or os.path.splitext(os.path.basename(path))[0],
            version=meta.get("version") or "",
            description=meta.get("description") or "",
        )

    @classmethod
    def from_json_dir(cls, directory: str, profile: Optional[str] = None) -> "Glossary":
        """加载目录下的术语文件。

        ``profile`` 形如 ``campus_zh_ru``：优先加载同名文件，其次是 ``*.json`` 全量。
        """
        if not os.path.isdir(directory):
            raise FileNotFoundError("glossary directory not found: %s" % directory)
        files: List[str] = []
        if profile:
            candidate = os.path.join(directory, profile + ("" if profile.endswith(".json") else ".json"))
            if os.path.exists(candidate):
                files.append(candidate)
            else:
                files.extend(
                    os.path.join(directory, f)
                    for f in sorted(os.listdir(directory))
                    if f.endswith(".json") and profile in f
                )
        if not files:
            files = [
                os.path.join(directory, f)
                for f in sorted(os.listdir(directory))
                if f.endswith(".json") and not f.startswith("noise")
            ]
        return cls.from_files(files, name=profile or os.path.basename(directory))

    @classmethod
    def from_files(cls, paths: Sequence[str], name: str = "merged") -> "Glossary":
        merged: List[Term] = []
        versions: List[str] = []
        for path in paths:
            part = cls.from_json_file(path)
            merged.extend(part.terms)
            if part.version:
                versions.append(part.version)
        return cls(merged, name=name, version="+".join(versions))

    # -- 基本属性 -----------------------------------------------------------
    @property
    def terms(self) -> List[Term]:
        return list(self._terms)

    def add(self, term: Term) -> None:
        self._terms.append(term)
        self._invalidate()

    def extend(self, terms: Iterable[Term]) -> None:
        self._terms.extend(terms)
        self._invalidate()

    def _invalidate(self) -> None:
        self._index = None
        self._patterns = None

    def merge(self, other: "Glossary") -> "Glossary":
        """合并另一份术语库；同 ``zh`` 冲突时后加入的覆盖先加入的。"""
        merged = Glossary(list(self._terms), name=self.name, version=self.version)
        merged.extend(other.terms)
        return merged

    def __len__(self) -> int:
        return len(self._terms)

    def domains(self) -> Dict[str, int]:
        out: Dict[str, int] = {}
        for term in self._terms:
            out[term.domain] = out.get(term.domain, 0) + 1
        return dict(sorted(out.items(), key=lambda kv: (-kv[1], kv[0])))

    # -- 检索 ---------------------------------------------------------------
    def _build_index(self) -> Dict[str, List[Term]]:
        if self._index is None:
            index: Dict[str, List[Term]] = {}
            for term in self._terms:
                for lang in ("zh", "ru", "en"):
                    key = _norm(term.target(lang))
                    if not key:
                        continue
                    if len(key) < 2 and not term.do_not_translate:
                        continue
                    index.setdefault(key, []).append(term)
            self._index = index
        return self._index

    def _compiled_index(self) -> List[Tuple[str, "re.Pattern", List[Term]]]:
        """``(key, regex, terms)``，正则直接匹配原始文本，便于拿到准确偏移。"""
        if self._patterns is None:
            compiled = []
            for key, terms in self._build_index().items():
                compiled.append((key, _key_pattern(key), terms))
            # 长词条优先，避免"数据结构"被"数据"抢先命中
            compiled.sort(key=lambda item: (-len(item[0]), item[0]))
            self._patterns = compiled
        return self._patterns

    def candidates(self, text: str, source: str, target: str) -> List[Tuple[str, Term]]:
        """返回文本中命中的 ``(词条, Term)``，按词条长度降序。"""
        return [(key, terms[0]) for key, regex, terms in self._compiled_index()
                if regex.search(text or "")]

    def match(self, text: str, source: str, target: str) -> List[GlossaryMatch]:
        """最长优先、互不重叠地找出术语命中位置。

        偏移量相对 NFKC 规范化后的文本；:meth:`mask` 内部使用同一套偏移，
        因此不会错位。俄语词条里的 ``ё`` 会同时匹配 ``е`` 写法。
        """
        if not text:
            return []
        haystack = unicodedata.normalize("NFKC", text)
        spans: List[Tuple[int, int, str, Term]] = []
        for key, regex, terms in self._compiled_index():
            term = terms[0]
            if not term.target(target):
                continue
            for found in regex.finditer(haystack):
                spans.append((found.start(), found.end(), key, term))
        spans.sort(key=lambda item: (-(item[1] - item[0]), item[0]))
        taken = bytearray(len(haystack))
        matches: List[GlossaryMatch] = []
        for start, end, key, term in spans:
            if any(taken[start:end]):
                continue
            for i in range(start, end):
                taken[i] = 1
            matches.append(
                GlossaryMatch(start=start, end=end, origin=haystack[start:end],
                              term=term, value=term.target(target))
            )
        matches.sort(key=lambda m: (m.start, m.end))
        return matches

    def mask(self, text: str, source: str = "zh", target: str = "ru",
             strict: bool = True, table: Optional[PlaceholderTable] = None) -> MaskOutcome:
        """把命中的术语替换成占位符，返回待翻译文本。

        ``strict=False`` 时，术语直接替换为目标语言写法（不做占位符保护），
        适用于"术语表直出"这类不需要模型的场景。
        传入 ``table`` 可与其它规则（如编号保护）共用同一张占位符表。
        """
        haystack = unicodedata.normalize("NFKC", text or "")
        matches = self.match(haystack, source, target)
        if not matches:
            return MaskOutcome(text=haystack, table=table, source=source, target=target)
        if not strict:
            pieces: List[str] = []
            cursor = 0
            for match in matches:
                pieces.append(haystack[cursor:match.start])
                pieces.append(match.value)
                cursor = match.end
            pieces.append(haystack[cursor:])
            return MaskOutcome(text=_space_boundaries("".join(pieces)), matches=matches,
                               table=table, source=source, target=target)

        table = table if table is not None else PlaceholderTable()
        pieces = []
        cursor = 0
        for match in matches:
            pieces.append(haystack[cursor:match.start])
            match.slot = table.add(
                origin=match.origin,
                value=match.value,
                kind="term",
                meta={"domain": match.term.domain, "zh": match.term.zh, "ru": match.term.ru},
            )
            pieces.append(match.slot)
            cursor = match.end
        pieces.append(haystack[cursor:])
        return MaskOutcome(text=_space_boundaries(table.render(pieces)), matches=matches,
                           table=table, source=source, target=target)

    def restore(self, text: str, table: Optional[PlaceholderTable], loose: bool = True) -> RestoreResult:
        if table is None:
            return RestoreResult(text=text)
        return table.restore(text, loose=loose)

    # -- 直出/校验 ----------------------------------------------------------
    def translate_terms(self, source: str, target: str) -> Dict[str, str]:
        """术语表直出：``{源语言写法: 目标语言写法}``（不需要模型）。"""
        out: Dict[str, str] = {}
        for term in self._terms:
            src = term.target(source)
            tgt = term.target(target)
            if src and tgt:
                out[src] = tgt
        return out

    def coverage(self, text: str, source: str = "zh", target: str = "ru") -> float:
        """术语覆盖率：命中的术语字符数 / 文本字符数（用于质量看板）。"""
        haystack = unicodedata.normalize("NFKC", text or "")
        if not haystack:
            return 0.0
        used = sum(m.end - m.start for m in self.match(haystack, source, target))
        return used / float(len(haystack))

    def unknown_candidates(self, text: str, source: str = "zh",
                           min_len: int = 2) -> List[str]:
        """粗筛"可能是术语但库里没有"的中文串（连续汉字片段），供术语库补录。"""
        known = set()
        for term in self._terms:
            for lang in ("zh", "ru"):
                known.add(_norm(term.target(lang)))
        found: List[str] = []
        for chunk in re.findall(r"[\u4e00-\u9fff]{%d,}" % min_len, text or ""):
            for size in range(len(chunk), min_len - 1, -1):
                for start in range(0, len(chunk) - size + 1):
                    piece = chunk[start:start + size]
                    if _norm(piece) not in known and piece not in found:
                        found.append(piece)
                if found:
                    break
        return found[:50]

    def validate(self) -> List[GlossaryIssue]:
        """术语库自检。返回问题列表（空列表表示通过）。"""
        issues: List[GlossaryIssue] = []
        seen_zh: Dict[str, Term] = {}
        for term in self._terms:
            if not term.zh or not term.ru:
                issues.append(GlossaryIssue("GLOSSARY_INCOMPLETE", "zh/ru 不能为空", term.zh, "error"))
                continue
            if term.domain not in VALID_DOMAINS:
                issues.append(
                    GlossaryIssue("GLOSSARY_BAD_DOMAIN",
                                  "domain 不在约定集合内: %s" % term.domain, term.zh)
                )
            if CJK_RE.search(term.ru):
                issues.append(
                    GlossaryIssue("GLOSSARY_CJK_IN_RU", "俄语侧混入中日韩字符: %s" % term.ru, term.zh)
                )
            if CYRILLIC_RE.search(term.zh):
                issues.append(
                    GlossaryIssue("GLOSSARY_CYRILLIC_IN_ZH", "中文侧混入西里尔字母: %s" % term.zh, term.zh)
                )
            if LATIN_RE.search(term.ru) and not term.note:
                issues.append(
                    GlossaryIssue("GLOSSARY_LATIN_IN_RU",
                                  "俄语侧含拉丁字母且未在 note 中说明（可能是漏译）: %s" % term.ru,
                                  term.zh)
                )
            key = _norm(term.zh)
            if key in seen_zh:
                other = seen_zh[key]
                if _norm(other.ru) != _norm(term.ru):
                    if not term.note and not other.note:
                        issues.append(
                            GlossaryIssue(
                                "GLOSSARY_AMBIGUOUS_NO_NOTE",
                                "同一中文有两种译法且都没有 note: %s / %s" % (other.ru, term.ru),
                                term.zh,
                            )
                        )
                else:
                    issues.append(
                        GlossaryIssue("GLOSSARY_DUPLICATE", "重复词条: %s" % term.zh, term.zh)
                    )
            else:
                seen_zh[key] = term
        return issues

    def stats(self) -> Dict[str, object]:
        return {
            "name": self.name,
            "version": self.version,
            "count": len(self._terms),
            "domains": self.domains(),
            "with_note": sum(1 for t in self._terms if t.note),
            "with_source": sum(1 for t in self._terms if t.source),
        }

    # -- 序列化 -------------------------------------------------------------
    def to_json(self, indent: int = 2) -> str:
        payload = {
            "name": self.name,
            "version": self.version,
            "description": self.description,
            "terms": [t.as_dict() for t in self._terms],
        }
        return json.dumps(payload, ensure_ascii=False, indent=indent) + "\n"

    def save(self, path: str) -> None:
        with open(path, "w", encoding="utf-8") as handle:
            handle.write(self.to_json())
