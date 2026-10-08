"""校园中俄增强的测试包。

这些测试**不需要语言模型**，用假引擎覆盖 prepare/finish 两阶段，
因此可以在没有 argostranslate / Argos 模型的环境里直接运行：

    python -m unittest discover -s libretranslate/tests/campus -t .
    python scripts/campus/run_tests.py
"""
