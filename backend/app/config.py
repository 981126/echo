"""应用配置：全部来自环境变量（.env），前缀 ECHO_。"""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path

from pydantic import model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


_MODE_CHOICES = {
    "tikhub_mode": {"mock", "real"},
    "hot_source_mode": {"mock", "real"},
    "asr_mode": {"mock", "aliyun", "siliconflow"},  # R-108：ASR 服务商可切硅基流动
}
_MODE_DEFAULTS = {"tikhub_mode": "mock", "hot_source_mode": "mock", "asr_mode": "mock"}


def normalize_mode(value, allowed: set[str], default: str) -> str:
    """解析模式值：去掉行尾注释黏连/空白；非法值直接抛错（不静默回退 mock，防假数据覆盖真实数据）。

    例：.env 里 `ECHO_TIKHUB_MODE=real# mock | real`（注释黏连）→ real。
    """
    raw = str(value or default).split("#", 1)[0].strip().lower()
    if raw not in allowed:
        raise ValueError(
            f"不支持的配置值 {raw!r}，允许：{'/'.join(sorted(allowed))}（检查 .env 对应行是否注释黏连，如 TIKHUB_MODE=real# ...）"
        )
    return raw


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="ECHO_", env_file=(".env", "../.env"), extra="ignore")

    # 访问令牌（Web 入口校验）
    access_token: str = "change-me"

    # DeepSeek（模型名可在 .env 配任意值：ECHO_DEEPSEEK_MODEL）
    deepseek_api_key: str = ""
    deepseek_base_url: str = "https://api.deepseek.com"
    deepseek_model: str = "deepseek-chat"

    # Kimi / Moonshot（R-023；模型名可配任意值：ECHO_KIMI_MODEL）
    kimi_api_key: str = ""
    kimi_base_url: str = "https://api.moonshot.cn/v1"
    kimi_model: str = "kimi-k2-0711-preview"

    # 生成策略（R-023）：deepseek | kimi | random | alternate（也可在页面切换）
    generation_model: str = "deepseek"
    debate_rounds: int = 5

    # ASR（R-108）：asr_mode = mock（开发/测试假转写）| aliyun | siliconflow
    asr_mode: str = "mock"  # mock | aliyun | siliconflow（.env 配置用哪家，重启生效）
    asr_poll_interval: int = 15  # 阿里云 FileTrans 结果轮询间隔（秒）
    asr_poll_timeout: int = 3600  # 转写最长等待（秒），超时任务标记失败可重试

    # 阿里云 ASR（asr_mode=aliyun 时使用）
    aliyun_asr_access_key_id: str = ""
    aliyun_asr_access_key_secret: str = ""
    aliyun_asr_app_key: str = ""
    aliyun_asr_region: str = "cn-shanghai"  # FileTrans 服务地域（域名前缀，如 cn-shanghai）
    # 阿里云 OSS（R-032：FileTrans 要求公网 URL，视频临时上传 OSS 再删除）
    aliyun_oss_bucket: str = ""
    aliyun_oss_region: str = "oss-cn-shanghai"  # 形如 oss-cn-shanghai
    aliyun_oss_url_expire: int = 7 * 24 * 3600  # 预签名 URL 有效期（覆盖最长排队，秒）

    # 硅基流动 ASR（R-108，asr_mode=siliconflow 时使用）：POST /v1/audio/transcriptions
    siliconflow_api_key: str = ""
    siliconflow_base_url: str = "https://api.siliconflow.cn/v1"
    siliconflow_asr_model: str = "Qwen/Qwen3-ASR-1.7B"  # 可在 .env 覆盖（ECHO_SILICONFLOW_ASR_MODEL）

    # QQ 邮箱 SMTP
    smtp_host: str = "smtp.qq.com"
    smtp_port: int = 465
    smtp_user: str = ""
    smtp_auth_code: str = ""
    mail_to: str = ""

    # 每日流水线
    daily_push_time: str = "07:00"
    tz: str = "Asia/Shanghai"
    pipeline_topics_count: int = 3
    web_base_url: str = "http://localhost:8000"  # 邮件内"去工作台"链接前缀

    # 热点源
    hot_source_mode: str = "mock"  # mock | real
    timezone: str = "Asia/Shanghai"  # 应用统一时区（通知/任务/各类时间戳），可用 ECHO_TIMEZONE 覆盖

    # 平台数据同步（M13，R-027/R-029）：TikHub 第三方聚合
    tikhub_api_key: str = ""
    tikhub_base_url: str = "https://api.tikhub.io/api/v1"
    tikhub_mode: str = "mock"  # mock | real（real 需 .env 配 ECHO_TIKHUB_API_KEY）
    tikhub_daily_budget: int = 2000  # 每日请求预算上限（页面可覆盖，存 Kv）
    platform_sync_times: str = "06:00,17:00"  # R-109：每日两轮（主博主+对标统一），逗号分隔，北京时区

    # 路径：未显式配置时由 data_dir 统一派生（env 可用 ECHO_DB_PATH / ECHO_*_DIR 覆盖）
    _UNSET = Path("@unset@")
    data_dir: Path = Path("./data")
    db_path: Path = _UNSET
    inbox_dir: Path = _UNSET
    videos_dir: Path = _UNSET
    covers_dir: Path = _UNSET
    uploads_dir: Path = _UNSET

    @model_validator(mode="after")
    def _resolve_paths(self) -> "Settings":
        base = self.data_dir
        if self.db_path == self._UNSET:
            self.db_path = base / "echo.db"
        if self.inbox_dir == self._UNSET:
            self.inbox_dir = base / "inbox"
        if self.videos_dir == self._UNSET:
            self.videos_dir = base / "videos"
        if self.covers_dir == self._UNSET:
            self.covers_dir = base / "covers"
        if self.uploads_dir == self._UNSET:
            self.uploads_dir = base / "uploads"
        for key, allowed in _MODE_CHOICES.items():
            setattr(self, key, normalize_mode(getattr(self, key), allowed, _MODE_DEFAULTS[key]))
        return self

    @property
    def sqlalchemy_url(self) -> str:
        return f"sqlite:///{self.db_path}"


@lru_cache
def get_settings() -> Settings:
    return Settings()
