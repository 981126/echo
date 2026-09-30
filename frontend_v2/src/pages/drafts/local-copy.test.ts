// R-213：本地「未同步副本」读写的健壮性
import { afterEach, describe, expect, it } from 'vitest'
import { LOCAL_COPY_KEY, clearLocalCopy, readLocalCopy, writeLocalCopy } from './local-copy'
import type { DraftEditState } from './edit-drawer'

const state: DraftEditState = {
  id: 0,
  title: '断网时写的标题',
  cover_text: '',
  script: '正文',
  video_id: null,
  tagsText: '',
  publish_platform: '',
  publish_url: '',
  published_at: ''
}

afterEach(() => window.localStorage.clear())

describe('local-copy（R-213）', () => {
  it('写得进、读得出（含时间与草稿 id）', () => {
    writeLocalCopy({ state, id: 0, at: '2026-09-29T10:00:00.000Z' })
    const copy = readLocalCopy()
    expect(copy?.state.script).toBe('正文')
    expect(copy?.state.title).toBe('断网时写的标题')
    expect(copy?.id).toBe(0)
    expect(copy?.at).toBe('2026-09-29T10:00:00.000Z')
  })

  it('没有副本时返回 null，清掉后也是 null', () => {
    expect(readLocalCopy()).toBeNull()
    writeLocalCopy({ state, id: 12, at: '' })
    expect(readLocalCopy()?.id).toBe(12)
    clearLocalCopy()
    expect(readLocalCopy()).toBeNull()
  })

  it('坏 JSON / 缺字段 / 类型不对都不炸：坏数据当没有，字段降级成空串', () => {
    window.localStorage.setItem(LOCAL_COPY_KEY, '{不是 JSON')
    expect(readLocalCopy()).toBeNull()

    window.localStorage.setItem(LOCAL_COPY_KEY, JSON.stringify({ at: 123, id: 'x' }))
    expect(readLocalCopy()).toBeNull() // 没有 state

    window.localStorage.setItem(
      LOCAL_COPY_KEY,
      JSON.stringify({ state: { title: 42, script: null, video_id: '7' }, id: '9' })
    )
    const copy = readLocalCopy()
    expect(copy?.state.title).toBe('')
    expect(copy?.state.script).toBe('')
    expect(copy?.state.video_id).toBe(7) // 数字字符串仍能解析
    expect(copy?.state.tagsText).toBe('')
    expect(copy?.id).toBe(9)
    expect(copy?.at).toBe('')
  })
})
