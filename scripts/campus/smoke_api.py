#!/usr/bin/env python
"""HTTP 层冒烟测试：验证 /translate 的校园增强参数与两个新接口。

**前置条件**：装好本仓库的完整依赖与至少一个语言模型，例如

    pip install -e .
    python main.py --update-models        # 首次会下载模型，比较慢

然后运行：

    python scripts/campus/smoke_api.py
    python scripts/campus/smoke_api.py --source zh --target ru

脚本只做"能不能跑通、字段在不在"的检查，不判断译文质量。
没有模型的环境（例如只装了 campus 工具链的机器）请改用：

    python scripts/campus/run_tests.py      # 71 项单元测试，无需模型
    python scripts/campus/demo.py           # 离线对照排版演示
"""
import argparse
import json
import os
import sys


def main(argv=None):
    parser = argparse.ArgumentParser(description="Campus ZH-RU API smoke test")
    parser.add_argument("--source", default="zh")
    parser.add_argument("--target", default="ru")
    parser.add_argument("--text", default="本课程讲授数据结构与操作系统，教室 3-412。")
    parser.add_argument("--glossary-dir", default="data/glossary")
    args = parser.parse_args(argv)

    repo_root = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    if repo_root not in sys.path:
        sys.path.insert(0, repo_root)

    try:
        from libretranslate.app import create_app
        from libretranslate.main import get_parser
    except ImportError as exc:
        print("缺少依赖：%s" % exc)
        print("请先执行 pip install -e . （会安装 Flask / argostranslate 等）")
        return 2

    parsed = get_parser().parse_args([
        "--glossary-dir", args.glossary_dir,
        "--glossary", "campus_zh_ru",
    ])
    app = create_app(parsed)
    client = app.test_client()

    failures = []

    def check(name, condition, detail=""):
        print("[%s] %s %s" % ("PASS" if condition else "FAIL", name, detail))
        if not condition:
            failures.append(name)

    status = client.get("/campus/status")
    check("GET /campus/status", status.status_code == 200)
    if status.status_code == 200:
        payload = status.get_json()
        check("glossary loaded", payload.get("glossary", {}).get("count", 0) > 50,
              "count=%s" % payload.get("glossary", {}).get("count"))

    glossary = client.get("/campus/glossary?source=%s&target=%s" % (args.source, args.target))
    check("GET /campus/glossary", glossary.status_code == 200)
    if glossary.status_code == 200:
        payload = glossary.get_json()
        check("direct table present", bool(payload.get("direct")))

    response = client.post("/translate", json={
        "q": args.text,
        "source": args.source,
        "target": args.target,
        "campus": True,
    })
    check("POST /translate (campus=true)", response.status_code == 200,
          "status=%s" % response.status_code)
    if response.status_code == 200:
        payload = response.get_json()
        print(json.dumps(payload, ensure_ascii=False, indent=2)[:2000])
        check("translatedText present", bool(payload.get("translatedText")))
        check("campus audit block", isinstance(payload.get("campus"), dict))
        if isinstance(payload.get("campus"), dict):
            check("glossary matches recorded", len(payload["campus"].get("glossaryMatches", [])) > 0)
            check("no placeholder left", "[[" not in str(payload.get("translatedText", "")))

    inline = client.post("/translate", json={
        "q": "编译原理",
        "source": args.source,
        "target": args.target,
        "glossary": json.dumps([{"zh": "编译原理", "ru": "теория компиляции"}]),
    })
    check("POST /translate (inline glossary)", inline.status_code == 200)
    if inline.status_code == 200:
        payload = inline.get_json()
        check("inline glossary applied",
              "теория компиляции" in str(payload.get("translatedText", ""))
              or bool(payload.get("campus", {}).get("glossaryMatches")),
              str(payload.get("translatedText"))[:80])

    print()
    if failures:
        print("FAILED: %s" % ", ".join(failures))
        return 1
    print("ALL CHECKS PASSED")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
