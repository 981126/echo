// R-212：新建草稿「实时保存」的纯逻辑（不含 React/DOM，便于单测）。
//
// 症状：新建草稿的内容原先只在内存里——点到抽屉外面（遮罩）就把抽屉关了，整篇内容随之丢弃。
// 做法：
//   ① 任何一处变动 → 防抖 900ms 落库（首次 `POST`，之后 `PATCH`）；
//   ② 关抽屉瞬间 `closeOut()` 再补一次，防抖窗口里最后几个字也不丢；
//   ③ **单飞 + 队列**：保存进行中又有改动时排队，当前这次完成后继续写最新内容（不许漏字、不许重复建稿）；
//   ④ 自动建出来的稿若被清空 → 关闭时回调 `onDiscard`，让页面把它删掉（不留「（无标题）」垃圾卡）。
//
// R-213（断网兜底）：改动**先落本地副本**再谈服务器；网络/5xx 失败按退避重试（`online` 时立刻重试），
//   只有服务器确认落库才清副本；4xx 是请求本身有问题，重试没意义，直接报失败。
import type { DraftEditState } from './edit-drawer'
import { localCopyStorage } from './local-copy'

/** 距最后一次改动多久落库（短到几乎无感，长到不会一字一请求） */
export const AUTOSAVE_DELAY = 900

/** 失败重试退避：1s → 2s → 4s … 上限 30s（页面活着就一直试） */
export const RETRY_BASE = 1000
export const RETRY_MAX = 30000

export type AutoSaveStatus = 'idle' | 'dirty' | 'saving' | 'saved' | 'offline' | 'error'

/** `POST/PATCH /api/drafts` 的请求体（与 `ensureSaved()` 同一口径） */
export interface AutoSavePayload {
  title: string
  cover_text: string
  script: string
  video_id: number | null
  tags: string[]
  publish_platform: string
  publish_url: string
  published_at: string | null
}

export function draftBody(s: DraftEditState): AutoSavePayload {
  return {
    title: s.title,
    cover_text: s.cover_text,
    script: s.script,
    video_id: s.video_id,
    tags: s.tagsText.split(/[,，]/).map((x) => x.trim()).filter(Boolean),
    publish_platform: s.publish_platform,
    publish_url: s.publish_url,
    published_at: s.published_at || null
  }
}

/** 全空（与后端 R-154「空白草稿不落库」同一口径）：标题/封面字/正文/标签/关联素材都空才算空 */
export function isBlankDraft(s: DraftEditState): boolean {
  const b = draftBody(s)
  return !b.title.trim() && !b.cover_text.trim() && !b.script.trim() && !b.tags.length && !b.video_id
}

/** 内容指纹（**不含 id**）：同一份内容不重复写库 */
export function draftFingerprint(s: DraftEditState): string {
  return JSON.stringify(draftBody(s))
}

export interface AutoSaveEnv {
  /** 读当前编辑器内容（组件里用 ref，保证回调拿到最新值） */
  read: () => DraftEditState
  create: (body: AutoSavePayload) => Promise<{ id: number }>
  update: (id: number, body: AutoSavePayload) => Promise<void>
  /** 首次自动保存建出了草稿（页面据此记住 id / 刷新列表） */
  onCreate: (id: number) => void
  /** 自动建出的稿被清空 → 请页面逻辑删除它 */
  onDiscard: (id: number) => void
  /** `attempt` 仅离线重试时给（状态位显示「重试 N」） */
  onStatus: (status: AutoSaveStatus, at?: Date, attempt?: number) => void
  /** 防抖时长（测试用，默认 `AUTOSAVE_DELAY`） */
  delay?: number
  /** 本地兜底（R-213）：默认写 localStorage，单测注入假的 */
  storage?: { write: (state: DraftEditState, id: number) => void; clear: () => void }
}

export interface AutoSaver {
  /** 每次打开抽屉（新一轮新建）时调用：清掉上一轮的 id/指纹/队列（组件是常驻挂载的） */
  reset: () => void
  /** 内容变动后调用（可重复调用；同内容/空白未建稿时不排期） */
  schedule: () => void
  /** 立刻按当前内容保存一次（不等防抖）：关抽屉、恢复本地副本时用 */
  flush: () => void
  /** 关抽屉时调用：清定时器 + `flush()`；若「自动建出且已清空」则丢弃 */
  closeOut: () => void
  /** 网络恢复（`online` 事件）时调用：立刻重试还没落库的内容 */
  retryNow: () => void
  /** 手动【保存】/服务端已写（讨论完成回填）后调用：记下已落库内容，避免重复写 */
  markSaved: (s: DraftEditState) => void
  /** 打开草稿时调用：把服务端内容记为「已保存基线」——打开本身不算改动，不写库、不留本地副本 */
  baseline: (s: DraftEditState) => void
  /** 组件卸载：清定时器与队列（在飞的请求与本地副本都保留） */
  dispose: () => void
}

