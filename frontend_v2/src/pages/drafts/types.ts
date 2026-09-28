// 脚本工作台类型
/** R-173：草稿当前的 AI 长任务状态（讨论/洗稿/回炉/生成），来自 `/api/drafts` 的 `debate` 字段。 */
export interface DebateState {
  state: 'running' | 'failed' | string
  kind: string
  note: string
  actor: string
  phase: string
  round: number | null
  rounds: number | null
  at?: string
  running?: boolean
}

export interface Draft {
  id: number
  video_id?: number | null
  title: string
  cover_text: string
  script: string
  platform_shells?: Record<string, unknown>
  source: string
  original_script: string
  source_ref: {
    source_title?: string
    benchmark_name?: string
    post_id?: number
    video_id?: number
    [k: string]: unknown
  }
  tags: string[]
  status: 'draft' | 'used' | 'done' | 'archived'
  prompt_version: number
  persona_version: number
  quality: {
    fallback?: boolean
    rounds?: number
    rounds_done?: number
    mock?: boolean
    gen_model?: string
    referee_model?: string
    [k: string]: unknown
  }
  version: number
  /** R-173：无任务时为 null/undefined */
  debate?: DebateState | null
  created_at: string
  updated_at: string
}

export interface DraftVersion {
  id: number
  draft_id: number
  source: string
  title: string
  cover_text: string
  script: string
  tags: string[]
  note?: string
  created_at: string
}

export interface Discussion {
  id: number
  actor: string
  kind: string
  round: number
  content: string
  created_at?: string
  /** R-178：实际出结果的模型（历史留痕为空 → 显示「未记录模型（历史）」） */
  used_slot?: string
  vendor?: string
  model_id?: string
  model_label?: string
}

/** R-178：留痕里「谁说的」——按 kind 判角色（critique=评审方，draft/revise=生成方） */
export function discussRoleLabel(m: Discussion): string {
  if (m.kind === 'critique') return '评审方'
  if (m.kind === 'draft' || m.kind === 'revise') return '生成方'
  if (m.actor === 'system') return '系统'
  return m.actor || '系统'
}

export const UNKNOWN_MODEL = '未记录模型（历史）'

/** R-178：这条留痕实际用的模型文案；老数据没记录过就诚实标注，不按当前配置反推 */
export function discussModelLabel(m: Discussion): string {
  return (m.model_label || '').trim() || UNKNOWN_MODEL
}

/** R-178：某次讨论的配置（`kind='run'` 运行头里的 JSON） */
export interface DiscussionRun {
  id: number
  gen: string
  critic: string
  rounds: number | null
  rounds_done: number | null
  degraded: boolean | null
  created_at?: string
}

export function isRunRow(m: Discussion): boolean {
  return m.kind === 'run'
}

/** 解析运行头；坏 JSON 不炸，退化成「未知」。 */
export function parseRun(m: Discussion): DiscussionRun {
  let raw: Record<string, unknown> = {}
  try {
    raw = JSON.parse(m.content || '{}') as Record<string, unknown>
  } catch {
    raw = {}
  }
  const label = (v: unknown) => {
    const o = (v || {}) as Record<string, unknown>
    return String(o.label || o.model || '') || UNKNOWN_MODEL
  }
  const num = (v: unknown) => (typeof v === 'number' ? v : null)
  return {
    id: m.id,
    gen: label(raw.gen),
    critic: label(raw.critic),
    rounds: num(raw.rounds),
    rounds_done: num(raw.rounds_done),
    degraded: typeof raw.degraded === 'boolean' ? raw.degraded : null,
    created_at: m.created_at
  }
}

/** 本次讨论（最近一次运行头）；没有运行头（老数据）返回 null。 */
export function latestRun(discussions: Discussion[]): DiscussionRun | null {
  for (let i = discussions.length - 1; i >= 0; i--) {
    if (isRunRow(discussions[i])) return parseRun(discussions[i])
  }
  return null
}

/** R-178：讨论留痕的模型表述：优先最近一次运行头（本次讨论），否则回退 quality（老数据可能为空）。 */
export function discussionModelInfo(discussions: Discussion[], d?: Draft | null): string {
  const run = latestRun(discussions)
  if (run) {
    const same = run.gen === run.critic
    return same ? run.gen : `生成方 ${run.gen} × 评审方 ${run.critic}`
  }
  return d ? modelInfo(d) : ''
}

export const DIM_DEFS = [
  { key: 'hook_score', label: '钩子' },
  { key: 'pace_score', label: '节奏' },
  { key: 'ending_score', label: '结尾' },
  { key: 'style_score', label: '像我' }
] as const

export const DIM_OPTS = [
  { v: 5, label: '好' },
  { v: 3, label: '中' },
  { v: 1, label: '差' }
] as const

const SOURCE_LABEL: Record<string, string> = {
  manual: '手动',
  daily: '每日',
  hot: '热点',
  rewrite: '洗稿',
  benchmark: '对标',
  feedback: '回炉'
}

export function srcLabel(d: Draft): string {
  return SOURCE_LABEL[d.source] || d.source || '手动'
}

export function srcTitle(d: Draft): string {
  return d.source_ref?.source_title || ''
}

/** R-178：本篇生成模型——`quality.models/used` 才是后端真正写入的字段（`gen_model/referee_model` 从未写过，是死代码）。 */
export function modelInfo(d: Draft): string {
  const q = (d.quality || {}) as Record<string, unknown>
  const used = (q.used || {}) as Record<string, unknown>
  const models = (q.models || {}) as Record<string, unknown>
  const fmt = (v: unknown) => {
    // 后端口径：`model1(deepseek/deepseek-flash)` → `deepseek-flash`（前端只认得模型 ID 部分）
    const s = String(v || '')
    const m = /\(([^)]*)\)/.exec(s)
    return m ? m[1].split('/').pop() || '' : s
  }
  const gen = fmt(used.gen || models.gen)
  const critic = fmt(used.critic || models.critic)
  if (!gen && !critic) return ''
  return critic && critic !== gen ? `${gen} × ${critic}` : gen
}

export const VERSION_SOURCE: Record<string, { label: string; variant: 'default' | 'secondary' | 'success' | 'warning' }> = {
  manual: { label: '手动定稿', variant: 'default' },
  ai_generate: { label: 'AI 生成', variant: 'secondary' },
  ai_discuss: { label: 'AI 讨论', variant: 'secondary' },
  rewrite_before: { label: '洗稿前 ASR', variant: 'secondary' },
  rewrite_after: { label: '修改后', variant: 'success' },
  rework: { label: '回炉', variant: 'warning' }
}

/** R-173：草稿 AI 长任务的类型名（卡片/讨论 tab 状态条） */
export const AI_KIND_LABELS: Record<string, string> = {
  debate: '双模型讨论',
  discuss: '双模型讨论',
  rewrite: '洗稿讨论',
  rework: '回炉重写',
  generate: 'AI 生成'
}

export function aiKindLabel(kind?: string): string {
  return AI_KIND_LABELS[kind || ''] || 'AI 处理'
}
