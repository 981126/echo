"""pytest 会话级环境：测试数据目录指向临时目录，避免污染仓库/本机数据；并硬隔离外发邮件（R-221）。"""

from __future__ import annotations

import os
import sys
import tempfile
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

_TMP = tempfile.mkdtemp(prefix="echo-test-data-")
os.environ["ECHO_DATA_DIR"] = _TMP
os.environ["ECHO_DB_PATH"] = os.path.join(_TMP, "test.db")
os.environ["ECHO_ACCESS_TOKEN"] = ""
os.environ["ECHO_ASR_MODE"] = "mock"
os.environ["ECHO_HOT_SOURCE_MODE"] = "mock"
os.environ["ECHO_TIKHUB_MODE"] = "mock"
os.environ["ECHO_DEEPSEEK_API_KEY"] = ""
os.environ["ECHO_KIMI_API_KEY"] = ""
# R-221：邮件是唯一「测试会打到真实外部世界」的通道。`app/config.py` 的 env_file=(".env", "../.env")
# 让 pytest（CWD=backend）读到仓库根 .env 里的真实 QQ SMTP 配置 —— 于是 tests/test_r208_daily_best.py
# 里 `push_daily_best` 的夹具稿（选题B / B 的口播稿正文）被当成「今日最佳」真发给了作者，
# 每次 verify.sh（跑 pytest）就多一封垃圾邮件。这里显式清空（环境变量优先级高于 .env）→
# `mail_config_problem()` 必然返回「未配置」→ 任何用例都走不到 SMTP，fail-closed。
os.environ["ECHO_SMTP_USER"] = ""
os.environ["ECHO_SMTP_AUTH_CODE"] = ""
os.environ["ECHO_MAIL_TO"] = ""

# 预建表 + seed 默认提示词，保证 get_prompt 等 DB 依赖离线可用
from app.db import init_db  # noqa: E402

init_db()


class RealMailAttempted(BaseException):  # noqa: N818 故意不继承 Exception（见下）
    """测试里尝试真实连 SMTP 时抛出（R-221 兜底闸门）。

    故意继承 `BaseException`：`notify._send` 只收敛 `Exception`（R-141），
    所以这个异常会直接炸穿用例，而不是被吞成「返回 False」后悄悄发出去。
    """


@pytest.fixture(autouse=True)
def _forbid_real_mail(monkeypatch):
    """兜底闸门（R-221）：即使某个用例把 SMTP 配置补回来，也不允许真的连出去。"""
    from app.services import notify as notify_mod

    def _tripwire(*_args, **_kwargs):
        raise RealMailAttempted("R-221：测试环境禁止真实发信（conftest 兜底闸门拦下）")

    monkeypatch.setattr(notify_mod.smtplib, "SMTP_SSL", _tripwire)
    yield
