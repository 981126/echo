# 术语表（GLOSSARY）

| 术语 | 含义 |
|---|---|
| 本地素材 | 作者上传/导入、有视频文件的素材（videos），可转写并进入人设/风格学习语料 |
| 云端作品 | 从平台（TikHub）同步回来的平台帖子（platform_posts），默认无本地视频，用于复盘/选题/对标 |
| 转本地素材 | 把云端作品生成本地 videos 记录（可后补上传视频），并绑定 platform_posts.local_video_id |
| 合并作品（work） | 同一条视频在抖音/B站/小红书的多条平台帖，按规范化标题自动/手动合并成一张卡；`works` 表 |
| 规范化标题 | 去 #话题/标点/空白/大小写后的标题，用于跨平台合并匹配（works_service.normalize_work_title） |
| 同步 | 从平台拉取作品/指标/评论到本地（幂等 upsert）；范围：前 20 条(daily)/全量(initial)/每周(weekly，对标)/单条 |
| 指标快照 | 平台作品指标按天快照（platform_post_stats）或本地素材按天聚合（metrics_snapshots） |
| 评论 Top50 | 每个平台作品下点赞最高的前 50 条评论，随同步入库并在「评论数据」页按点赞展示（R-067） |
| DataSource | 平台数据源接口（services/platform/base.py）；默认实现 TikHub，可整体/单平台替换（R-062） |
| mock / real | 数据源模式：mock=确定性假数据（仅离线测试），real=真实接口；非法值启动报错（R-068） |
| 预算护栏 | TikHub 每日请求预算（默认 2000），超限停止本轮并通知 |
| 人设档案 | persona_tags：赛道/表达/红线等，版本化，AI 建议需作者确认 |
| 风格画像 | 由全部非广告素材统计出的口癖/句长/语气占比等表达特征（R-020/R-057） |
| 金句库 | 高表现素材里挑出的高光句/口头禅，作者确认后生成时强注入 |
| 禁词 | AI 腔词汇（“首先/总之/值得注意的是…”），生成时注入 avoid 词（R-057） |
| 提示词版本 | ai_prompts 表按 key 管理各功能系统提示词；enabled=生效，candidate=待启用候选 |
| 双模型讨论 | Kimi+DeepSeek 围绕草稿多轮互评修订（draft_discussions 留痕），失败降级单模型 |
| 选题池 / 灵感池 | topic_ideas：各平台热点或评论区内容，人工挑选不自动推送（R-028） |
| 每日流水线 | 每日定时：热点→匹配→生成 ≥3 选题+脚本→入库（幂等，可邮件推送） |
| ABCD 复盘 | A 报表/B 归因/C 建议/D 赛道方向的复盘报告（review_reports） |
| 通知中心 | 右上角铃铛：后台任务完成/失败 + 点击跳转（notifications，R-019） |
| 同步进度条 | 博主页同步时按 sync_jobs.progress_* 实时显示的进度条（R-070） |
| access token | 登录令牌（ECHO_ACCESS_TOKEN），请求头 X-Access-Token |
| kv | app_kv 表：预算计数/迁移标记/节流计数等轻量键值 |
| 需求归档 | requirements/R-xxx.md：需求原文事实源 + 状态机 |
| 幂等迁移 | db.py 中按“列是否存在”判断的轻量 schema 迁移（未用 Alembic） |
| 北京时间 | 系统统一时区（默认 Asia/Shanghai，ECHO_TIMEZONE 可覆盖；R-066） |
