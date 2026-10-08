#!/usr/bin/env python
"""批量文档翻译 / 一键中俄对照排版。

支持 txt / md / docx。两种引擎：

* ``--engine offline``（默认）：只用术语库直出替换 + 编号保护，不需要模型。
  适合课程名、通知抬头、成绩单这类"术语密集型"材料。
* ``--engine argos``：调用本仓库自带的 Argos 引擎（需已安装语言模型），
  中文↔俄语无直连模型时会经英语中转（pivot）。

示例::

    # 离线术语直出，生成中俄对照 markdown
    python scripts/campus/translate_docs.py -i notice.md -o out/notice.md --layout paragraph

    # 有模型时走真正的机器翻译
    python scripts/campus/translate_docs.py -i notice.txt -o out/notice.docx --engine argos
"""
import argparse
import os
import sys

LAYOUTS = ("interleaved", "side-by-side", "paragraph", "table")


def build_engine(name, glossary_dir, profile, noise_file):
    """返回 (translate_fn, translator)。"""
    repo_root = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    if repo_root not in sys.path:
        sys.path.insert(0, repo_root)
    from libretranslate.campus import CampusOptions, build_campus_translator

    if name == "offline":
        # 直通引擎：术语已经在 prepare 阶段被替换，这里原样返回即可
        translator = build_campus_translator(
            lambda texts, src, tgt: list(texts),
            glossary_dir=glossary_dir, profile=profile, noise_file=noise_file,
        )
        options = CampusOptions(use_glossary=True, glossary_strict=False, protect_noise=True)
        return translator, options

    from argostranslate import translate as argos_translate

    languages = {lang.code: lang for lang in argos_translate.get_installed_languages()}

    def engine(texts, source, target):
        outputs = []
        for text in texts:
            outputs.append(_translate_with_pivot(languages, text, source, target))
        return outputs

    translator = build_campus_translator(engine, glossary_dir=glossary_dir, profile=profile,
                                         noise_file=noise_file)
    return translator, CampusOptions()


def _translate_with_pivot(languages, text, source, target):
    """优先直连，其次经英语中转。"""
    src = languages.get(source)
    tgt = languages.get(target)
    if src is not None and tgt is not None:
        direct = src.get_translation(tgt)
        if direct is not None:
            return direct.translate(text)
    pivot = languages.get("en")
    if src is None or pivot is None or tgt is None:
        raise RuntimeError("缺少 %s→%s 的语言模型（可先执行 libretranslate --update-models）"
                           % (source, target))
    first = src.get_translation(pivot)
    second = pivot.get_translation(tgt)
    if first is None or second is None:
        raise RuntimeError("缺少经英语中转的模型：%s→en→%s" % (source, target))
    return second.translate(first.translate(text))


def read_docx(path):
    import docx  # python-docx

    document = docx.Document(path)
    paragraphs = [p.text for p in document.paragraphs]
    return paragraphs


def write_docx(path, pairs, title_zh, title_ru):
    import docx

    document = docx.Document()
    if title_zh:
        document.add_heading(title_zh, level=1)
    if title_ru:
        document.add_heading(title_ru, level=2)
    for pair in pairs:
        document.add_paragraph(pair.left)
        ru = document.add_paragraph(pair.right)
        ru.style = document.styles["Normal"]
        for run in ru.runs:
            run.italic = True
    os.makedirs(os.path.dirname(os.path.abspath(path)), exist_ok=True)
    document.save(path)


def main(argv=None):
    repo_root = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    parser = argparse.ArgumentParser(description="Campus bilingual document translation")
    parser.add_argument("-i", "--input", required=True)
    parser.add_argument("-o", "--output", required=True)
    parser.add_argument("--source", default="zh")
    parser.add_argument("--target", default="ru")
    parser.add_argument("--engine", default="offline", choices=("offline", "argos"))
    parser.add_argument("--layout", default="interleaved", choices=LAYOUTS)
    parser.add_argument("--glossary-dir", default=os.path.join(repo_root, "data", "glossary"))
    parser.add_argument("--profile", default="campus_zh_ru")
    parser.add_argument("--noise-file", default="")
    parser.add_argument("--title", default="")
    args = parser.parse_args(argv)

    noise_file = args.noise_file or os.path.join(args.glossary_dir, "campus_noise.json")
    translator, options = build_engine(args.engine, args.glossary_dir, args.profile, noise_file)
    options.source = args.source
    options.target = args.target

    ext = os.path.splitext(args.input)[1].lower()
    if ext == ".docx":
        units = read_docx(args.input)
    else:
        with open(args.input, "r", encoding="utf-8") as handle:
            raw = handle.read()
        units = [line for line in raw.split("\n") if line.strip()]
    if not units:
        print("输入文件没有可翻译的段落")
        return 1

    pairs = []
    matches_total = 0
    warnings = []
    for index, unit in enumerate(units):
        result = translator.translate(unit, options)
        matches_total += len(result.matches)
        warnings.extend(result.warnings)
        pairs.append((unit, result.text))

    from libretranslate.campus.templates import AlignedPair, BilingualDoc

    doc = BilingualDoc(
        title_zh=args.title if args.source.startswith("zh") else "",
        title_ru=args.title if args.source.startswith("ru") else "",
        pairs=[AlignedPair(i, left, right) for i, (left, right) in enumerate(pairs)],
        meta={"术语命中": str(matches_total), "引擎": args.engine},
        warnings=warnings,
    )
    os.makedirs(os.path.dirname(os.path.abspath(args.output)), exist_ok=True)
    if args.output.lower().endswith(".docx"):
        write_docx(args.output, doc.pairs, doc.title_zh, doc.title_ru)
    else:
        with open(args.output, "w", encoding="utf-8", newline="\n") as handle:
            handle.write(doc.render(args.layout))
    print("已生成：%s" % args.output)
    print("段落：%d  术语命中：%d  警告：%d" % (len(pairs), matches_total, len(warnings)))
    for warning in warnings[:5]:
        print("  ! %s" % warning)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
