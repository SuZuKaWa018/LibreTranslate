"""校园场景"噪音"处理（Noise handling）。

中俄双语校园文本里有一批**不该被翻译**的东西，机器翻译却经常动手：

* 课程编号、教室号、学号、班级号（``МА101``、``3-412``、``2023B0123``）；
* 邮箱、URL、电话、日期时间、公式编号、文件名；
* 中文缩写（"深北莫"）与俄文缩写（``МГУ-ППИ``）；
* 俄方师生姓名（需要音译而不是逐字翻译）。

本模块提供三件事：

1. :class:`NoiseProtector` —— 按正则命中后交给占位符机制保护；
2. :func:`normalize_source` / :func:`clean_translation` —— 输入输出规范化；
3. :class:`AbbreviationBook` 与 :class:`NameTransliterator` —— 缩写展开与姓名音译。

同样不依赖翻译引擎，可单独单元测试。
"""
from __future__ import annotations

import json
import os
import re
import unicodedata
from dataclasses import dataclass, field
from typing import Dict, Iterable, List, Optional, Sequence, Tuple

from .placeholders import PlaceholderTable, RestoreResult, Slot

# ---------------------------------------------------------------------------
# 默认保护规则
# ---------------------------------------------------------------------------


@dataclass
class ProtectedPattern:
    """一条"原样保留"的规则。"""

    name: str
    pattern: str
    description: str = ""
    case_sensitive: bool = False

    def compile(self) -> "re.Pattern":
        flags = 0 if self.case_sensitive else re.IGNORECASE
        return re.compile(self.pattern, flags)


DEFAULT_PATTERNS: Tuple[ProtectedPattern, ...] = (
    ProtectedPattern("course_code", r"\b(?:[A-ZА-Я]{2,4}[-‑]?\d{2,4}[A-ZА-Я]?)\b",
                     "课程/专业编号，如 MA101、МА-101、CS204B"),
    ProtectedPattern("room", r"\b(?:[А-ЯA-Z]?\d{1,2}[-‑]\d{2,4}[А-ЯA-Z]?|ауд\.\s?\d{2,4})\b",
                     "教室号，如 3-412、ауд. 512"),
    ProtectedPattern("student_id", r"\b\d{4}[A-ZА-Я]{0,3}\d{4,8}\b", "学号/工号"),
    ProtectedPattern("email", r"[\w.+-]+@[\w-]+\.[\w.-]+", "邮箱"),
    ProtectedPattern("url", r"(?:https?://|www\.)[^\s，。；）)]+", "网址"),
    ProtectedPattern("phone",
                     r"(?:(?:\+7|\+86|8)[\s\-()]?\d{3,4}[\s\-]?\d{3}[\s\-]?\d{2}[\s\-]?\d{2}"
                     r"|\+?86[\s\-]?\d{3}[\s\-]?\d{4}[\s\-]?\d{4})",
                     "中俄手机/座机号，如 +7 916 123 45 67、+86 755 1234 5678"),
    ProtectedPattern("date_ru", r"\b\d{1,2}[./]\d{1,2}[./]\d{2,4}\b", "日期 12.05.2026"),
    ProtectedPattern("date_zh", r"\d{4}\s?年\s?\d{1,2}\s?月\s?\d{1,2}\s?日", "日期 2026年5月12日"),
    ProtectedPattern("time", r"\b\d{1,2}:\d{2}(?::\d{2})?\b", "时间 14:30"),
    ProtectedPattern("formula_ref", r"\(\s?\d{1,2}[.\-]\d{1,3}\s?\)|式\s?\(\d{1,2}\)", "公式引用"),
    ProtectedPattern("file_name", r"[\w\u4e00-\u9fff-]+\.(?:docx?|pptx?|xlsx?|pdf|zip|py|json|csv|txt)",
                     "文件名"),
    ProtectedPattern("percent", r"\d+(?:[.,]\d+)?\s?%", "百分比"),
    ProtectedPattern("initials", r"\b[А-ЯA-Z]\.\s?[А-ЯA-Z]\.", "姓名缩写，如 И.И."),
)

