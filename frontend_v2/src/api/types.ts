// 手写业务类型：OpenAPI 未覆盖（SSE）或生成类型过宽（any）处的手工补强

// ---------- SSE 事件（/api/events） ----------
export interface TaskUpdateEvent {
  id: number
  status: 'pending' | 'running' | 'done' | 'failed'
  progress?: number
  note?: string
  error?: string
  payload?: Record<string, unknown>
}

export interface NotificationEvent {
  id: number
  kind: string
  status: string
  title: string
  message: string
  target: string
}

export interface SyncJobEvent {
  id: number
  job_type: string
  scope: string
  creator_id?: number | null
  account_id?: number | null
  post_id?: number | null
  status: string
  progress_done: number
  progress_total: number
  progress_note: string
  message: string
}

export type EchoEvent =
  | { type: 'task.update'; data: TaskUpdateEvent }
  | { type: 'notification.new'; data: NotificationEvent }
  | { type: 'sync.job'; data: SyncJobEvent }
  | { type: string; data: Record<string, unknown> }

// ---------- 业务负载（M-A 使用） ----------
export interface Notification {
  id: number
  kind: string
  status: string
  title: string
  message: string
  target: string
  created_at?: string
  read?: boolean
}

export interface HotTopic {
  id: number
  title: string
  platform?: string
  hot_value?: number | null
  matched?: boolean
  score?: number | null
  url?: string
}

export interface TopicIdea {
  id: number
  title: string
  source: 'hot' | 'comment'
  platform?: string
  likes?: number
  matched?: boolean
  score?: number | null
}

export interface TimelineEvent {
  key: string
  title: string
  fullTitle: string
  date: string
  left: number
  status: string
  coverUrl?: string
  srcLabel?: string
  kind: 'local' | 'cloud'
  id: number
}
