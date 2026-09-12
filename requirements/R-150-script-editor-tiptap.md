# R-150 口播脚本编辑区换成 Tiptap 块编辑器（嵌入开源组件，保持 Markdown 存储）

- **日期**: 2026-09-12
- **状态**: 已确认范围，待作者说「继续」后实施（M139）
- **关联**: `DraftsView.vue`（口播脚本编辑区）、`api.js` 的 `uploadImage`、R-018（Markdown 编辑器）、R-024

## 原文（作者原话，未改动）

> 现在有类似于notion、飞书那种开源在线文档澳门

> 有那种类似于notion开源组件吗，嵌入进我这个系统，我现在这个富文本使用不方便

（第一条为发送截断/误触，作者随后重发为第二条完整表述；两条均按原文留档。）

## 背景：现状是什么

「口播脚本」当前**不是真正的富文本编辑器**，是手搓的 Markdown textarea：

- `frontend/src/views/DraftsView.vue` 用 `<n-input type="textarea">` 绑定 `editing.script`；
- 工具栏是自研的 `wrap()` / `linePrefix()` / `insertHr()` / `insertLink()` / `onImage()`，直接操作 `textareaEl.selectionStart` 拼字符串；
- 预览用 `markdown-it`；草稿列表/详情也是渲染同一份 Markdown；
- 后端 **`drafts.script` 就是 Markdown**：AI 生成、回炉重写、原文/洗稿 diff（R-117）全部以 Markdown 为契约。

**结论：任何替换方案都必须能无损往返 Markdown，否则 AI 链路 + diff + 历史稿全部要重做。**

## 反问与确认结论（2026-09-12）

| # | 问题 | 作者选择 |
|---|---|---|
| 1 | 选型走哪条路？ | **Tiptap v3**（块编辑 + 官方 Markdown 往返，后续可加「选中文字 → AI 改写」） |
| 2 | 这次替换范围到哪？ | **只换「口播脚本」编辑区**（DraftsView 编辑页） |
| 3 | 存储格式怎么定？ | **保持 Markdown**，`drafts.script` 不动，后端零改动 |

其余反问项（按 WORKFLOW 清单）确认结论：

- **非目标**：不改后端接口、不改表结构、不动 AI 生成/讨论链路；不做多人协作/评论/块级引用（当前无需求）；不替换素材文案、转写文本、提示词等其它多行输入框。
- **数据**：不新增数据字段；历史稿件无需迁移。
- **异常/边界**：空稿件、只有 `---` 分隔线、HTML 片段、图片、超长稿（AI 稿可达数千字）都要能打开保存不丢内容。
- **成本**：纯前端依赖，无 API 成本增加；打包体积增加由懒加载兜底。
- **依赖与风险**：新增 npm 依赖 3～5 个（MIT），无外部服务依赖，离线可用。

## 技术方案（Tiptap v3）

1. **依赖**（全部 MIT）：
   - `@tiptap/vue-3`（官方 Vue 3 绑定，peer `vue ^3.0.0`）
   - `@tiptap/starter-kit`（标题/粗斜体/列表/引用/代码块/分隔线等基础块）
   - `@tiptap/markdown`（官方 Markdown 解析与序列化 —— 保住 `drafts.script` 契约的关键）
   - `@tiptap/extension-image`、`@tiptap/extension-placeholder`
   > 具体扩展集以实施时安装版本的实际导出为准（StarterKit 在不同小版本含括的扩展有差异），缺什么补什么，不引整套 UI 包。
2. **新增 `frontend/src/components/ScriptEditor.vue`**：
   - `v-model` 绑定 **Markdown 字符串**（`props.modelValue` ↔ `emit('update:modelValue')`），对上层与现在的 textarea 行为一致；
   - `useEditor({ content: markdown, contentType: 'markdown', onUpdate: () => emit(getMarkdown()) })`；
   - 图片：复用 `api.js` 的 `uploadImage()`，工具栏「插 图」/粘贴/拖拽三条入口都插 image 节点（存 URL，不存 base64）；
   - 工具栏沿用 Naive UI `n-button` 与现有视觉风格（不引入 Tiptap 自带 UI 包）。
3. **`DraftsView.vue` 改造**：
   - 用 `defineAsyncComponent(() => import('../components/ScriptEditor.vue'))` **懒加载**，不进首屏；
   - 删除手搓的 `textarea()` / `wrap()` / `linePrefix()` / `insertHr()` / `insertLink()` / `onImage()`；
   - 保留「预览」开关（继续用 `markdown-it`，与列表页渲染保持同一套渲染器，避免两套渲染结果不一致）。
4. **不做**：不加协作（Yjs）、不加斜杠命令/拖拽块（先不做，需要时另立需求）、不换 JSON 文档模型。

## 影响与风险

| 风险 | 对策 |
|---|---|
| Markdown 往返丢格式（标题层级、列表、引用、分隔线、图片、表格） | 实施后抽查 ≥5 篇历史 AI 稿：打开 → 保存 → 比对字段差异；发现不支持的语法就补扩展 |
| 已有宽松 HTML / 特殊语法被规范化 | 同上回归；必要时对 `---`、HTML 片段单独验证 |
| 打包体积变大（ProseMirror 系约 300KB+） | 组件异步加载，首屏体积实测无显著变化 |
| 编辑器渲染与 `markdown-it` 预览不一致 | 二者以 Markdown 为唯一事实源；验收时逐条比对常见语法 |
| 前后端契约被误改 | 方案明确后端零改动；`drafts.script` 仍为 Markdown |

## 验收标准

1. 打开草稿编辑页，「口播脚本」是可块编辑的富文本区：标题、粗体、斜体、列表、引用、代码块、分隔线、链接、图片均可操作，插图走现有 `/api/upload/image`；
2. **保存后 `drafts.script` 仍是 Markdown**，且抽查 ≥5 篇历史 AI 稿「打开 → 保存」后语义不丢（比对前后 Markdown 差异）；
3. 「预览」与编辑器对同一份 Markdown 的呈现一致；
4. 首屏体积无显著增加（编辑器为异步 chunk）；
5. `scripts/verify.sh` 全绿（ruff / eslint / 前端构建 / pytest）+ 前端关键交互点检；
6. 后端与数据库无改动（`git diff` 里不含 `backend/` 业务代码）。

## 排期

- **M139**（待作者确认后实施）
- commit 信息：`feat(R-150): 口播脚本编辑区换 Tiptap 块编辑器（保持 Markdown 存储）`