# 中俄混排时需要在汉字与西里尔/拉丁字母之间补空格
_CJK = r"\u4e00-\u9fff"
_BOUNDARY_PATTERNS = (
    (re.compile(r"(?<=[%s])(?=[A-Za-z\u0400-\u04ff])" % _CJK), " "),
    (re.compile(r"(?<=[A-Za-z\u0400-\u04ff])(?=[%s])" % _CJK), " "),
)

# 全角 → 半角（标点为主）
_FULLWIDTH_MAP = {
    "，": ", ", "。": ". ", "；": "; ", "：": ": ", "？": "?", "！": "!",
    "（": " (", "）": ") ", "、": ", ", "～": "~", "－": "-", "　": " ",
    "％": "%", "＋": "+", "＝": "=", "／": "/", "＃": "#", "＆": "&",
}


@dataclass
class ProtectOutcome:
    """保护结果。"""

    text: str
    table: PlaceholderTable
    hits: List[Tuple[str, str]] = field(default_factory=list)  # (rule_name, origin)


class NoiseProtector:
    """把校园文本里的编号/链接/日期等替换为占位符。"""

    def __init__(self, patterns: Optional[Iterable[ProtectedPattern]] = None):
        self.patterns = list(DEFAULT_PATTERNS if patterns is None else patterns)
        self._compiled = [(p, p.compile()) for p in self.patterns]

    def protect(self, text: str, rules: Optional[Iterable[str]] = None,
                table: Optional[PlaceholderTable] = None) -> ProtectOutcome:
        """保护文本；``rules`` 可只启用指定规则名；``table`` 可与术语库共用。"""
        table = table if table is not None else PlaceholderTable()
        working = text or ""
        hits: List[Tuple[str, str]] = []
        wanted = set(rules) if rules else None
        for spec, regex in self._compiled:
            if wanted is not None and spec.name not in wanted:
                continue
            pieces: List[object] = []
            cursor = 0
            for match in regex.finditer(working):
                pieces.append(working[cursor:match.start()])
                origin = match.group(0)
                pieces.append(table.add(origin=origin, value=origin, kind="pattern",
                                        meta={"rule": spec.name}))
                hits.append((spec.name, origin))
                cursor = match.end()
            pieces.append(working[cursor:])
            working = table.render(pieces)
        return ProtectOutcome(text=working, table=table, hits=hits)

    def restore(self, text: str, table: PlaceholderTable, loose: bool = True) -> RestoreResult:
        return table.restore(text, loose=loose)


# ---------------------------------------------------------------------------
# 规范化
# ---------------------------------------------------------------------------


def normalize_source(text: str, lang: str = "zh") -> str:
    """统一输入：NFKC、全角标点、中文/西里尔边界空格、多余空白。

    注意 NFKC 会先把全角标点（``，：；``）折成半角，因此这里要在半角形态上
    补空格：只在标点后面紧跟汉字时插入空格，避免把 ``3-412,5`` 这类编号拆开。
    """
    if not text:
        return ""
    out = unicodedata.normalize("NFKC", text)
    for src, dst in _FULLWIDTH_MAP.items():
        out = out.replace(src, dst)
    out = out.replace("\r\n", "\n").replace("\r", "\n")
    # 半角标点后紧跟汉字时补一个空格，让 MT 引擎能正确断句
    out = re.sub(r"([,;:])(?=[\u4e00-\u9fff])", r"\1 ", out)
    # 左括号后、右括号前的空白整理
    out = re.sub(r"\(\s+", "(", out)
    out = re.sub(r"\s+\)", ")", out)
    for regex, repl in _BOUNDARY_PATTERNS:
        out = regex.sub(repl, out)
    out = re.sub(r"[ \t]{2,}", " ", out)
    out = re.sub(r" *\n *", "\n", out)
    return out.strip()