export function createAutoSaver(env: AutoSaveEnv): AutoSaver {
  const delay = env.delay ?? AUTOSAVE_DELAY
  const storage = env.storage ?? localCopyStorage
  let timer: ReturnType<typeof setTimeout> | null = null
  let retryTimer: ReturnType<typeof setTimeout> | null = null
  let attempt = 0 // 连续失败次数（退避用；成功即归零）
  let createdId = 0 // 本次会话自动建出的草稿 id（0 = 还没建）
  let savedFp = '' // 最近一次确认已落库的内容指纹
  let pending: DraftEditState | null = null // 最新一份还没确认落库的内容（断网重试用它，不读已重置的编辑态）
  let queue: DraftEditState | null = null // 待落库内容（后写覆盖先写）
  let pumping = false
  let discardOnCreate = false // 极端：建稿那一次还在飞，作者已清空并关了抽屉

  function clearTimer() {
    if (timer !== null) {
      clearTimeout(timer)
      timer = null
    }
  }

  function clearRetry() {
    if (retryTimer !== null) {
      clearTimeout(retryTimer)
      retryTimer = null
    }
  }

  function discard() {
    if (!createdId) return
    const id = createdId
    createdId = 0
    savedFp = ''
    pending = null
    storage.clear()
    env.onDiscard(id)
  }

  /** 请求失败：4xx 是请求本身有问题（重试没意义）→ 报失败；其余（断网/超时/5xx）→ 退避重试 */
  function handleFailure(error: unknown) {
    const status = Number((error as { status?: number } | null)?.status || 0)
    if (status >= 400 && status < 500) {
      env.onStatus('error')
      return
    }
    attempt += 1
    env.onStatus('offline', undefined, attempt)
    clearRetry()
    retryTimer = setTimeout(() => {
      retryTimer = null
      if (pending) enqueue(pending)
    }, Math.min(RETRY_BASE * 2 ** (attempt - 1), RETRY_MAX))
  }

  async function persist(snap: DraftEditState) {
    if (isBlankDraft(snap)) return
    const fp = draftFingerprint(snap)
    if (fp === savedFp) return
    env.onStatus('saving')
    try {
      const body = draftBody(snap)
      const id = snap.id || createdId
      if (id) {
        await env.update(id, body)
      } else {
        const row = await env.create(body)
        createdId = row.id
        env.onCreate(row.id)
        if (discardOnCreate) {
          // 保存期间作者清空并关了抽屉：刚建出来的空稿立刻丢掉
          discardOnCreate = false
          discard()
          return
        }
      }
      savedFp = fp
      attempt = 0
      clearRetry()
      // 只有「没有更新的未落库内容」时才清本地副本，否则会把并发期间的改动一起清掉
      if (!pending || draftFingerprint(pending) === fp) {
        pending = null
        storage.clear()
      }
      env.onStatus('saved', new Date())
    } catch (error) {
      handleFailure(error)
    }
  }

  async function pump() {
    if (pumping) return
    pumping = true
    try {
      while (queue) {
        const snap = queue
        queue = null
        await persist(snap)
      }
    } finally {
      pumping = false
    }
  }

  function enqueue(snap: DraftEditState) {
    queue = snap
    void pump()
  }

  /** 记下「这份还没落库」并写本地副本（R-213：先留本地，再谈服务器） */
  function remember(snap: DraftEditState) {
    pending = snap
    storage.write(snap, snap.id || createdId)
  }

  function schedule() {
    clearTimer()
    const cur = env.read()
    if (isBlankDraft(cur)) {
      // 空稿不留本地副本（关闭时会走「空稿自动删除」）
      if (!createdId) return
      pending = null
      storage.clear()
      return
    }
    if (draftFingerprint(cur) === savedFp) {
      // 服务器已经有了这份内容（例如改了又改回来），副本没用了
      pending = null
      storage.clear()
      return
    }
    remember(cur)
    env.onStatus('dirty')
    timer = setTimeout(() => {
      timer = null
      if (pending) enqueue(pending)
    }, delay)
  }

  /** 不等防抖，立刻保存一次（内容为空则什么都不做） */
  function flush() {
    clearTimer()
    const cur = env.read()
    if (isBlankDraft(cur)) return
    remember(cur)
    enqueue(cur)
  }

  function closeOut() {
    clearTimer()
    const cur = env.read()
    if (isBlankDraft(cur)) {
      pending = null
      if (createdId) {
        queue = null
        discard()
      } else if (pumping) {
        discardOnCreate = true
      }
      return
    }
    flush()
  }

  function retryNow() {
    clearRetry()
    attempt = 0
    if (!pending && !queue) return
    enqueue((pending ?? queue) as DraftEditState)
  }

  function markSaved(s: DraftEditState) {
    clearTimer()
    clearRetry()
    queue = null
    pending = null
    attempt = 0
    savedFp = draftFingerprint(s)
    storage.clear()
    env.onStatus('saved', new Date())
  }

  /** 打开草稿：把当前内容当作「服务器已保存」的基线（不清本地副本，留给 R-213 兜底判断） */
  function baseline(s: DraftEditState) {
    clearTimer()
    pending = null
    savedFp = draftFingerprint(s)
  }

  function dispose() {
    clearTimer()
    clearRetry()
    queue = null
    // 故意**不清**本地副本：这正是断网/刷新兜底的意义
  }

  function reset() {
    clearTimer()
    clearRetry()
    queue = null
    pending = null
    createdId = 0
    savedFp = ''
    attempt = 0
    discardOnCreate = false
  }

  return { reset, schedule, flush, closeOut, retryNow, markSaved, baseline, dispose }
}
