"""R-188：每周灵感补给文案拼装。"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.services.opportunity import digest_message


def test_digest_gap_first_and_limit():
    pack = [{"title": "热榜选题A", "reason": "今日热榜"}, {"title": "评论选题B", "reason": "评论区被问 3 次"}]
    gap = [{"title": "缺口选题X", "reason": "该讲没讲过"}]
    msg, total = digest_message(pack, gap, limit=2)
    assert total == 3
    assert msg.index("缺口选题X") < msg.index("热榜选题A")  # 缺口优先
    assert "另有 1 条" in msg


def test_digest_empty():
    msg, total = digest_message([], [])
    assert total == 0 and msg == ""