_RU_PUNCT_FIXES = (
    (re.compile(r"\s+([,.;:!?])"), r"\1"),
    (re.compile(r"([,;:])(?=[^\s\d])"), r"\1 "),
    (re.compile(r"\s{2,}"), " "),
)


def clean_translation(text: str, lang: str = "ru") -> str:
    """清理译文排版：俄语标点前后空格、重复空白、括号内侧空格。"""
    if not text:
        return ""
    out = text
    out = re.sub(r"\(\s+", "(", out)
    out = re.sub(r"\s+\)", ")", out)
    if lang.startswith("ru"):
        for regex, repl in _RU_PUNCT_FIXES:
            out = regex.sub(repl, out)
    else:
        for src, dst in _FULLWIDTH_MAP.items():
            out = out.replace(src, dst)
    return out.strip()


# ---------------------------------------------------------------------------
# 缩写
# ---------------------------------------------------------------------------


@dataclass
class Abbreviation:
    short: str
    lang: str
    full: str
    translation: str = ""
    note: str = ""


class AbbreviationBook:
    """缩写 ↔ 全称对照（"深北莫"、"МГУ-ППИ" 之类）。"""

    def __init__(self, entries: Optional[Iterable[Abbreviation]] = None):
        self._entries: Dict[str, Abbreviation] = {}
        for entry in entries or ():
            self._entries[entry.short.casefold()] = entry

    @classmethod
    def from_json_file(cls, path: str) -> "AbbreviationBook":
        with open(path, "r", encoding="utf-8") as handle:
            payload = json.load(handle)
        rows = payload.get("abbreviations", payload) if isinstance(payload, dict) else payload
        return cls(Abbreviation(
            short=str(row.get("short", "")).strip(),
            lang=str(row.get("lang", "zh")).strip(),
            full=str(row.get("full", "")).strip(),
            translation=str(row.get("translation", "")).strip(),
            note=str(row.get("note", "")).strip(),
        ) for row in rows)

    def __len__(self) -> int:
        return len(self._entries)

    def entries(self) -> List[Abbreviation]:
        return list(self._entries.values())

    def expand(self, text: str, mode: str = "parenthetical") -> str:
        """把缩写第一次出现处展开成全称。

        ``mode``：
          * ``parenthetical``：``深北莫（深圳北理莫斯科大学）``
          * ``replace``：直接用全称替换
          * ``annotate``：只在末尾附加一条说明行
        """
        out = text or ""
        notes: List[str] = []
        for entry in self._entries.values():
            if not entry.short or entry.short not in out:
                continue
            if mode == "replace":
                out = out.replace(entry.short, entry.full)
            elif mode == "annotate":
                notes.append("%s = %s" % (entry.short, entry.full))
            else:
                out = out.replace(entry.short, "%s（%s）" % (entry.short, entry.full), 1)
        if mode == "annotate" and notes:
            out = out + "\n\n注释：" + "；".join(notes)
        return out

    def translate_short(self, short: str) -> str:
        entry = self._entries.get((short or "").casefold())
        return entry.translation if entry else ""

    def find(self, text: str) -> List[Abbreviation]:
        return [e for e in self._entries.values() if e.short and e.short in (text or "")]


# ---------------------------------------------------------------------------
# 姓名音译
# ---------------------------------------------------------------------------


@dataclass
class NameGuess:
    source: str
    han: str
    method: str          # dictionary | syllable | unchanged
    confidence: float    # 0~1
    review: bool = False  # 需要人工复核

    def __str__(self) -> str:  # pragma: no cover - 便于调试打印
        return "%s -> %s (%s, %.2f)" % (self.source, self.han, self.method, self.confidence)


