#!/usr/bin/env python
"""离线演示：不装语言模型也能看到完整效果。

演示内容是一份校园通知（含课程编号、日期、邮箱、电话、专业术语、俄方教师姓名），
跑完整条链路：**规范化 → 术语遮蔽 → 编号保护 → 翻译 → 回填 → 中俄对照排版**。

输出：

* ``demo_output/notice_zh_ru.md``     中俄对照排版
* ``demo_output/notice_zh_ru.docx``   中俄对照 Word（装了 python-docx 时）
* ``demo_output/audit.json``          逐句审计信息（命中的术语、保护片段、告警）
* ``demo_output/glossary_preview.md`` 术语库抽样

关于"引擎"：这里不用模型，而是用一组**人工写好的俄语译文模板**充当引擎输出，
模板里保留 ``[[T1]]`` 这样的占位符，用来演示"翻译结果必须原样带回占位符"这一约束，
以及回填失败时的降级路径。真实上线请用 ``translate_docs.py --engine argos``
或直接调用本项目的 HTTP API。
"""
import json
import os
import sys

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
if REPO_ROOT not in sys.path:
    sys.path.insert(0, REPO_ROOT)

from libretranslate.campus import (  # noqa: E402
    AbbreviationBook,
    CampusOptions,
    Glossary,
    NameTransliterator,
    build_campus_translator,
)
from libretranslate.campus.templates import AlignedPair, BilingualDoc  # noqa: E402

GLOSSARY_DIR = os.path.join(REPO_ROOT, "data", "glossary")
NOISE_FILE = os.path.join(GLOSSARY_DIR, "campus_noise.json")
OUT_DIR = os.path.join(REPO_ROOT, "demo_output")

TITLE = "关于 2026 年春季学期选课的通知"

BODY = [
    "各位同学：2026年春季学期选课将于 2026年5月12日 开始，请登录教务系统完成选课。",
    "本次开放的课程包括数据结构、操作系统、算法设计与分析、离散数学与概率论。",
    "数据结构（课程号 МА101）与操作系统（课程号 МА102）为先修课程，教室为 3-412。",
    "如有疑问请联系教务处 И.И. Иванов，邮箱 jwc@smbu.edu.cn，电话 +86 755 1234 5678。",
    "未按期完成选课的同学，将影响本学期学分认定与奖学金评定。",
]

# 每个函数拿到的 t 是"本条句子里全部占位符"，按分配顺序排列；
# 模板里保留占位符，交给 finish() 回填成术语库里的标准译法。
RU_TEMPLATES = [
    # 标题：t[0] = 通知
    lambda t, p: "%s о выборе дисциплин на весенний семестр 2026 года" % t[0],
    # t[0] = 2026年5月12日
    lambda t, p: ("Уважаемые студенты! Выбор дисциплин на весенний семестр 2026 года начнётся "
                  "%s. Пожалуйста, войдите в учебную систему и завершите выбор." % t[0]),
    # t = 数据结构 / 操作系统 / 算法设计与分析 / 离散数学 / 概率论
    lambda t, p: "В этом семестре открыты следующие дисциплины: %s." % ", ".join(t),
    # t[0]=数据结构 t[1]=操作系统 t[2]=МА101 t[3]=МА102 t[4]=3-412
    lambda t, p: ("%s (код курса %s) и %s (код курса %s) являются предшествующими дисциплинами, "
                  "аудитория %s." % (t[0], t[2], t[1], t[3], t[4])),
    # t[0]=教务处 t[1]=邮箱 t[2]=电话 t[3]=И.И.
    lambda t, p: ("По вопросам обращайтесь в %s, %s Иванов, эл. почта %s, тел. %s."
                  % (t[0], t[3], t[1], t[2])),
    # t[0]=学分 t[1]=奖学金
    lambda t, p: ("Студенты, не завершившие выбор дисциплин в срок, столкнутся с последствиями "
                  "для учёта %s и назначения %s в этом семестре." % (t[0], t[1])),
]


def demo_engine(texts, source, target):
    """占位直通引擎：演示时不调用模型（真正翻译见 translate_docs.py --engine argos）。"""
    return list(texts)


