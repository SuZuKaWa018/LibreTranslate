"""测试用的小工具。

Windows 沙箱环境下 ``tempfile.TemporaryDirectory`` 会以 0o700 创建目录，
由此得到的目录在当前会话里可能不可写，因此这里改用 ``os.makedirs``
在系统临时目录下自建 scratch 目录，并在用完后尽力清理。
"""
import os
import shutil
import tempfile
import uuid

_BASE = os.path.join(tempfile.gettempdir(), "lt-campus-tests")


def scratch_dir(name: str = "case") -> str:
    """返回一个可写、可清理的临时目录。"""
    path = os.path.join(_BASE, "%s-%s" % (name, uuid.uuid4().hex[:8]))
    os.makedirs(path, exist_ok=True)
    return path


def cleanup(path: str) -> None:
    shutil.rmtree(path, ignore_errors=True)
