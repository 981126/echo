# R-101-ACCOUNT-ENABLE-DISABLE: 账号启用/禁用开关（禁停自动同步，素材/对标隐藏）

- **日期**: 2026-09-06
- **提出渠道**: 对话
- **原文摘要**: 博主管理账号管理里每个账户加启用/禁用按钮；禁用后不再自动同步，素材库、博主对标等不再展示该账号数据。
- **状态**: ✅ 已完成
- **排期**: M83（已完成）
- **关联**: CreatorAccountRow/CreatorsView、creators API（/enabled）、works_service.list_works、benchmark.candidates、platform_sync（enabled 已跳过）

## 处理
1. 账号行加「启用/禁用」开关（禁用时整行变灰）。
2. 后端 POST /api/creators/accounts/{id}/enabled 设置 enabled。
3. 语义：
   - 自动同步本就只同步 enabled 账号（run_sync 过滤 enabled，sync_account 里 disabled 直接跳过）；
   - 素材库云端作品列表（list_works）只取 enabled 账号数据；
   - 博主对标候选只取 enabled 账号数据；
   - 手动点同步仍可用于单独恢复前验证（可手动执行）。
4. 自测：verify.sh 全绿。

## 原文（作者原话，未改动）
> 博主管理 1.账号管理里面每个账户 添加一个启用禁用按钮，如果禁用了，不再自动同步，并且素材库，博主对标等等功能就不会再展示、或者对标这个账号些数据

## 修复记录（M84）
- R-101 首发后端漏实现 POST /api/creators/accounts/{id}/enabled（只有前端开关），页面点击启用/禁用报 Method Not Allowed。
- 已补后端接口（设置 enabled 幂等、404 保护）+ 回归测试 tests/test_creators_accounts.py；docs/API.md 同步。

