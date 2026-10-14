// R-212/R-213：新建草稿实时保存 + 断网本地兜底 的纯逻辑单测
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import {
  AUTOSAVE_DELAY,
  RETRY_BASE,
  createAutoSaver,
  draftBody,
  draftFingerprint,
  isBlankDraft,
  type AutoSavePayload,
  type AutoSaveStatus
} from './autosave'
import type { DraftEditState } from './edit-drawer'

function draft(patch: Partial<DraftEditState> = {}): DraftEditState {
  return {
    id: 0,
    title: '',
    cover_text: '',
    script: '',
    video_id: null,
    tagsText: '',
    publish_platform: '',
    publish_url: '',
    published_at: '',
    ...patch
  }
}

type FailMode = 'ok' | 'network' | 'http400'

/** 把 create 挂起，模拟「保存期间作者继续打字」；`mode` 模拟断网 / 4xx */
function harness() {
  let cur = draft()
  let mode: FailMode = 'ok'
  const created: AutoSavePayload[] = []
  const updated: Array<{ id: number; body: AutoSavePayload }> = []
  const statuses: AutoSaveStatus[] = []
  const attempts: Array<number | undefined> = []
  const discarded: number[] = []
  const copies: Array<{ state: DraftEditState; id: number }> = []
  let stored: { state: DraftEditState; id: number } | null = null
  let clears = 0
  let gate: Promise<void> | null = null
  let release: (() => void) | null = null
  let nextId = 7

  const maybeFail = () => {
    if (mode === 'network') throw new TypeError('Failed to fetch')
    if (mode === 'http400') throw Object.assign(new Error('草稿内容为空，未创建'), { status: 400 })
  }

  const saver = createAutoSaver({
    read: () => cur,
    create: async (body) => {
      created.push(body)
      maybeFail()
      if (gate) await gate
      return { id: nextId++ }
    },
    update: async (id, body) => {
      updated.push({ id, body })
      maybeFail()
    },
    // 与父组件一致：建稿成功即把 id 写回编辑态
    onCreate: (id) => {
      cur = { ...cur, id }
    },
    onDiscard: (id) => discarded.push(id),
    onStatus: (s, _at, attempt) => {
      statuses.push(s)
      attempts.push(attempt)
    },
    storage: {
      write: (state, id) => {
        stored = { state, id }
        copies.push({ state, id })
      },
      clear: () => {
        stored = null
        clears += 1
      }
    }
  })

  return {
    saver,
    created,
    updated,
    statuses,
    attempts,
    discarded,
    copies,
    read: () => cur,
    get stored() {
      return stored
    },
    get clears() {
      return clears
    },
    setMode: (m: FailMode) => {
      mode = m
    },
    set: (patch: Partial<DraftEditState>) => {
      cur = { ...cur, ...patch }
    },
    hold: () => {
      gate = new Promise<void>((r) => {
        release = () => {
          gate = null
          r()
        }
      })
    },
    release: () => release?.()
  }
}

/** 冲掉队列里的微任务（假定时器下 await 不会自己推进） */
async function flush() {
  for (let i = 0; i < 5; i++) await Promise.resolve()
}

beforeEach(() => {
  vi.useFakeTimers()
})
afterEach(() => {
  vi.useRealTimers()
})

describe('draftBody / isBlankDraft / draftFingerprint（R-212）', () => {
  it('请求体与【保存】路径同口径（标签按逗号切分去空）', () => {
    const body = draftBody(draft({ title: ' 标题 ', tagsText: '求职, 面试，，赚钱', published_at: '' }))
    expect(body.tags).toEqual(['求职', '面试', '赚钱'])
    expect(body.title).toBe(' 标题 ')
    expect(body.published_at).toBeNull()
  })

  it('全空=空稿（标题/封面字/正文/标签/关联素材都没有）；只选素材不算空', () => {
    expect(isBlankDraft(draft())).toBe(true)
    expect(isBlankDraft(draft({ script: '  ' }))).toBe(true)
    expect(isBlankDraft(draft({ video_id: 3 }))).toBe(false)
    expect(isBlankDraft(draft({ title: 'a' }))).toBe(false)
  })

  it('指纹只看内容不看 id（同内容不重复写库）', () => {
    expect(draftFingerprint(draft({ title: 'a' }))).toBe(draftFingerprint(draft({ id: 99, title: 'a' })))
  })
})

