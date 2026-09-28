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

export function modelInfo(d: Draft): string {
  const q = d.quality || {}
  const gen = (q.gen_model as string) || ''
  const ref = (q.referee_model as string) || ''
  if (!gen && !ref) return ''
  return ref && ref !== gen ? `${gen} × ${ref}` : gen
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