# 常见俄语姓氏/名字的规范中文写法（人工整理，标准译法优先）
DEFAULT_NAME_DICTIONARY: Dict[str, str] = {
    "иванов": "伊万诺夫", "иванова": "伊万诺娃", "иван": "伊万",
    "петров": "彼得罗夫", "петрова": "彼得罗娃", "пётр": "彼得",
    "смирнов": "斯米尔诺夫", "кузнецов": "库兹涅佐夫", "соколов": "索科洛夫",
    "попов": "波波夫", "лебедев": "列别杰夫", "козлов": "科兹洛夫",
    "новиков": "诺维科夫", "морозов": "莫罗佐夫", "волков": "沃尔科夫",
    "соловьёв": "索洛维约夫", "васильев": "瓦西里耶夫", "зайцев": "扎伊采夫",
    "павлов": "巴甫洛夫", "семёнов": "谢苗诺夫", "голубев": "戈卢别夫",
    "виноградов": "维诺格拉多夫", "богданов": "波格丹诺夫", "воробьёв": "沃罗比约夫",
    "фёдоров": "费奥多罗夫", "михайлов": "米哈伊洛夫", "беляев": "别利亚耶夫",
    "тарасов": "塔拉索夫", "белов": "别洛夫", "комаров": "科马罗夫",
    "орлов": "奥尔洛夫", "киселёв": "基谢廖夫", "макаров": "马卡罗夫",
    "андреев": "安德烈耶夫", "ковалёв": "科瓦廖夫", "ильин": "伊林",
    "гусев": "古谢夫", "титов": "季托夫", "кузьмин": "库兹明",
    "кудрявцев": "库德里亚夫采夫", "баранов": "巴拉诺夫", "куликов": "库利科夫",
    "алексеев": "阿列克谢耶夫", "степанов": "斯捷潘诺夫", "яковлев": "雅科夫列夫",
    "сорокин": "索罗金", "сергеев": "谢尔盖耶夫", "романов": "罗曼诺夫",
    "захаров": "扎哈罗夫", "борисов": "鲍里索夫", "королёв": "科罗廖夫",
    "герасимов": "格拉西莫夫", "григорьев": "格里戈里耶夫", "никитин": "尼基京",
    "жуков": "茹科夫", "фролов": "弗罗洛夫", "журавлёв": "茹拉夫廖夫",
    "николаев": "尼古拉耶夫", "крылов": "克雷洛夫",
    "максимов": "马克西莫夫", "медведев": "梅德韦杰夫", "ершов": "叶尔绍夫",
    "александр": "亚历山大", "александра": "亚历山德拉", "сергей": "谢尔盖",
    "дмитрий": "德米特里", "андрей": "安德烈", "алексей": "阿列克谢",
    "николай": "尼古拉", "владимир": "弗拉基米尔", "михаил": "米哈伊尔",
    "юрий": "尤里", "олег": "奥列格", "павел": "帕维尔", "роман": "罗曼",
    "максим": "马克西姆", "игорь": "伊戈尔", "антон": "安东",
    "екатерина": "叶卡捷琳娜", "татьяна": "塔季扬娜", "елена": "叶莲娜",
    "ольга": "奥尔加", "наталья": "娜塔莉亚", "анна": "安娜",
    "мария": "玛丽亚", "ирина": "伊琳娜", "светлана": "斯韦特兰娜",
    "людмила": "柳德米拉", "галина": "加林娜", "валентина": "瓦莲京娜",
    "юлия": "尤利娅", "вера": "薇拉", "надежда": "娜杰日达",
    "любовь": "柳博芙", "софья": "索菲亚", "ксения": "克谢尼娅",
}