describe('createAutoSaver（R-212）', () => {
  it('还没内容时不建稿（R-154：空白草稿不落库）', async () => {
    const h = harness()
    h.saver.schedule()
    await vi.advanceTimersByTimeAsync(AUTOSAVE_DELAY * 2)
    expect(h.created).toHaveLength(0)
    expect(h.statuses).toHaveLength(0)
  })

  it('连续打字防抖成一次写库，且落库的是最后内容', async () => {
    const h = harness()
    h.set({ title: 'a' })
    h.saver.schedule()
    await vi.advanceTimersByTimeAsync(400)
    h.set({ title: 'ab' })
    h.saver.schedule()
    await vi.advanceTimersByTimeAsync(400)
    expect(h.created).toHaveLength(0) // 还没到 900ms（每次都重新计时）
    await vi.advanceTimersByTimeAsync(AUTOSAVE_DELAY)
    expect(h.created).toHaveLength(1)
    expect(h.created[0].title).toBe('ab')
    // 每次排期都报「待保存」，落库时报「保存中 → 已保存」（组件里同值 setState 会被 React 合并）
    expect(h.statuses).toEqual(['dirty', 'dirty', 'saving', 'saved'])
  })

  it('自动建出 id 之后继续改 → PATCH，不再重复建稿', async () => {
    const h = harness()
    h.set({ title: 'a' })
    h.saver.schedule()
    await vi.advanceTimersByTimeAsync(AUTOSAVE_DELAY)
    h.set({ script: '正文一' })
    h.saver.schedule()
    await vi.advanceTimersByTimeAsync(AUTOSAVE_DELAY)
    expect(h.created).toHaveLength(1)
    expect(h.updated).toHaveLength(1)
    expect(h.updated[0]).toMatchObject({ id: 7, body: { script: '正文一' } })
  })

  it('保存进行中继续打字不漏字：这次完成后把最新内容接着写完', async () => {
    const h = harness()
    h.hold()
    h.set({ title: 'a' })
    h.saver.schedule()
    await vi.advanceTimersByTimeAsync(AUTOSAVE_DELAY)
    expect(h.created).toHaveLength(1) // POST 在飞
    h.set({ title: 'ab' })
    h.saver.schedule()
    await vi.advanceTimersByTimeAsync(AUTOSAVE_DELAY)
    expect(h.updated).toHaveLength(0)
    h.release()
    await flush()
    expect(h.updated).toHaveLength(1)
    expect(h.updated[0].body.title).toBe('ab') // 建稿期间敲的字没丢
    expect(h.created).toHaveLength(1)
  })

  it('关抽屉（closeOut）立刻补一次，不等防抖', async () => {
    const h = harness()
    h.set({ script: '最后几个字' })
    h.saver.schedule()
    await vi.advanceTimersByTimeAsync(200)
    h.saver.closeOut()
    await flush()
    expect(h.created).toHaveLength(1)
    expect(h.created[0].script).toBe('最后几个字')
  })

  it('自动建出的稿被清空后关闭 → 丢弃（逻辑删除），不再写库', async () => {
    const h = harness()
    h.set({ title: '临时' })
    h.saver.schedule()
    await vi.advanceTimersByTimeAsync(AUTOSAVE_DELAY)
    expect(h.created).toHaveLength(1)
    h.set({ id: 0, title: '' }) // 作者又清空了（父组件关闭时会重置编辑态）
    h.saver.closeOut()
    await flush()
    expect(h.discarded).toEqual([7])
    expect(h.updated).toHaveLength(0)
  })

  it('baseline：打开已有稿后未改动 → 不写库、不留本地副本（打开本身不算改动）', async () => {
    const h = harness()
    h.set({ id: 5, title: '服务器内容' })
    h.saver.baseline(h.read())
    h.saver.schedule()
    await vi.advanceTimersByTimeAsync(AUTOSAVE_DELAY)
    expect(h.created).toHaveLength(0)
    expect(h.updated).toHaveLength(0)
    expect(h.stored).toBeNull()
  })

  it('baseline 之后真实改动仍会落库', async () => {
    const h = harness()
    h.set({ id: 5, title: '服务器内容' })
    h.saver.baseline(h.read())
    h.set({ title: '改过的' })
    h.saver.schedule()
    await vi.advanceTimersByTimeAsync(AUTOSAVE_DELAY)
    expect(h.updated).toHaveLength(1)
    expect(h.updated[0]).toMatchObject({ id: 5, body: { title: '改过的' } })
  })

  it('markSaved（手动保存 / 服务端回填）后不再重复写', async () => {
    const h = harness()
    h.set({ title: 'a' })
    h.saver.schedule()
    await vi.advanceTimersByTimeAsync(AUTOSAVE_DELAY)
    h.saver.markSaved(h.read())
    h.saver.schedule()
    await vi.advanceTimersByTimeAsync(AUTOSAVE_DELAY)
    expect(h.created).toHaveLength(1)
    expect(h.updated).toHaveLength(0)
  })

  it('reset 清掉上一轮的 id：下一轮新建再打字是新建，不会写到上一张稿上', async () => {
    const h = harness()
    h.set({ title: '第一张' })
    h.saver.schedule()
    await vi.advanceTimersByTimeAsync(AUTOSAVE_DELAY)
    h.saver.reset()
    h.set({ id: 0, title: '第二张' })
    h.saver.schedule()
    await vi.advanceTimersByTimeAsync(AUTOSAVE_DELAY)
    expect(h.created.map((b) => b.title)).toEqual(['第一张', '第二张'])
    expect(h.updated).toHaveLength(0)
  })
})

