"""纯逻辑测试（无第三方依赖，可离线运行；同时兼容 pytest）。"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.core.requirement_file import next_requirement_id, parse_requirement_file  # noqa: E402
from app.core.signature import (  # noqa: E402
    build_canonicalized_query,
    build_string_to_sign,
    content_md5,
    hmac_sha1_sign,
    utcnow_rfc1123,
)
from app.core.topics import is_valid_platform, normalize_main_topic  # noqa: E402
from app.core.transcript import (  # noqa: E402
    estimate_duration_seconds,
    normalize_text,
    split_sentences,
)


def test_normalize_main_topic():
    assert normalize_main_topic("求职") == "求职"
    assert normalize_main_topic("面试技巧") == "面试"
    assert normalize_main_topic("如何赚钱") == "赚钱"
    assert normalize_main_topic("知识分享") == "知识"
    assert normalize_main_topic("随便什么") == "其他"
    assert normalize_main_topic("") == "其他"
    assert normalize_main_topic(None) == "其他"


def test_platform():
    assert is_valid_platform("douyin")
    assert is_valid_platform("bilibili")
    assert is_valid_platform("xiaohongshu")
    assert not is_valid_platform("youtube")
    assert not is_valid_platform("")


def test_normalize_text():
    assert normalize_text("  你好\u3000世界  ") == "你好 世界"
    assert normalize_text("") == ""


def test_estimate_duration():
    text = "大家好" * 40  # 120 字
    assert estimate_duration_seconds(text) == 30  # 120 / 4 cps


def test_split_sentences():
    parts = split_sentences("第一句。第二句！第三句？")
    assert len(parts) == 3
    assert parts[0] == "第一句。"


def test_signature_helpers():
    assert content_md5(b"") == ""
    q = build_canonicalized_query({"b": "2", "a": "1"})
    assert q == "a=1&b=2"
    signed = hmac_sha1_sign("secret", "hello")
    assert isinstance(signed, str) and len(signed) > 10
    assert "GMT" in utcnow_rfc1123()
    sts = build_string_to_sign("POST", "application/json", b"{}", "application/json", "date", "", "/api?x=1")
    assert sts.startswith("POST\napplication/json")


def test_parse_requirement_file():
    text = "# R-003: 微信推送\n\n- **状态**: 已确认\n- **原文摘要**: 测试摘要\n"
    data = parse_requirement_file(text, "R-003.md")
    assert data["id"] == "R-003"
    assert data["title"] == "微信推送"
    assert data["status"] == "已确认"
    assert data["summary"] == "测试摘要"


def test_next_requirement_id():
    assert next_requirement_id([]) == "R-001"
    assert next_requirement_id(["R-001.md", "R-003.md"]) == "R-004"
    assert next_requirement_id(["README.md"]) == "R-001"


if __name__ == "__main__":
    fns = [v for k, v in sorted(globals().items()) if k.startswith("test_") and callable(v)]
    for fn in fns:
        fn()
        print(f"ok: {fn.__name__}")
    print(f"全部通过：{len(fns)} 个测试")
