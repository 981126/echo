"""ASR 转写适配器：mock（开发/测试）| 阿里云 FileTrans | 硅基流动 | 腾讯云（R-108/R-200）。"""

from __future__ import annotations

from pathlib import Path

from ..config import get_settings


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
        path = Path(video_path)
        if not path.exists():
            raise TranscriptionError(f"视频不存在: {path}")
        mode = (self.mode or self.settings.asr_mode or "mock").strip().lower()
        if mode == "mock":
            return self._mock_transcript(path)
        if mode == "aliyun":
            from .aliyun_filetrans import AliyunFileTrans  # 延迟导入，避免循环

            return AliyunFileTrans(settings=self.settings).transcribe_file(path)
        if mode == "siliconflow":
            from .siliconflow_asr import SiliconFlowASR  # 延迟导入，避免循环

            return SiliconFlowASR(settings=self.settings, model=self.model).transcribe_file(path)
        if mode == "tencent":
            from .tencent_asr import TencentAsr  # 延迟导入，避免循环

            return TencentAsr(settings=self.settings, model=self.model).transcribe_file(path)
        raise TranscriptionError(f"未知 asr_mode: {mode}")

    def _mock_transcript(self, path: Path) -> str:
        """开发/测试用确定性假转写稿（明显标注，防止误用）。"""
        name = path.stem.replace("_", " ").strip()
        return (
            f"[mock 转写] 大家好，今天我们来聊一聊{name}这个话题。"
            "很多人在求职和面试的时候都会遇到类似的问题，"
            "其实赚钱的思路并不复杂，关键是选对方向、持续积累。"
            "希望这条视频对你有帮助，我们下期再见。"
        )
