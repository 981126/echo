"""pytest 会话级环境（R-235 改造）：

- 测试数据库固定为 PG 的 **echo_test** 库（安全闸门：指向其它库名直接拒绝启动，防误清开发库）；
  连接串从仓库根 `.env` 派生（密码只留在 .env，不进代码），可用环境变量覆盖；
- `fresh_engine()` 每测试清空全部表（TRUNCATE ... CASCADE），保持原 tmp SQLite「空库」语义；
- 表结构、视图和默认数据在导入时由 Alembic migration 建好，用例里不重复执行迁移；
- 测试数据目录指向临时目录，避免污染仓库/本机数据；并硬隔离外发邮件（R-221）与联网搜索（R-227）。
"""

from __future__ import annotations

import os
import sys
import tempfile
import time
from pathlib import Path

import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.engine import make_url
from sqlalchemy.exc import OperationalError
from sqlalchemy.pool import NullPool

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

# R-235：测试库固定 echo_test（与开发库 echo_dev 同实例不同库）。
# 连接串**不写死在代码里**：优先环境变量；否则从仓库根 .env 读 ECHO_DATABASE_URL，再把库名换成 echo_test
#（.env 正常指向 echo_dev，自动换库名 → 不可能误清开发库）。密码只存在 .env（gitignored）。
# 注意驱动写法必须是 postgresql+psycopg（SQLAlchemy 2.0 里裸 postgresql:// 默认找 psycopg2）。
def _test_database_url() -> str:
    raw = os.environ.get("ECHO_DATABASE_URL", "").strip()
    if not raw:
        env_file = Path(__file__).resolve().parents[2] / ".env"
        if env_file.exists():
            for line in env_file.read_text(encoding="utf-8").splitlines():
                if line.startswith("ECHO_DATABASE_URL="):
                    raw = line.split("=", 1)[1].strip().strip('"').strip("'")
                    break
    if not raw:
        raise RuntimeError(
            "pytest 需要数据库连接串：请在仓库根 .env 配置 ECHO_DATABASE_URL，"
            "或用环境变量 ECHO_DATABASE_URL 指向 echo_test 库。"
        )
    return make_url(raw).set(database="echo_test").render_as_string(hide_password=False)


os.environ["ECHO_DATABASE_URL"] = _test_database_url()

_TMP = tempfile.mkdtemp(prefix="echo-test-data-")
os.environ["ECHO_DATA_DIR"] = _TMP
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
# R-227：联网搜索同样会打到真实外部世界（豆包搜索 API），测试环境 fail-closed 关闭；
# 需要验证联网逻辑的用例自行 monkeypatch web_search。
os.environ["ECHO_WEB_SEARCH_API_KEY"] = ""

# R-235 安全闸门：测试只允许连 echo_test 库（大小写不敏感）。
_url = make_url(os.environ["ECHO_DATABASE_URL"])
_db_name = (_url.database or "").lower()
if _db_name != "echo_test":
    raise RuntimeError(
        f"R-235 安全闸门：pytest 只允许连接 echo_test 库，当前 ECHO_DATABASE_URL 指向 {_db_name!r}。"
        "请改为 echo_test（如 postgresql://…@yeah981.cn:15981/echo_test），切勿指向开发/生产库。"
    )

# 远端 PG（作者 NAS，公网 IPv6 链路）偶发瞬断：实测约 1.7% 新建连接在握手/查询途中被掐
#（server closed the connection / password authentication failed）。这类连接级错误与代码正确性
# 无关，统一识别后重试；断言失败等业务错误不在此列。
_TRANSIENT_DB_MARKERS = (
    "server closed the connection",
    "consuming input failed",
    "password authentication failed",
    "connection failed",
    "terminating connection",
)


def _is_transient_db_error(exc: BaseException) -> bool:
    blob = str(exc).lower()
    cause = exc.__cause__
    if cause is not None:
        blob += " " + str(cause).lower()
    return any(m in blob for m in _TRANSIENT_DB_MARKERS)


# 会话级执行版本化迁移，保证表、视图和默认数据齐全
from app.db import Base, engine  # noqa: E402
from app.migrations import run_migrations  # noqa: E402

for _attempt in range(3):
    try:
        run_migrations()
        break
    except OperationalError as _exc:
        if _attempt == 2 or not _is_transient_db_error(_exc):
            raise


def _kill_stale_transactions() -> None:
    """踢掉遗留的 idle-in-transaction 连接（多半来自上一个用例的后台线程）。

    不清掉它们的话，`TRUNCATE` 会和它们按不同顺序抢表锁 → `deadlock detected`
    （实测 test_r147 就因此 ERROR）。echo_test 是测试专用库，杀掉本库的空闲事务安全。
    """
    try:
        with engine.begin() as conn:
            conn.execute(
                text(
                    "SELECT pg_terminate_backend(pid) FROM pg_stat_activity "
                    "WHERE datname = current_database() AND pid <> pg_backend_pid() "
                    "AND state LIKE 'idle in transaction%'"
                )
            )
    except Exception:  # noqa: BLE001  清不干净也别让整个用例失败
        pass


def fresh_engine():
    """每个测试一个干净库：清空全部表（TRUNCATE ... RESTART IDENTITY CASCADE）。

    返回共享引擎（等价于原 tmp SQLite 空库语义：无残留数据、序列归零）。
    被清空的表来自 ORM metadata；Alembic 版本表不参与逐用例清理。
    `lock_timeout` + 重试：后台线程还攥着表锁时先让一步，避免整轮 verify 被一个死锁打断。
    """
    tables = ", ".join(t.name for t in Base.metadata.sorted_tables)
    for attempt in range(5):
        _kill_stale_transactions()
        try:
            with engine.begin() as conn:
                conn.execute(text("SET LOCAL lock_timeout = '10s'"))
                conn.execute(text(f"TRUNCATE TABLE {tables} RESTART IDENTITY CASCADE"))
            return engine
        except OperationalError as exc:
            msg = str(exc).lower()
            retryable = "deadlock" in msg or "lock timeout" in msg or "canceling statement" in msg or _is_transient_db_error(exc)
            if attempt < 4 and retryable:
                time.sleep(0.5 * (attempt + 1))
                continue
            raise
    return engine


@pytest.hookimpl(hookwrapper=True)
def pytest_runtest_call(item):
    """调用阶段遭遇远端 PG 瞬断时整用例重跑一次（只兜连接级错误，断言失败不重试）。

    用 hookwrapper 而不是 tryfirst：pytest_runtest_call 的所有实现**都会**被执行，
    tryfirst + item.runtest() 会让用例跑两遍（第二次撞上自己第一次的残留数据）。
    """
    outcome = yield
    try:
        outcome.get_result()
    except Exception as exc:
        if not _is_transient_db_error(exc):
            raise
        print(
            f"\n[R-235] 远端 PG 瞬断（{type(exc).__name__}），重跑该用例一次：{item.nodeid}",
            file=sys.stderr,
        )
        item.runtest()


def ensure_schema(_engine=None) -> None:
    """兼容既有用例；结构已在会话导入时由 Alembic migration 建好。"""


def make_fresh_engine():
    """独立引擎变体：清库后返回一个**新**引擎（隔离连接池，供需要独立事务边界的用例用）。"""
    eng = fresh_engine()
    return create_engine(eng.url.render_as_string(hide_password=False), poolclass=NullPool)


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