# 音节表（辅音+元音优先匹配），用于词库里没有的名字
_SYLLABLES: Tuple[Tuple[str, str], ...] = (
    ("ща", "夏"), ("ще", "谢"), ("щи", "希"), ("щу", "舒"), ("шо", "绍"), ("ша", "沙"),
    ("ше", "舍"), ("ши", "希"), ("шу", "舒"), ("чо", "乔"), ("ча", "恰"), ("че", "切"),
    ("чи", "奇"), ("чу", "丘"), ("цо", "措"), ("ца", "察"), ("це", "采"), ("ци", "齐"),
    ("цу", "楚"), ("цы", "齐"), ("жа", "扎"), ("же", "热"), ("жи", "日"), ("жо", "若"),
    ("жу", "茹"), ("ша", "沙"), ("ю", "尤"), ("я", "亚"), ("ё", "约"),
    ("ба", "巴"), ("бе", "别"), ("би", "比"), ("бо", "博"), ("бу", "布"), ("бы", "贝"),
    ("ва", "瓦"), ("ве", "韦"), ("ви", "维"), ("во", "沃"), ("ву", "武"), ("вы", "维"),
    ("га", "加"), ("ге", "格"), ("ги", "吉"), ("го", "戈"), ("гу", "古"),
    ("да", "达"), ("де", "杰"), ("ди", "季"), ("до", "多"), ("ду", "杜"),
    ("за", "扎"), ("зе", "泽"), ("зи", "济"), ("зо", "佐"), ("зу", "祖"),
    ("ка", "卡"), ("ке", "克"), ("ки", "基"), ("ко", "科"), ("ку", "库"),
    ("ла", "拉"), ("ле", "列"), ("ли", "利"), ("ло", "洛"), ("лу", "卢"), ("лы", "雷"),
    ("ма", "马"), ("ме", "梅"), ("ми", "米"), ("мо", "莫"), ("му", "穆"),
    ("на", "纳"), ("не", "涅"), ("ни", "尼"), ("но", "诺"), ("ну", "努"),
    ("па", "帕"), ("пе", "佩"), ("пи", "皮"), ("по", "波"), ("пу", "普"),
    ("ра", "拉"), ("ре", "列"), ("ри", "里"), ("ро", "罗"), ("ру", "鲁"), ("ры", "雷"),
    ("са", "萨"), ("се", "谢"), ("си", "西"), ("со", "索"), ("су", "苏"), ("сы", "瑟"),
    ("та", "塔"), ("те", "捷"), ("ти", "季"), ("то", "托"), ("ту", "图"),
    ("фа", "法"), ("фе", "费"), ("фи", "菲"), ("фо", "福"), ("фу", "富"),
    ("ха", "哈"), ("хе", "赫"), ("хи", "希"), ("хо", "霍"), ("ху", "胡"),
)
_CONSONANTS: Dict[str, str] = {
    "б": "布", "в": "夫", "г": "格", "д": "德", "ж": "日", "з": "兹", "й": "伊",
    "к": "克", "л": "尔", "м": "姆", "н": "恩", "п": "普", "р": "尔", "с": "斯",
    "т": "特", "ф": "弗", "х": "赫", "ц": "茨", "ч": "奇", "ш": "什", "щ": "谢",
}
_VOWELS: Dict[str, str] = {
    "а": "阿", "е": "叶", "и": "伊", "о": "奥", "у": "乌", "ы": "厄", "э": "埃",
}


