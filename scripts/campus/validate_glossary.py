#!/usr/bin/env python
"""术语库质检：加载 → 自检 → 报告。

用法::

    python scripts/campus/validate_glossary.py                 # 用仓库自带数据
    python scripts/campus/validate_glossary.py --dir data/glossary --profile campus_zh_ru
    python scripts/campus/validate_glossary.py --json report.json

退出码：0 = 通过（可能有 warning），1 = 存在 error 级问题。
老师/助教复核术语时，可以只看 ``--json`` 报告里 severity=error 的条目。
"""
import argparse
import json
import os
import sys


def main(argv=None):
    parser = argparse.ArgumentParser(description="Campus glossary QA")
    repo_root = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    parser.add_argument("--dir", default=os.path.join(repo_root, "data", "glossary"))
    parser.add_argument("--profile", default="campus_zh_ru")
    parser.add_argument("--json", dest="json_path", default="")
    parser.add_argument("--quiet", action="store_true")
    args = parser.parse_args(argv)

    if repo_root not in sys.path:
        sys.path.insert(0, repo_root)

    from libretranslate.campus import Glossary

    glossary = Glossary.from_json_dir(args.dir, profile=args.profile)
    issues = glossary.validate()
    errors = [i for i in issues if i.severity == "error"]
    report = {
        "directory": args.dir,
        "profile": args.profile,
        "stats": glossary.stats(),
        "issues": [
            {"code": i.code, "severity": i.severity, "zh": i.zh, "message": i.message}
            for i in issues
        ],
    }

    if not args.quiet:
        print("术语库：%s" % args.dir)
        print("条目数：%d" % len(glossary))
        print("领域分布：%s" % ", ".join("%s=%d" % kv for kv in glossary.domains().items()))
        print("带 note：%d  带 source：%d"
              % (report["stats"]["with_note"], report["stats"]["with_source"]))
        if issues:
            print("问题：")
            for issue in issues:
                print("  [%s] %s %s %s" % (issue.severity, issue.code, issue.zh, issue.message))
        else:
            print("问题：无")
        print("结论：%s" % ("通过" if not errors else "存在 %d 个 error" % len(errors)))

    if args.json_path:
        with open(args.json_path, "w", encoding="utf-8") as handle:
            json.dump(report, handle, ensure_ascii=False, indent=2)
        print("报告已写入：%s" % args.json_path)

    return 1 if errors else 0


if __name__ == "__main__":
    raise SystemExit(main())
