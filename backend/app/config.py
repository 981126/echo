"""应用配置：全部来自环境变量（.env），前缀 ECHO_。"""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path

from pydantic import model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="ECHO_", env_file=(".env", "../.env"), extra="ignore")

    # 访问令牌（Web 入口校验）
    access_token: str = "change-me"

    # DeepSeek
    deepseek_api_key: str = ""
    deepseek_base_url: str = "https://api.deepseek.com"
    deepseek_model: str = "deepseek-chat"

    # 阿里云 ASR（mode=mock 时无需密钥，用于开发/测试）
    aliyun_asr_access_key_id: str = ""
    aliyun_asr_access_key_secret: str = ""
    aliyun_asr_app_key: str = ""
    asr_mode: str = "mock"  # mock | aliyun

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
        return self

    @property
    def sqlalchemy_url(self) -> str:
        return f"sqlite:///{self.db_path}"


@lru_cache
def get_settings() -> Settings:
    return Settings()
