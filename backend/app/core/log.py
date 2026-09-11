"""统一日志（R-133）。

背景：全后端此前**零日志设施**，53 处 `except Exception` 只做 `pass`/`rollback()`，
导致转写失败、定时任务失败、备份失败、素材丢失等全部不可观测。
这里提供最小可用的统一 logger：`get_logger("tasks")` → 输出到 stdout，格式含时间/级别/模块。
"""

from __future__ import annotations

import logging
import sys

_CONFIGURED = False
_FORMAT = "%(asctime)s %(levelname)s %(name)s: %(message)s"


def setup_logging(level: int = logging.INFO) -> None:
    """进程启动时调用一次（幂等）。"""
    global _CONFIGURED
    if _CONFIGURED:
        return
    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(logging.Formatter(_FORMAT))
    root = logging.getLogger()
    root.setLevel(level)
    if not any(isinstance(h, logging.StreamHandler) for h in root.handlers):
        root.addHandler(handler)
    _CONFIGURED = True


def get_logger(name: str) -> logging.Logger:
    """取带 echo. 前缀的 logger（不依赖 setup_logging 也已可用）。"""
    return logging.getLogger(f"echo.{name}")


__all__ = ["setup_logging", "get_logger"]
