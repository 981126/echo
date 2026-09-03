"""服务层测试（mock 外部依赖，需在安装依赖后运行：pytest）。"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from unittest.mock import MagicMock

from app.core.topics import normalize_main_topic
from app.services.llm import LLMError
from app.services.persona import PersonaService
from app.services.transcription import Transcriber


def test_persona_analyze_initial_parses_json():
    service = PersonaService(llm=MagicMock())
    service.llm.chat_json.return_value = {
        "tags": [{"label": "犀利敢说", "description": "喜欢一针见血"}],
        "redlines": ["不蹭负面热点"],
    }
    result = service.analyze_initial(["转写稿1", "转写稿2"])
    assert result["tags"][0]["label"] == "犀利敢说"
    assert result["redlines"] == ["不蹭负面热点"]


def test_persona_analyze_initial_fallback_without_key():
    service = PersonaService(llm=MagicMock())
    service.llm.chat_json.side_effect = LLMError("no key")
    result = service.analyze_initial(["x"])
    assert result == {"tags": [], "redlines": []}


def test_persona_suggest_video_tags():
    service = PersonaService(llm=MagicMock())
    service.llm.chat_json.return_value = {"main_topics": ["面试", "赚钱"], "is_ad": False, "tags": ["干货"]}
    result = service.suggest_video_tags("今天聊聊面试")
    assert result["main_topics"] == ["面试", "赚钱"]
    assert result["tags"] == ["干货"]


def test_persona_suggest_video_tags_normalizes_topic():
    service = PersonaService(llm=MagicMock())
    service.llm.chat_json.return_value = {"main_topics": ["求职技巧分享"], "is_ad": True, "tags": []}
    result = service.suggest_video_tags("广告内容")
    assert result["main_topics"] == [normalize_main_topic("求职技巧分享")] == ["求职"]
    assert result["is_ad"] is True


def test_transcriber_mock(tmp_path):
    p = tmp_path / "demo.mp4"
    p.write_bytes(b"fake")
    transcriber = Transcriber(MagicMock(asr_mode="mock"))
    text = transcriber.transcribe(p)
    assert "[mock 转写]" in text


def test_transcriber_missing_file():
    transcriber = Transcriber(MagicMock(asr_mode="mock"))
    try:
        transcriber.transcribe("/no/such/file.mp4")
        assert False, "应抛出异常"
    except Exception:
        pass
