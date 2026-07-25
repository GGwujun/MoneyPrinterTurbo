"""Vendored copy of blogger-distiller ``scripts/``.

这些脚本使用「同级绝对导入」: ``from utils.tikhub_client import ...``、
``from verify import ...``、``from analyze import detect_platform``、
``from crawl_common import ...``。它们假定自己运行在 ``scripts/`` 目录下,
``utils`` / ``analyze`` / ``verify`` 等是顶层模块。

为了让这些脚本**零改写**地在 MoneyPrinterTurbo 进程里被导入, 这里在 import
时把本目录 (vendor/) 插入 ``sys.path``。这样 vendored 脚本的同级导入就能
原样解析到 ``vendor/utils/``、``vendor/analyze.py`` 等。

MoneyPrinterTurbo 没有顶层 ``utils``/``analyze``/``verify`` 模块 (它用的是
``app.utils``), site-packages 里也没有顶层 ``utils``, 因此不会产生命名冲突。
插入是幂等的。
"""
import os
import sys

_VENDOR_DIR = os.path.dirname(os.path.abspath(__file__))

# 必须在任何 vendored 子模块被导入之前完成, 所以放在包 __init__ 顶部。
if _VENDOR_DIR not in sys.path:
    sys.path.insert(0, _VENDOR_DIR)
