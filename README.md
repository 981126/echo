# echo（回声）— 自媒体复盘纠错平台

让 AI 越来越懂你的人设：每日自动产出匹配选题与脚本，对已发布内容复盘纠错，辅助找到适合的赛道（抖音 / B站 / 小红书）。

## 快速开始
1. 复制 `.env.example` 为 `.env` 并填入配置（DeepSeek / 阿里云 ASR / QQ 邮箱授权码 / 访问令牌）
2. 开发：见 `docs/ARCHITECTURE.md` §7（笔记本跑后端 + 前端）
3. 部署：NAS 上 `docker compose up -d --build`
4. 更新：`scripts/update.sh`

## 文档索引
| 文档 | 内容 |
|---|---|
| `AGENTS.md` | AI 行为手册（任何 agent 打开项目先读它） |
| `docs/PRD.md` | 产品需求 |
| `docs/ARCHITECTURE.md` | 架构总览与运行方式 |
| `docs/WORKFLOW.md` | 标准流程与需求反问清单 |
| `docs/DECISIONS.md` | 关键决策记录 |
| `docs/milestones.md` | 里程碑进度 |
| `requirements/` | 需求归档（R-xxx，事实源） |

## 对 AI 用户的一句话
在这个仓库里提需求 = 说一句话，agent 会先反问、再留档、再排期、你确认后实现。
