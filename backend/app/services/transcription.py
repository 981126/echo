"""ASR 转写适配器：mock（开发/测试）| 阿里云 FileTrans | 硅基流动 | 腾讯云（R-108/R-200）。"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

from ..config import get_settings

TRANSCRIPT_PRECISION = ("sentence", "chunk", "none")


@dataclass(frozen=True)
class TranscriptResult:
    """转写结果（R-265）：正文 + 分句时间轴 + 精度。

    `sentences` 为 `[{"start_ms": int, "end_ms": int, "text": str}]`；
    `precision=sentence` 才能把留存掉点指到具体句子，`chunk` 只到 ASR 分片窗口。
    """

    text: str
    sentences: list[dict] = field(default_factory=list)
    source: str = ""
    precision: str = "none"


class TranscriptionError(RuntimeError):
    pass


class Transcriber:
    """统一转写入口：根据 asr_mode 选择实现。

    R-138/R-139：`mode` / `model` 可由调用方从运行时配置（`app_kv`）传入，
    这样在「AI 设置」里改 ASR 后**下一次转写立即生效**，无需重启。
    """

    def __init__(self, settings=None, mode: str | None = None, model: str | None = None):
        self.settings = settings or get_settings()
        self.mode = mode
        self.model = model

    def transcribe(self, video_path: Path | str) -> str:
        return self.transcribe_detailed(video_path).text

    def transcribe_detailed(self, video_path: Path | str) -> TranscriptResult:
        """转写并返回分句时间轴（R-265）；不支持分句的服务商 precision=none。"""
        path = Path(video_path)
        if not path.exists():
            raise TranscriptionError(f"视频不存在: {path}")
        mode = (self.mode or self.settings.asr_mode or "mock").strip().lower()
        if mode == "mock":
            return TranscriptResult(self._mock_transcript(path), [], "mock", "none")
        if mode == "aliyun":
            from .aliyun_filetrans import AliyunFileTrans  # 延迟导入，避免循环

            return self._detailed(AliyunFileTrans(settings=self.settings), path, "aliyun")
        if mode == "siliconflow":
            from .siliconflow_asr import SiliconFlowASR  # 延迟导入，避免循环

            provider = SiliconFlowASR(settings=self.settings, model=self.model)
            return self._detailed(provider, path, "siliconflow")
        if mode == "tencent":
            from .tencent_asr import TencentAsr  # 延迟导入，避免循环

            return self._detailed(TencentAsr(settings=self.settings, model=self.model), path, "tencent")
        if mode == "deepseek":
            from .deepseek_asr import DeepSeekAsr  # 延迟导入，避免循环

            return self._detailed(DeepSeekAsr(settings=self.settings), path, "deepseek")
        raise TranscriptionError(f"未知 asr_mode: {mode}")

    @staticmethod
    def _detailed(provider, path: Path, source: str) -> TranscriptResult:
        """服务商支持分句就用分句；只实现文本的（或测试替身）退回 precision=none。"""
        detailed = getattr(provider, "transcribe_detailed", None)
        if callable(detailed):
            return detailed(path)
        return TranscriptResult(provider.transcribe_file(path), [], source, "none")

    def _mock_transcript(self, path: Path) -> str:
        """开发/测试用确定性假转写稿（明显标注，防止误用）。"""
        name = path.stem.replace("_", " ").strip()
        return (
            f"[mock 转写] 大家好，今天我们来聊一聊{name}这个话题。"
            "很多人在求职和面试的时候都会遇到类似的问题，"
            "其实赚钱的思路并不复杂，关键是选对方向、持续积累。"
            "希望这条视频对你有帮助，我们下期再见。"
        )
