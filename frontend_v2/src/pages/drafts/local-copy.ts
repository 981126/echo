// R-213：草稿的本地「未同步副本」——断网 / 后端不可达时先把改动留在浏览器里，服务器确认落库后再清掉。
// 只保留**一份**（当前还没同步成功的那份）；已同步的内容不缓存。
// 读/写/删都不抛：隐私模式、配额满、手改过 localStorage 都不该影响正常保存。
import type { DraftEditState } from './edit-drawer'

export const LOCAL_COPY_KEY = 'echo_v2_draft_local_copy'

export interface LocalDraftCopy {
  /** 编辑器内容快照 */
  state: DraftEditState
  /** 写入时间（ISO 字符串，UI 显示「HH:MM 保存」） */
  at: string
  /** 这份副本对应的草稿 id（0 = 还没在服务端建过稿） */
  id: number
}

/** 兜底解析：字段缺失/类型不对一律降级成空串，绝不把坏数据灌进编辑器 */
function normalizeState(raw: unknown): DraftEditState | null {
  if (!raw || typeof raw !== 'object') return null
  const s = raw as Record<string, unknown>
  const str = (v: unknown) => (typeof v === 'string' ? v : '')
  const videoId = s.video_id
  return {
    id: Number(s.id) || 0,
    title: str(s.title),
    cover_text: str(s.cover_text),
    script: str(s.script),
    video_id: videoId == null || videoId === '' ? null : Number(videoId) || null,
    tagsText: str(s.tagsText),
    publish_platform: str(s.publish_platform),
    publish_url: str(s.publish_url),
    published_at: str(s.published_at)
  }
}

export function readLocalCopy(): LocalDraftCopy | null {
  try {
    const raw = window.localStorage.getItem(LOCAL_COPY_KEY)
    if (!raw) return null
    const data = JSON.parse(raw) as Record<string, unknown>
    const state = normalizeState(data?.state)
    if (!state) return null
    return { state, at: typeof data.at === 'string' ? data.at : '', id: Number(data.id) || 0 }
  } catch {
    return null
  }
}

export function writeLocalCopy(copy: LocalDraftCopy): void {
  try {
    window.localStorage.setItem(LOCAL_COPY_KEY, JSON.stringify(copy))
  } catch {
    /* 配额满 / 隐私模式：本地兜底失败不该阻断保存主路径 */
  }
}

export function clearLocalCopy(): void {
  try {
    window.localStorage.removeItem(LOCAL_COPY_KEY)
  } catch {
    /* ignore */
  }
}

/** 给 `createAutoSaver` 用的默认本地存储实现（单测里注入假的） */
export const localCopyStorage = {
  write: (state: DraftEditState, id: number) => writeLocalCopy({ state, id, at: new Date().toISOString() }),
  clear: clearLocalCopy
}
