export interface VideoItem {
  post_id: number
  title: string
  cover_url?: string | null
  publish_time?: string | null
  video_url?: string | null
  duration_seconds?: number | null
  /** 作品状态（v30：来自平台作品指标，approved/private/rejected/published/unknown） */
  status?: string | null
  status_label?: string | null
  /** v32：最新统计（视频切换下拉展示用） */
  plays?: number | null
  likes?: number | null
  favorites?: number | null
  shares?: number | null
  latest_review_id?: number | null
  review_status?: string | null
  latest_sync_at?: string | null
  running_task_id?: number | null
}

export interface Metric {
  key: string
  label: string
  unit: string
  value?: number | null
  baseline?: number | null
  percentile?: number | null
  state: string
  sample_count: number
  missing: boolean
}

export type FindingVerdict = 'strength' | 'weak' | 'neutral' | 'unknown' | ''

/** R-248：归因证据结构化（新分析由程序构造；历史数据可能是旧结构，渲染侧做兼容）。 */
export interface FindingMetricEvidence {
  evidence_id?: string
  key?: string
  label?: string
  value?: number | null
  baseline?: number | null
  unit?: string
  state?: string
  sample_count?: number
  time?: string
  drop?: number
}

export interface FindingContentEvidence {
  evidence_id?: string
  text?: string
  source?: string
}

export interface Finding {
  id: number
  dimension: string
  title: string
  judgement_type: 'fact' | 'hypothesis' | 'unknown'
  conclusion: string
  suggestion: string
  target_metric: string
  /** R-248：归因方向（程序按真实指标判定）；历史数据为空串/缺省 */
  verdict?: FindingVerdict
  metric_evidence: FindingMetricEvidence[]
  content_evidence: FindingContentEvidence[]
}

export interface Topic {
  id?: number
  role?: string
  rank?: number
  topic: string
  reason: string
  fit_reason: string
  evidence: Array<Record<string, unknown>>
  outline?: string[]
  opening_line?: string
  target_metric: string
  follow_up_role?: string
  score?: number
  score_detail?: Record<string, unknown>
}

export interface NewTopic {
  topic: string
  reason: string
  fit_reason: string
  first_step: string
  evidence?: Array<Record<string, unknown>>
  target_metric?: string
}

export interface Charts {
  comparison: Metric[]
  retention: { points: Array<{ time_seconds: number; time_label: string; current?: number; similar_author?: number }>; reliable: boolean; plays?: number; has_timed_transcript: boolean }
  traffic: Array<{ name: string; value: number; ratio: number }>
  search_terms: Array<{ term?: string; keyword?: string; value: number }>
  comment_questions: Array<{ group_title: string; commenter_count: number; likes: number; comments?: Array<{ id: number; text: string; likes: number }> }>
  follower_topics: Array<{ topic: string; follower_gain: number; follower_per_1k?: number; sample_count: number }>
  peer_comparisons: Array<{ post_id: number; title: string; plays: number; baseline: number; play_multiple: number; sample_count: number }>
}

export interface MetricAdvice {
  dimension: string
  title: string
  target_metric: string
  gap: string
  judgement_type: 'fact' | 'hypothesis'
  reasons: string[]
  actions: string[]
  copy_refs: string[]
  evidence: string[]
}

export interface Review {
  id: number
  status: string
  error?: string
  post: VideoItem
  data_time: string
  summary: string
  overall_result: string
  comparison: { count: number; post_ids: number[]; sample_note: string }
  metrics: Metric[]
  findings: Finding[]
  advices: MetricAdvice[]
  follower_analysis: { strong_topics: Charts['follower_topics']; homepage: { bio?: string; direction_note?: string; pinned_post_ids?: number[]; needs_author_input?: boolean; message?: string } }
  recommendations: { primary?: Topic | null; backups: Topic[]; follow_ups: Topic[] }
  new_topics: NewTopic[]
  charts: Charts
  warnings: string[]
  model_name?: string
}

export interface FailedReview {
  id: number
  error?: string
  created_at?: string
  task_id?: number | null
}

export interface ReferenceItem {
  id: string
  kind: 'peer' | 'low_fan'
  title: string
  cover_url?: string | null
  author_nickname: string
  author_followers?: number | null
  publish_time?: string | null
  plays?: number | null
  likes?: number | null
  comments?: number | null
  video_url?: string | null
  verdict: string
  verdict_evidence: { baseline_plays?: number; play_multiple?: number; sample_count?: number; source?: string; label?: string }
  relevance: number
}

export interface Credential {
  account_id: number
  enabled?: boolean
  status: 'missing' | 'valid' | 'invalid' | 'disabled' | string
  status_label?: string
  has_cookie: boolean
  last_validated_at?: string | null
  last_success_at?: string | null
  last_error?: string
}
