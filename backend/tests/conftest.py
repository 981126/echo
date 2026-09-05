"""pytest 会话级环境：测试数据目录指向临时目录，避免污染仓库/本机数据。"""

from __future__ import annotations

import os
import sys
import tempfile
from pathlib import Path

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

# 预建表 + seed 默认提示词，保证 get_prompt 等 DB 依赖离线可用
from app.db import init_db  # noqa: E402

init_db()
