"""应用配置：全部来自环境变量（.env），前缀 ECHO_。"""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path

from pydantic import model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


_MODE_CHOICES = {
    "tikhub_mode": {"mock", "real"},
    "hot_source_mode": {"mock", "real"},
    "asr_mode": {"mock", "aliyun", "siliconflow", "tencent"},  # R-108/R-200：ASR 服务商可切硅基流动/腾讯云
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
    deepseek_model: str = "deepseek-flash"  # R-137：DeepSeek-V4.1-Flash 官方 ID

    # Kimi / Moonshot（R-023；模型名可配任意值：ECHO_KIMI_MODEL）
    kimi_api_key: str = ""
    kimi_base_url: str = "https://api.moonshot.cn/v1"
    kimi_model: str = "kimi-k2-0711-preview"

    # 旧生成策略（R-023）。R-138 起改用「AI 设置 → 模型设置」的 gen_role/referee_role，
    # 这里只作为旧值迁移来源与 .env 兜底（random/alternate 已下线）。
    generation_model: str = "deepseek"
    debate_rounds: int = 5
    # 单次 LLM 调用的硬性墙钟上限（秒）：超过即按超时处理 → 由 llm_router 降级到模型2（R-139）
    llm_timeout_seconds: int = 600  # R-240：同时作为各 feature 单次预算的硬上限（min），调低会全局收紧

    # AI 对话 agent 行为（R-147 P0）：回合数 / 单次提问的工具调用总次数 / 墙钟上限（秒）
    # 到限不再抛「未收敛」，而是带着已获得的数据收尾作答。
    agent_max_rounds: int = 8
    agent_max_tool_calls: int = 16
    agent_timeout_seconds: int = 120

    # 灵感池进池限量（R-140）：每条作品最多进池 N 条（按点赞降序）、每个博主每天最多进池 N 条。
    # 设为 0 表示该维度不限量。daily 走「逐素材队列」后评论量大，必须限量避免灌进几百上千条。
    pool_ideas_per_post: int = 8
    pool_ideas_per_day: int = 40

    # ASR（R-108）：asr_mode = mock（开发/测试假转写）| aliyun | siliconflow | tencent
    asr_mode: str = "mock"  # mock | aliyun | siliconflow | tencent（.env 配置用哪家，重启生效；界面可覆盖）
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
    siliconflow_asr_model: str = "Qwen/Qwen3-ASR-1.7B"  # 免费 ASR 模型（官方定价页标注免费）；可在 .env 覆盖（ECHO_SILICONFLOW_ASR_MODEL）

    # 腾讯云 ASR（R-200，asr_mode=tencent 时使用）：录音文件识别 CreateRecTask/DescribeTaskStatus
    # 音频本地 base64 直传（SourceType=1），单文件 ≤5MB；引擎可在界面切换，默认大模型2.0
    tencent_asr_secret_id: str = ""
    tencent_asr_secret_key: str = ""
    tencent_asr_region: str = "ap-guangzhou"  # 腾讯云地域（HTTP 接口 domain 与地域无关，SDK 仍需一个地域）
    tencent_asr_endpoint: str = "asr.tencentcloudapi.com"
    tencent_asr_engine_model: str = "16k_zh_en_2.0"  # 默认引擎（大模型2.0）；界面可覆盖
    tencent_asr_max_audio_mb: int = 5  # 本地音频直传上限（腾讯限制 5MB）

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
    douyin_cookie_key: str = ""  # R-237：Cookie 密文密钥；Cookie 本身只经页面加密入库
    # R-163/R-222 同步并发：全局 TikHub 令牌桶（所有接口合计 ≤ rate req/s）+ 消费者池大小
    tikhub_rate_limit: float = 10.0  # 全局请求速率上限（req/s），ECHO_TIKHUB_RATE_LIMIT
    tikhub_rate_burst: int = 10  # 令牌桶容量（允许的瞬时突发），ECHO_TIKHUB_RATE_BURST
    sync_concurrency: int = 4  # 博主级并发消费者数，ECHO_SYNC_CONCURRENCY
    sync_account_concurrency: int = 3  # 单个博主内账号并发数，ECHO_SYNC_ACCOUNT_CONCURRENCY（R-222）
    sync_post_concurrency: int = 5  # 单账号内作品/评论/B站补全并发数，ECHO_SYNC_POST_CONCURRENCY（R-222）
    sync_download_concurrency: int = 4  # 视频下载并发数（ffmpeg 保持独立限制），ECHO_SYNC_DOWNLOAD_CONCURRENCY（R-222）
    sync_media_concurrency: int = 6  # R-240：进程级全局媒体并发数（下载/转写较重，独立池），ECHO_SYNC_MEDIA_CONCURRENCY
    sync_commit_batch_size: int = 20  # 批量写库提交阈值，ECHO_SYNC_COMMIT_BATCH_SIZE（R-222）
    sync_progress_debounce_seconds: float = 2.0  # 同步进度更新防抖秒数，ECHO_SYNC_PROGRESS_DEBOUNCE_SECONDS（R-222）

    # R-240 性能优化可调项（批次 1+2）
    prompt_eval_concurrency: int = 3  # 金样本评测并发 LLM 数（1~5），ECHO_PROMPT_EVAL_CONCURRENCY
    pipeline_generate_concurrency: int = 2  # 每日流水线并发生成草稿数（1~3），ECHO_PIPELINE_GENERATE_CONCURRENCY
    prompt_selfcheck_concurrency: int = 2  # 提示词启用后自测并发生成数（1~3），ECHO_PROMPT_SELFCHECK_CONCURRENCY
    asr_max_attempts: int = 3  # 自动转写最大尝试次数，超过跳过并通知；ECHO_ASR_MAX_ATTEMPTS

    # 联网搜索（R-227）：火山引擎豆包搜索（融合信息搜索），为生成/洗稿补充真实事实/数据。
    # 未配 key 时联网能力静默关闭（不影响生成）；结果缓存 + 单次请求超时。
    web_search_api_key: str = ""
    web_search_base_url: str = "https://open.feedcoopapi.com/search_api/web_search"
    web_search_timeout_seconds: int = 15
    web_search_count: int = 5  # 单次搜索返回条数（web ≤ 50）
    web_search_cache_seconds: int = 3600  # 同 query 结果缓存时长，省额度
    web_search_traffic_tag: str = "skill_web_search_common"  # 渠道标识（豆包搜索要求）

    # 联网参考（R-233）：DeepSeek Search/Fetch + 豆包双源并行 + 正文补齐 + 去营销 + 生成方选文。
    # DeepSeek 复用 deepseek_api_key / deepseek_base_url；未配 key 或关开关时自动只跑豆包。
    online_search_enabled: bool = True  # 联网总开关（测试/临时关闭双源）
    deepseek_search_enabled: bool = True
    deepseek_search_count: int = 5  # 单次搜索条数（1~50）
    online_search_timeout_seconds: int = 20  # 单次搜索请求超时
    online_fetch_enabled: bool = True  # 缺正文时是否调 DeepSeek Fetch 补齐
    online_fetch_max: int = 4  # 单次最多补抓篇数
    online_fetch_timeout_seconds: int = 15  # 单次 Fetch 超时
    online_fetch_chars: int = 2000  # 单篇正文注入上限（按相关度抽段）
    online_min_content_chars: int = 800  # 低于此长度视为「缺正文」，触发 Fetch
    online_budget_seconds: int = 25  # 搜索 + 抓取总预算（超时用已有内容继续）
    online_ref_pick: bool = True  # 是否由生成方模型按人设选文（关=按相关度自动取）
    online_ref_pick_min: int = 2
    online_ref_pick_max: int = 3
    online_pick_timeout_seconds: int = 45  # 选文调用墙钟上限（超时自动兜底，避免拖死整条生成）
    # 营销/内容农场站点（逗号分隔，按 URL 子串匹配）；可留空关闭站点过滤
    online_site_blacklist: str = (
        "k.sina.com.cn,baijiahao.baidu.com,sohu.com/a/,163.com/dy/,qq.com/omn/,"
        "book118.com,docin.com,renrendoc.com,"
        "taobao.com,tmall.com,jd.com,pinduoduo.com,1688.com"
    )

    # 数据库（R-235）：PostgreSQL 连接串，只从 .env 读（ECHO_DATABASE_URL），无默认值——
    # 缺失即启动报错（fail-closed）。例：postgresql+psycopg://user:pass@host:5432/echo_dev
    database_url: str = ""
    # 路径：未显式配置时由 data_dir 统一派生（env 可用 ECHO_*_DIR 覆盖）
    _UNSET = Path("@unset@")
    data_dir: Path = Path("./data")
    inbox_dir: Path = _UNSET
    videos_dir: Path = _UNSET
    covers_dir: Path = _UNSET
    uploads_dir: Path = _UNSET

    @model_validator(mode="after")
    def _resolve_paths(self) -> "Settings":
        if not self.database_url:
            raise ValueError(
                "未配置数据库连接串：请在 .env 设置 ECHO_DATABASE_URL（如 postgresql+psycopg://user:pass@host:5432/echo_dev）"
            )
        base = self.data_dir
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


@lru_cache
def get_settings() -> Settings:
    return Settings()
