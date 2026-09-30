# R-221 测试环境禁止真实发信（垃圾邮件根因）

> 📌 2026-09-30：线上 bug 直报，已定位根因并直接修复（AGENTS「线上明显的 bug 修复可在说明根因后直接修复并登记」）。
> 业务代码零改动，只改测试隔离 + 补回归。

- **日期**: 2026-09-30
- **状态**: 已完成（2026-09-30）
- **关联**: R-208（今日最佳推送）、R-140/R-141（邮件次要通道与配置校验）、verify.sh（每次跑 pytest）

## 原文（作者原话，未改动）
> 服务一直在发垃圾邮件，这是bug吧，下面是邮件内容
> echo · 今日选题与脚本
> 1. 选题B
> 平台：douyin · 匹配度：60 · 【今日最佳 · 热榜】理由
>
> 封面字：（无）
>
> B 的口播稿正文

## 排查结论
**不是服务在发，是 pytest 在发——测试夹具稿被当「今日最佳」真发到了作者邮箱。**

1. 邮件正文与 `backend/tests/test_r208_daily_best.py` 的夹具**逐字一致**（`选题B` / `douyin` / `60` / `hot`→`热榜` / `reason="理由"` / `B 的口播稿正文` / `cover_text=""`→`（无）`）。用假 SMTP 捕获该用例实际发出的报文，解码后正文与作者收到的一模一样（主题 `【echo】今日最佳（2026-09-30）：选题B`，收件人 = `ECHO_MAIL_TO`）。
2. 原用例调用 `pl.push_daily_best(db, today_key())`，内部走到 `notify.send_daily_best` → `_send`；`tests/conftest.py` 只隔离了数据目录与 API Key，**没有隔离 SMTP**，而 `app/config.py` 的 `env_file=(".env", "../.env")` 让 pytest（CWD=`backend`）读到了仓库根 `.env` 里的真实 QQ 邮箱配置 → 真的 login + sendmail。
3. 频率 = 跑测试的频率：`scripts/verify.sh` 每跑一次（pytest 全套）就多一封；`daily_best` 同一天只推一次的 Kv 标记只挡住了同一次运行里的第二次调用。
4. 反证：真实库 `pipeline_runs` 只有 1 条（2026-09-12 failed），`notifications` 里从未有 `daily_best`，`app_kv` 无 `daily_best_pushed:*` —— **运行中的服务从未触发过这条推送**，发件方只可能是测试。

## 方案
1. `tests/conftest.py`：导入 app 前显式清空 `ECHO_SMTP_USER` / `ECHO_SMTP_AUTH_CODE` / `ECHO_MAIL_TO`（环境变量优先级高于 `.env`）→ `mail_config_problem()` 必然返回「未配置」，默认配置下任何用例都发不出信（fail-closed）。
2. 兜底闸门（autouse fixture）：给 `notify.smtplib.SMTP_SSL` 装 tripwire，抛 `RealMailAttempted(BaseException)`——故意不继承 `Exception`，`_send` 的 `except Exception` 吞不掉，谁偷偷补回配置真发信就当场炸穿用例。
3. `test_r208_daily_best.py`：发信改 spy（`monkeypatch pl.send_daily_best`），断言推送内容（标题/正文/理由/封面字），不再依赖环境里的真实 SMTP。
4. 新增 `tests/test_r221_mail_isolation.py` 锁死：默认配置下 `_send` 返回 False；配置合法时被闸门拦下；R-208 夹具在测试环境只写站内通知、邮件通道空操作。

## 明确不做
- 不动 `notify.py` / 流水线的业务语义（邮件仍是次要通道、失败不影响流水线）——这是测试隔离问题，不是发信逻辑问题。
- 不动 `send_daily_digest` 的「force 重跑会再发一封」语义（当前 UI 不传 `force`；若要改属新需求）。

## 验收
- [x] 复现：假 SMTP 捕获到原用例真实外发报文，内容与作者收到的一致（修复前）
- [x] 修复后全套 pytest 零外发（假 SMTP/闸门无一被触发）
- [x] `scripts/verify.sh` 全绿
- [x] 业务代码零改动，服务（8000）保持运行
