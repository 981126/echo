# R-151 素材同步失败修复：TikHub 请求重试 + 单路由限速

- **日期**: 2026-09-14
- **状态**: ✅ 已完成（2026-09-14，M140）
- **关联**: `services/platform/tikhub.py`、`services/media_ensure.py`、`services/platform_sync.py`

## 原文（作者原话，未改动）
> 素材同步失败
> 「关于经济独立我的思考。互联网行业是青春饭 那未来还能领多久现在的工资也是未知，那么就在毕业之前尽情翻滚倒腾吧朋友们，永远」：TikHub 请求失败: [SSL: UNEXPECTED_EOF_WHILE_READING] EOF occurred in violation of protocol (_ssl.c:1082)

## 复现与根因（2026-09-14 实测，非推测）
一次 daily 同步（09:22–09:34，5 个博主账号）注册了 18×5 条 `card_sync`（素材同步）队列任务，
其中 **169 条失败**，错误都是同一句 `TikHub 请求失败: [SSL: UNEXPECTED_EOF_WHILE_READING]`（另有少量 `The read operation timed out`）。
作者收到的通知只是这 169 条里的两条。实测证据：

1. **链路经过本地系统代理**：`httpx._utils.get_environment_proxies()` 在本机返回
   `{'http://': 'http://127.0.0.1:7890', 'https://': 'http://127.0.0.1:7890'}`——
   进程环境变量里**没有**任何 `*_PROXY`，是 **macOS 系统代理设置**被 `urllib.getproxies()` 读到（httpx `trust_env=True` 默认生效）。
   实测完整堆栈落在 `httpcore/_sync/http_proxy.py:316 handle_request → start_tls`，
   即 **CONNECT 隧道建好后、TLS 握手阶段被代理/上游掐断**，正是 `UNEXPECTED_EOF_WHILE_READING` 的典型形态。
   同一时间窗（09:26–09:27）DeepSeek 也出现 `ConnectTimeout` / `RemoteProtocolError`（日志实测），
   说明是**本地代理到外网的瞬时抖动**，不是 TikHub 或 API key 的问题（紧接着的请求与现在的手工探测都 200）。
2. **TikHub 有单路由 1 请求/秒 限速**：并发 40 次请求实测 **35 次 HTTP 429**，429 响应体原文：
   `"Request too fast, the request rate limit for the current route is 1 times/second"`。
   而 daily 同步是 `ThreadPoolExecutor(3)` × 多个账号并行、每条素材又要打评论接口，
   必然超限；被限流时服务端有时回 429、有时**直接掐 TLS 连接**（即上面的 SSL EOF）。
3. **代码放大了故障**：`TikHubClient._get()` 只有一次 `httpx.get(...)`，
   既没有重试、也没有限速、失败也不写日志（只在 `media_ensure.run_card_sync_queue` 里变成通知）。
   于是**一次瞬时抖动 = 一条素材同步失败 + 一条失败通知**（同批 169 条）。

## 范围
1. `TikHubClient._get()` 增加**同路由排队**：进程内按 API path 保证最小间隔
   `_ROUTE_MIN_INTERVAL = 1.2s`（TikHub 限速 1 req/s，留 0.2s 余量），
   线程安全（`threading.Lock` 预留时间片，sleep 在锁外，不影响其它路由）。
2. `TikHubClient._get()` 增加**有界重试**：最多 3 次尝试（首次 + 2 次重试），
   退避 `1.5s → 4.0s`；重试条件 =
   - `httpx.TransportError`（含 SSL EOF / ConnectError / 读写重置 / 超时等瞬时故障）；
   - HTTP `429 / 500 / 502 / 503 / 504`。
   4xx 等**永久错误不重试**，立即抛错（保持原「不浪费额度」口径）。
3. 失败**写日志**（R-133 统一 logger）：重试时 `warning`、最终失败 `error`，含 path 与原因；
   错误消息保持原前缀 `TikHub 请求失败:`，重试后追加「（已重试 2 次）」，通知里直接可读。

## 不包含
- **不改代理设置**（`no_proxy`/系统代理）：是否需要代理访问 TikHub 由作者的网络环境决定，代码不擅自绕过。
- 不改 TikHub 之外的适配器（`topic_mining.TikHubHotSource` 热搜源单平台失败会降级，暂不动）。
- 不改同步并发度 / `ThreadPoolExecutor` 结构（限速已能消除 429；降并发是另一条路，未采纳）。
- 不回补本次失败的 169 条素材（属数据修复动作，作者可在素材卡上「同步数据」重跑；已单独说明）。
- 不改前端、不改接口/表结构（`API.md` / `DATABASE.md` 无变化）。

## 验收标准
- 单测：SSL EOF/连接重置 → 自动重试后成功；429 → 重试后成功；400 → 不重试直接失败；
  重试耗尽 → 抛 `TikHubError` 且尝试次数 = 3；同路由第二次调用会排队（sleep > 0），不同路由不互相阻塞。
- `scripts/verify.sh` 全绿（ruff + mypy + pytest + 前端构建 + 文档一致性）。
- 重启后端后，真实链路冒烟：同一个素材卡「同步数据」成功，且不再出现 429 / SSL EOF 失败通知。

## 后续（不在本需求内，已向作者说明）
- 本次失败的 169 条素材可通过卡片「同步数据」逐条或整篇重跑补回（会消耗 TikHub 额度）。
- 若代理抖动成为常态，可考虑给平台同步固定 `HTTPS_PROXY`/`NO_PROXY` 或换更稳的节点——需作者决策。