describe('断网本地兜底 + 退避重试（R-213）', () => {
  it('改动先落本地副本（防抖之前），落库成功才清掉', async () => {
    const h = harness()
    h.set({ script: '离线也不怕' })
    h.saver.schedule()
    expect(h.stored?.state.script).toBe('离线也不怕') // 还没发请求就先留本地
    expect(h.clears).toBe(0)
    await vi.advanceTimersByTimeAsync(AUTOSAVE_DELAY)
    await flush()
    expect(h.clears).toBeGreaterThan(0)
    expect(h.stored).toBeNull()
  })

  it('断网：状态转 offline，按 1s→2s→4s 退避重试，副本一直留着', async () => {
    const h = harness()
    h.setMode('network')
    h.set({ title: 'a' })
    h.saver.schedule()
    await vi.advanceTimersByTimeAsync(AUTOSAVE_DELAY)
    expect(h.statuses.at(-1)).toBe('offline')
    expect(h.attempts.at(-1)).toBe(1)
    expect(h.created).toHaveLength(1)
    await vi.advanceTimersByTimeAsync(RETRY_BASE) // 第 1 次退避 1s
    expect(h.created).toHaveLength(2)
    await vi.advanceTimersByTimeAsync(RETRY_BASE * 2) // 第 2 次退避 2s
    expect(h.created).toHaveLength(3)
    expect(h.attempts.at(-1)).toBe(3)
    expect(h.stored?.state.title).toBe('a') // 一直没清
  })

  it('4xx（请求本身有问题）不重试：直接报失败', async () => {
    const h = harness()
    h.setMode('http400')
    h.set({ title: 'a' })
    h.saver.schedule()
    await vi.advanceTimersByTimeAsync(AUTOSAVE_DELAY)
    expect(h.statuses.at(-1)).toBe('error')
    await vi.advanceTimersByTimeAsync(60_000)
    expect(h.created).toHaveLength(1) // 没有反复重试
  })

  it('网络恢复（retryNow）：立刻重试并落库，随后清掉副本', async () => {
    const h = harness()
    h.setMode('network')
    h.set({ title: 'a' })
    h.saver.schedule()
    await vi.advanceTimersByTimeAsync(AUTOSAVE_DELAY)
    const tried = h.created.length
    h.setMode('ok')
    h.saver.retryNow()
    await flush()
    expect(h.created.length).toBe(tried + 1)
    expect(h.statuses.at(-1)).toBe('saved')
    expect(h.stored).toBeNull()
  })

  it('断网期间关抽屉：副本留着，重试仍写「关那一刻」的内容（编辑态已被重置也不丢）', async () => {
    const h = harness()
    h.setMode('network')
    h.set({ script: '断网时写的内容' })
    h.saver.schedule()
    await vi.advanceTimersByTimeAsync(AUTOSAVE_DELAY) // 第一次尝试失败
    h.saver.closeOut() // 关抽屉再补一次，也失败
    await flush()
    expect(h.stored?.state.script).toBe('断网时写的内容')
    h.set({ id: 0, title: '', script: '' }) // 父组件关闭抽屉后重置编辑态
    h.setMode('ok')
    await vi.advanceTimersByTimeAsync(RETRY_BASE * 8) // 退避重试最终补上
    expect(h.created.at(-1)?.script).toBe('断网时写的内容')
    expect(h.stored).toBeNull()
  })

  it('dispose（卸载）不清本地副本——这正是刷新后还能恢复的原因', async () => {
    const h = harness()
    h.setMode('network')
    h.set({ title: '别丢' })
    h.saver.schedule()
    await vi.advanceTimersByTimeAsync(AUTOSAVE_DELAY)
    h.saver.dispose()
    expect(h.stored?.state.title).toBe('别丢')
  })

  it('内容又改回服务器已有版本时不留无用副本', async () => {
    const h = harness()
    h.set({ title: 'a' })
    h.saver.schedule()
    await vi.advanceTimersByTimeAsync(AUTOSAVE_DELAY) // 'a' 已落库
    h.set({ title: 'ab' })
    h.saver.schedule() // 副本 = ab
    expect(h.stored?.state.title).toBe('ab')
    h.set({ title: 'a' })
    h.saver.schedule() // 改回去 → 服务器已有 'a'
    expect(h.stored).toBeNull()
  })
})