def main():
    glossary = Glossary.from_json_dir(GLOSSARY_DIR, profile="campus_zh_ru")
    abbreviations = AbbreviationBook.from_json_file(NOISE_FILE)
    names = NameTransliterator.from_json_file(NOISE_FILE)
    translator = build_campus_translator(demo_engine, glossary_dir=GLOSSARY_DIR,
                                        profile="campus_zh_ru", noise_file=NOISE_FILE)
    options = CampusOptions(source="zh", target="ru", suggest_names=True)

    os.makedirs(OUT_DIR, exist_ok=True)
    print("=" * 78)
    print("中俄校园翻译增强 · 离线演示")
    print("=" * 78)
    print("术语库：%d 条，领域分布 %s" % (len(glossary), glossary.domains()))
    print("保护规则：%s" % ", ".join(p.name for p in translator.protector.patterns))
    print("缩写表：%d 条；人名表：%d 条" % (len(abbreviations), len(names.dictionary)))
    print()

    units = [TITLE] + BODY
    pairs = [None] * len(units)
    audits = []
    for index, unit in enumerate(units):
        request = translator.prepare(unit, options)
        tokens = [slot.token() for slot in request.table.slots]
        translated = RU_TEMPLATES[index](tokens, request)
        result = translator.finish(request, translated)
        pairs[index] = (unit, result.text, request.text)
        audits.append({
            "index": index,
            "source": unit,
            "masked": request.text,
            "translated": result.text,
            "glossaryMatches": [
                {"origin": m.origin, "target": m.value, "domain": m.term.domain}
                for m in result.matches
            ],
            "protected": [{"rule": rule, "text": text} for rule, text in result.protected],
            "nameSuggestions": [
                {"source": g.source, "han": g.han, "method": g.method, "review": g.review}
                for g in result.names
            ],
            "placeholderRestoreRate": round(result.restore_rate, 4),
            "warnings": list(result.warnings),
        })
        print("原文  ：%s" % unit)
        print("遮蔽后：%s" % request.text)
        print("译文  ：%s" % result.text)
        if result.names:
            print("人名  ：%s" % "；".join("%s → %s%s" % (g.source, g.han,
                                                        "（待复核）" if g.review else "")
                                          for g in result.names))
        print("-" * 78)

    doc = BilingualDoc(
        title_zh=TITLE,
        title_ru=pairs[0][1],
        pairs=[AlignedPair(i, left, right)
               for i, (left, right, _masked) in enumerate(pairs[1:])],
        meta={"术语库": "campus_zh_ru（%d 条）" % len(glossary),
              "引擎": "离线演示模板（占位符感知）",
              "术语命中": str(sum(len(a["glossaryMatches"]) for a in audits))},
        warnings=sorted({w for audit in audits for w in audit["warnings"]}),
    )

    md_path = os.path.join(OUT_DIR, "notice_zh_ru.md")
    with open(md_path, "w", encoding="utf-8", newline="\n") as handle:
        handle.write(doc.render("paragraph"))
    print("已写出：%s" % md_path)

    audit_path = os.path.join(OUT_DIR, "audit.json")
    with open(audit_path, "w", encoding="utf-8", newline="\n") as handle:
        json.dump({"segments": audits, "glossary": glossary.stats()}, handle,
                  ensure_ascii=False, indent=2)
    print("已写出：%s" % audit_path)

    preview_path = os.path.join(OUT_DIR, "glossary_preview.md")
    with open(preview_path, "w", encoding="utf-8", newline="\n") as handle:
        handle.write("# 术语库抽样（campus_zh_ru）\n\n")
        handle.write("| 中文 | 俄语 | 英语 | 领域 | 备注 |\n| --- | --- | --- | --- | --- |\n")
        for term in glossary.terms[:40]:
            handle.write("| %s | %s | %s | %s | %s |\n"
                         % (term.zh, term.ru, term.en, term.domain, term.note[:40]))
    print("已写出：%s" % preview_path)

    try:
        import docx  # noqa: F401

        from scripts.campus.translate_docs import write_docx

        docx_path = os.path.join(OUT_DIR, "notice_zh_ru.docx")
        write_docx(docx_path, doc.pairs, doc.title_zh, doc.title_ru)
        print("已写出：%s" % docx_path)
    except Exception as exc:  # pragma: no cover - 取决于环境
        print("跳过 DOCX 输出（%s）" % exc)

    total_matches = sum(len(a["glossaryMatches"]) for a in audits)
    total_protected = sum(len(a["protected"]) for a in audits)
    rates = [a["placeholderRestoreRate"] for a in audits]
    print()
    print("术语命中合计：%d，保护片段合计：%d，占位符回填率：%.0f%%"
          % (total_matches, total_protected, 100 * sum(rates) / len(rates)))
    print("命中术语：%s" % "、".join(
        "%s→%s" % (m["origin"], m["target"]) for a in audits for m in a["glossaryMatches"]))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
