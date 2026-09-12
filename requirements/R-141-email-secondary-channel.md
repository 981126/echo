# R-141 邮件是次要通道：配置校验 + 发信失败不炸穿流水线

- **日期**: 2026-09-12
- **状态**: ✅ 已完成（2026-09-12，M130）
- **关联**: R-019（通知/邮件）、R-030（每日选题邮件）、R-133（流水线终态与告警）、R-140（端到端验证中发现）、`services/notify.py`、`services/pipeline.py`、`api/pipeline.py`

## 发现经过（R-140 端到端验证中暴露）
由作者要求「手动触发一次每日流水线做端到端验证」触发。流水线**成功生成 3 条候选 + 3 篇脚本并落库**，
但在最后一步发每日邮件时抛 `UnicodeEncodeError`，导致整轮被置 `failed`、`generated_count=0` ——
已生成好的稿子被连带判为失败，且失败告警邮件也用同一路径再次失败（没有任何告警送达）。

## 根因（已复现，两层）
1. **配置层（作者需自行修）**：`.env` 里 `ECHO_SMTP_AUTH_CODE=授权码（非登录密码）`、`ECHO_MAIL_TO=接收邮箱`
   是把 `.env.example` 的**说明文字当值**留着了（值 100% 非 ASCII）。
   `smtplib` 在 `server.login()` 里做 `initial_response.encode('ascii')` 时炸在位置 17-26
   （= `\x00`+user+`\x00` 之后紧接的授权码前 10 个字符）。
   另有 `ECHO_WEB_BASE_URL=http://localhost:8000# 邮件内"去工作台"链接前缀，部署后…`——
   行尾注释被整串吃进值里（AGENTS.md 早已写明「行尾注释必须换行书写」），邮件里的跳转链接也是坏的。
2. **代码层**：`_send` 只判断「三个值非空」就当配置可用 → 占位符一路走到 `login()` 才炸；
   而且它在流水线的 `try` 里，异常直接让整轮 `run.status=failed`。

## 范围
1. `notify.mail_config_problem(settings)`：提前校验缺失 / 非 ASCII（占位符）/ 非法邮箱，返回可读原因。
2. `_send`：配置非法或发送异常都**记日志 + 返回 False**，不再向上抛；中文主题用 RFC2047（`Header(...).encode()`）编码，
   正文改用 `msg.as_bytes()`（避免 `sendmail(str)` 的 ASCII 编码路径）。
3. 流水线把邮件当**次要通道**：稿子生成成功即 `status=done` + `generated_count` 保留，
   邮件问题写入 `run.error`，并带进完成通知（`api/pipeline.py::_pipeline_task` 返回 message），
   站内通知能看到「已生成 N 篇脚本；注意：邮件未发送：<原因>」。
4. 测试：配置校验（缺失/占位符/非法邮箱）、`_send` 不抛且不连 SMTP、中文主题编码、邮件失败时流水线仍 done。

## 不包含
- 不改 `.env`（含密钥，且正确值只有作者知道）；只在交付说明里点出三处问题与修法。
- 不做邮件重试/队列（单用户每日一封，失败可见即可）。
- 不改 `core/digest.py` 的邮件模板样式。

## 验收标准
1. 占位符配置下 `send_daily_digest` 返回 False 且有可读日志，不抛异常；
2. 邮件失败时流水线 `status=done`、`generated_count` 正确、`run.error` 说明邮件原因，完成通知里能看到；
3. 中文主题经 RFC2047 编码，`msg.as_bytes()` 可用；
4. `scripts/verify.sh` 全绿。
