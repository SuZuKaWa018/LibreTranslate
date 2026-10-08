import os

__all__ = ["main", "manage"]


def __getattr__(name):
    """延迟导入重型入口。

    上游的 ``__init__`` 直接 ``from .main import main``，这会把
    Flask / argostranslate / argostranslatefiles 等一整套依赖在
    ``import libretranslate`` 时全部拉起来。校园工具链
    （``libretranslate.campus``）里的术语库、占位符保护、姓名音译等
    都是纯逻辑，应当能在**没有安装语言模型和 Argos 依赖**的环境里
    单独导入和单元测试（CI 不必下载 GB 级模型）。

    因此这里改为 PEP 562 的模块级 ``__getattr__``：属性访问时再导入，
    ``from libretranslate import main`` 与 ``libretranslate.main:main``
    这两个入口的用法保持不变。
    """
    if name == "main":
        from .main import main

        return main
    if name == "manage":
        from .manage import manage

        return manage
    raise AttributeError("module %r has no attribute %r" % (__name__, name))