class NameTransliterator:
    """俄语姓名 → 中文音译（词典优先，音节表兜底）。"""

    def __init__(self, dictionary: Optional[Dict[str, str]] = None,
                 syllables: Optional[Sequence[Tuple[str, str]]] = None):
        merged = dict(DEFAULT_NAME_DICTIONARY)
        if dictionary:
            merged.update({k.casefold(): v for k, v in dictionary.items()})
        self.dictionary = merged
        self.syllables = list(syllables or _SYLLABLES)

    @classmethod
    def from_json_file(cls, path: str) -> "NameTransliterator":
        with open(path, "r", encoding="utf-8") as handle:
            payload = json.load(handle)
        rows = payload.get("names", payload) if isinstance(payload, dict) else payload
        table: Dict[str, str] = {}
        for row in rows:
            if isinstance(row, dict):
                ru = str(row.get("ru", "")).strip()
                zh = str(row.get("zh", "")).strip()
                if ru and zh:
                    table[ru.casefold()] = zh
        return cls(table)

    # -- 单词级 -------------------------------------------------------------
    def word(self, token: str) -> NameGuess:
        raw = (token or "").strip()
        key = raw.casefold()
        if key in self.dictionary:
            return NameGuess(raw, self.dictionary[key], "dictionary", 0.95)
        feminine = self._feminine(key)
        if feminine:
            return NameGuess(raw, feminine, "dictionary", 0.9)
        stripped = re.sub(r"[^\u0400-\u04ff\-]", "", raw)
        if not stripped:
            return NameGuess(raw, raw, "unchanged", 1.0)
        parts = [p for p in re.split(r"[-‑]", stripped) if p]
        han = "-".join(self._syllabify(p) for p in parts)
        return NameGuess(raw, han, "syllable", 0.5, review=True)

    def _feminine(self, key: str) -> Optional[str]:
        """女性姓氏由阳性词条推导：Смирнова → 斯米尔诺娃。"""
        for suffix, tail in (("ова", "娃"), ("ева", "娃"), ("ёва", "娃"),
                             ("ина", "娜"), ("ына", "娜")):
            if key.endswith(suffix):
                base = key[:-1]
                if base in self.dictionary:
                    han = self.dictionary[base]
                    if han.endswith("夫"):
                        return han[:-1] + "娃"
                    if han.endswith("京"):
                        return han[:-1] + "娜"
                    return han + tail
        if key.endswith(("ская", "цкая", "ная")):
            stem = self._syllabify(key[:-2])
            return stem + ("茨卡娅" if key.endswith("цкая") else "斯卡娅")
        return None

    def _syllabify(self, word: str) -> str:
        out: List[str] = []
        index = 0
        lowered = word.casefold().replace("ё", "е")
        while index < len(lowered):
            two = lowered[index:index + 2]
            hit = next((zh for syl, zh in self.syllables if syl == two), None)
            if hit:
                out.append(hit)
                index += 2
                continue
            char = lowered[index]
            if char in _CONSONANTS:
                out.append(_CONSONANTS[char])
            elif char in _VOWELS:
                out.append(_VOWELS[char])
            elif char in "ьъ":
                pass
            else:
                out.append(char)
            index += 1
        return "".join(out)

    # -- 全名 ---------------------------------------------------------------
    def full_name(self, name: str) -> NameGuess:
        """处理 ``Иванов И.И.`` / ``И.И. Иванов`` / ``Иванов`` 三种写法。"""
        text = (name or "").strip()
        if not text:
            return NameGuess(text, text, "unchanged", 1.0)
        tokens = text.split()
        results: List[str] = []
        methods: List[str] = []
        confidences: List[float] = []
        for token in tokens:
            if re.fullmatch(r"[А-ЯA-Z]\.(?:\s?[А-ЯA-Z]\.)*", token):
                results.append(token)  # 缩写保持原样，便于回溯
                methods.append("unchanged")
                confidences.append(1.0)
                continue
            guess = self.word(token)
            results.append(guess.han)
            methods.append(guess.method)
            confidences.append(guess.confidence)
        method = "dictionary" if all(m in ("dictionary", "unchanged") for m in methods) else "syllable"
        confidence = min(confidences) if confidences else 1.0
        return NameGuess(text, " ".join(results), method, confidence,
                         review=method == "syllable")

    def scan(self, text: str) -> List[NameGuess]:
        """从整段文本里挑出疑似俄语人名并给出音译建议。"""
        guesses: List[NameGuess] = []
        for match in re.finditer(r"\b[А-ЯЁ][а-яё]{2,}(?:\s+[А-ЯЁ]\.(?:\s?[А-ЯЁ]\.)?)?", text or ""):
            guess = self.full_name(match.group(0))
            if guess.method != "unchanged":
                guesses.append(guess)
        return guesses


def load_noise_bundle(path: str) -> Tuple[AbbreviationBook, NameTransliterator]:
    """从一个 JSON 文件同时加载缩写表与姓名表（校园数据文件格式）。"""
    book = AbbreviationBook()
    translator = NameTransliterator()
    if os.path.exists(path):
        book = AbbreviationBook.from_json_file(path)
        translator = NameTransliterator.from_json_file(path)
    return book, translator
