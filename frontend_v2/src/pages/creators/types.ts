// 博主管理数据类型
export interface DouyinCredential {
  account_id: number
  enabled: boolean
  has_cookie: boolean
  status: 'missing' | 'valid' | 'invalid' | 'disabled'
  status_label: string
  last_validated_at?: string | null
  last_success_at?: string | null
  last_error: string
}

export interface AccountMeta {
  id: number
  creator_id: number
  platform: string
  nickname: string
  home_link: string
  platform_user_id: string
  avatar?: string | null
  avatar_url?: string
  enabled: boolean
  sync_frequency: string
  followers: number
  likes_total: number
  posts_total: number
  last_sync_at?: string | null
  sync_status: string
  sync_message: string
  extra_config?: Record<string, unknown>
  douyin_credential?: DouyinCredential | null
}

export interface CreatorMeta {
  id: number
  kind: 'owner' | 'benchmark'
  parent_id?: number | null
  name: string
  note: string
  is_current: boolean
  avatar?: string | null
  followers_total: number
  accounts: AccountMeta[]
  account_count: number
  created_at?: string
}

export interface SyncJob {
  id: number
  job_type: string
  scope: string
  status: string
  message: string
  creator_id?: number | null
  account_id?: number | null
  progress_done: number
  progress_total: number
  progress_note: string
  started_at?: string | null
  finished_at?: string | null
}

// R-219：sync-all 跳过的博主（结构化，前端按博主展示跳过提示条）
export interface SyncSkipped {
  creator_id: number
  name: string
  reason: string
}

export interface PlatformPostItem {
  id: number
  account_id: number
  creator_id?: number | null
  creator_name?: string
  creator_kind?: string
  platform: string
  title: string
  cover?: string
  publish_time?: string | null
  page_url?: string
  local_video_id?: number | null
  latest_stat?: {
    plays?: number | null
    likes?: number | null
    favorites?: number | null
    shares?: number | null
    comments?: number | null
  } | null
}
