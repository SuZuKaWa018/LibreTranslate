"""占位符机制（Placeholder protection）。

翻译流程里有两类片段必须"原样穿过"机器翻译引擎：

1. 术语库命中的词条 —— 我们希望译文直接使用人工审定的标准译法，
   而不是模型自由发挥的译法；
2. 校园场景的"噪音" —— 课程编号、教室号、学号、邮箱、URL、公式编号等，
   它们不应该被翻译，但经常被模型改写或吞掉。

做法是先把这些片段替换成带序号的占位符（默认 ``[[T1]]``），翻译完成后再回填。
占位符能否活下来取决于底层引擎，因此 :meth:`PlaceholderTable.restore` 采用
由严到宽的多轮匹配，并把彻底丢失的槽位报告出来，供上层决定如何降级处理。

本模块不依赖任何翻译引擎，可单独单元测试。
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Dict, Iterable, List, Optional, Sequence

DEFAULT_OPEN = "[["
DEFAULT_MARK = "T"
DEFAULT_CLOSE = "]]"

# 严格匹配我们自己写出的占位符。
_STRICT_RE = re.compile(r"\[\[\s*T(\d{1,4})\s*\]\]")
# 放宽匹配：引擎常常把方括号换成其它括号、大小写改写、或在中间插入空格。
_LOOSE_RE = re.compile(r"[\[\(\{<«]\s*[TtТт]\s*(\d{1,4})\s*[\]\)\}>»]")
# 最宽松匹配：只剩 T 和数字（默认不开启，避免误伤正文里的 "T1"）。
_BARE_RE = re.compile(r"(?<![0-9A-Za-z])[TtТт]\s?(\d{1,4})(?![0-9A-Za-z])")


@dataclass
class Slot:
    """一个被占位符保护的片段。"""

    index: int
    origin: str
    value: str
    kind: str = "term"
    meta: Dict[str, object] = field(default_factory=dict)

    def token(self, open_: str = DEFAULT_OPEN, mark: str = DEFAULT_MARK,
              close: str = DEFAULT_CLOSE) -> str:
        return "{}{}{}{}".format(open_, mark, self.index, close)


@dataclass
class RestoreResult:
    """回填结果。"""

    text: str
    restored: List[Slot] = field(default_factory=list)
    lost: List[Slot] = field(default_factory=list)
    duplicated: List[Slot] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return not self.lost

    @property
    def restore_rate(self) -> float:
        total = len(self.restored) + len(self.lost)
        if total == 0:
            return 1.0
        return len(self.restored) / float(total)


class PlaceholderTable:
    """分配占位符并在译文里回填。

    同一个 ``(kind, value)`` 只分配一个槽位，这样重复出现的术语共享一个占位符，
    即使引擎把复现位置合并或重排也能正确回填。
    """

    def __init__(self, open_: str = DEFAULT_OPEN, mark: str = DEFAULT_MARK,
                 close: str = DEFAULT_CLOSE, start_index: int = 1):
        self.open = open_
        self.mark = mark
        self.close = close
        self._next = start_index
        self._by_key: Dict[tuple, Slot] = {}
        self._by_index: Dict[int, Slot] = {}

    # -- 构建 ---------------------------------------------------------------
    def add(self, origin: str, value: str, kind: str = "term",
            meta: Optional[Dict[str, object]] = None) -> Slot:
        key = (kind, value)
        if key in self._by_key:
            return self._by_key[key]
        slot = Slot(index=self._next, origin=origin, value=value, kind=kind,
                    meta=dict(meta or {}))
        self._next += 1
        self._by_key[key] = slot
        self._by_index[slot.index] = slot
        return slot

    def token_for(self, origin: str, value: str, kind: str = "term",
                  meta: Optional[Dict[str, object]] = None) -> str:
        return self.add(origin, value, kind, meta).token(self.open, self.mark, self.close)

    def render(self, segments: Sequence[object]) -> str:
        """把 ``str`` 与 :class:`Slot` 混排的片段拼成待翻译文本。"""
        out: List[str] = []
        for seg in segments:
            if isinstance(seg, Slot):
                out.append(seg.token(self.open, self.mark, self.close))
            else:
                out.append(str(seg))
        return "".join(out)

    # -- 查询 ---------------------------------------------------------------
    @property
    def slots(self) -> List[Slot]:
        return [self._by_index[i] for i in sorted(self._by_index)]

    def __len__(self) -> int:
        return len(self._by_index)

    def __contains__(self, index: int) -> bool:
        return int(index) in self._by_index

    # -- 回填 ---------------------------------------------------------------
    def restore(self, text: str, loose: bool = True,
                allow_bare: bool = False) -> RestoreResult:
        """把译文里的占位符换回 :attr:`Slot.value`。"""
        result = RestoreResult(text=text or "")
        if not self._by_index:
            return result

        seen: Dict[int, int] = {}

        def _sub(match: "re.Match") -> str:
            idx = int(match.group(1))
            slot = self._by_index.get(idx)
            if slot is None:
                return match.group(0)
            seen[idx] = seen.get(idx, 0) + 1
            return slot.value

        working = _STRICT_RE.sub(_sub, result.text)
        if loose:
            working = _LOOSE_RE.sub(_sub, working)
        if allow_bare:
            working = _BARE_RE.sub(_sub, working)
        result.text = working

        for idx in sorted(seen):
            slot = self._by_index[idx]
            result.restored.append(slot)
            if seen[idx] > 1:
                result.duplicated.append(slot)
        for idx in sorted(self._by_index):
            if idx not in seen:
                result.lost.append(self._by_index[idx])
        return result

    def leftovers(self, text: str) -> List[int]:
        """返回文本里仍然残留的、属于本表的占位符序号（用于质量断言）。"""
        found = set()
        for regex in (_STRICT_RE, _LOOSE_RE):
            for match in regex.finditer(text or ""):
                idx = int(match.group(1))
                if idx in self._by_index:
                    found.add(idx)
        return sorted(found)


def iter_placeholders(text: str) -> Iterable[int]:
    """列出文本里出现的（任何表的）占位符序号，供调试使用。"""
    for regex in (_STRICT_RE, _LOOSE_RE):
        for match in regex.finditer(text or ""):
            yield int(match.group(1))
