# R-071-DOCS-REWRITE: 全量重写项目文档（以代码为准、真实详细）

- **日期**: 2026-09-06
- **提出渠道**: 对话
- **原文摘要**: 帮忙重写项目各个文档；现文档不详细甚至有些是错的；按代码逻辑写出真实详细文档，不要省 token。
- **状态**: ✅ 已完成
- **排期**: M53（已完成）
- **关联**: docs/*、README.md、AGENTS.md、requirements/README.md

## 处理结论（2026-09-06）
1. **自动生成（保证准确）**：
   - `docs/API.md`：由 FastAPI OpenAPI 重新生成（92 个路由，含方法/路径/标签/参数/请求体/返回）
   - `docs/DATABASE.md`：由 SQLAlchemy 模型元数据重新生成（26 张表：字段/类型/主键/可空/默认/索引/唯一/外键/关系）+ 人工注释
2. **按代码重写（修正过期/错误）**：
   - AGENTS.md / README.md：入口与导航，加入模式配置护栏、自动生成文档说明
   - docs/ARCHITECTURE.md：进程/定时任务（以 scheduler.py 为准）、目录分层、外部服务、数据目录（echo_resource 非 data/）
   - docs/milestones.md：M0–M52 完整进度 + 待排期
   - docs/DECISIONS.md：去重/整理 D-001~D-037（含 D-018+/D-031 演进标注，历史引用号不变）
   - docs/QUICKSTART.md / docs/GLOSSARY.md / docs/FAQ.md
3. 修正事实：数据目录（.env→echo_resource）、真实模式现状、top20、评论 Top50、进度条、定时任务时间表、测试数（53）等
4. 自测：verify.sh 全绿（文档完整性检查通过）

## 原文（作者原话，未改动）
> 帮忙重写现在项目中的各个文档，现在文档不详细，甚至有些是错的，确保按照代码逻辑写出真实详细的文档，不要省token
