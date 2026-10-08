#!/usr/bin/env python
"""跑校园增强的测试（不需要语言模型）。

用法::

    python scripts/campus/run_tests.py            # 全部
    python scripts/campus/run_tests.py -v         # 详细输出

等价于::

    python -m unittest discover -s libretranslate/tests/campus -t .

之所以不依赖 pytest：校园工具链的目标是"任何一台没装模型的机器上都能自测"，
标准库的 unittest 已经够用；仓库 CI 里若装了 pytest 也能直接跑同一批用例。
"""
import os
import sys
import unittest


def main(argv):
    repo_root = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    if repo_root not in sys.path:
        sys.path.insert(0, repo_root)
    verbosity = 2 if "-v" in argv or "--verbose" in argv else 1
    start_dir = os.path.join(repo_root, "libretranslate", "tests", "campus")
    loader = unittest.TestLoader()
    suite = loader.discover(start_dir=start_dir, top_level_dir=repo_root)
    runner = unittest.TextTestRunner(verbosity=verbosity)
    result = runner.run(suite)
    return 0 if result.wasSuccessful() else 1


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
