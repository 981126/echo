import { describe, it, expect } from 'vitest'
import { cardKeyForPayload, claimPool, type TaskRow } from './use-card-tasks'
import type { CardItem } from './types'

// R-220：未认领池重映射——修「/api/tasks 先回、/api/library 后回」竞速丢任务

const cloud = (key: string, id: number, postIds: number[]): CardItem => ({
  key,
  kind: 'cloud',
  id,
  type: 'work',
  title: key,
  cover_url: '',
  platforms: ['douyin'],
  tags: [],
  status: 'synced',
  is_ad: false,
  merged: 0,
  cloudPosts: postIds.map((id2) => ({ id: id2, platform: 'douyin', platform_post_id: `p${id2}`, title: '', cover: '', publish_time: null, page_url: '' })),
  hasVideo: false,
  date: ''
})

const card = cloud('cloud:1', 1, [101, 102])
const running = (id: number, postId: number): TaskRow => ({ id, status: 'running', progress: 4, note: '排队中…', payload: { post_id: postId } })

describe('claimPool（R-220 未认领池重映射）', () => {
  it('卡片未加载（空列表）→ 全部留池，无认领', () => {
    const pool = new Map<number, TaskRow>([
      [1, running(1, 101)],
      [2, running(2, 102)]
    ])
    const { claims, pool: next } = claimPool(pool, [], new Set(), new Set())
    expect(claims).toEqual([])
    expect(next.size).toBe(2)
  })

  it('卡片到位 → 命中 post_id 的任务被认领并出池', () => {
    const pool = new Map<number, TaskRow>([
      [1, running(1, 101)],
      [2, running(2, 999)]
    ])
    const { claims, pool: next } = claimPool(pool, [card], new Set(), new Set())
    expect(claims).toEqual([{ key: 'cloud:1', task: expect.objectContaining({ id: 1 }) }])
    expect(next.size).toBe(1)
    expect(next.has(2)).toBe(true)
  })

  it('终态任务出池丢弃，不产生幽灵遮罩', () => {
    const pool = new Map<number, TaskRow>([
      [1, running(1, 101)],
      [2, { id: 2, status: 'done', payload: { post_id: 101 } }],
      [3, { id: 3, status: 'failed', payload: { post_id: 102 } }]
    ])
    const { claims, pool: next } = claimPool(pool, [card], new Set(), new Set())
    expect(claims).toHaveLength(1)
    expect(next.has(2)).toBe(false)
    expect(next.has(3)).toBe(false)
  })

  it('已被认领的任务（claimedIds）出池丢弃', () => {
    const pool = new Map<number, TaskRow>([[1, running(1, 101)]])
    const { claims, pool: next } = claimPool(pool, [card], new Set([1]), new Set())
    expect(claims).toEqual([])
    expect(next.size).toBe(0)
  })

  it('卡片已被其它任务接管（claimedKeys）→ 留池待重试', () => {
    const pool = new Map<number, TaskRow>([[1, running(1, 101)]])
    const { claims, pool: next } = claimPool(pool, [card], new Set(), new Set(['cloud:1']))
    expect(claims).toEqual([])
    expect(next.has(1)).toBe(true)
  })

  it('不修改入参池（纯函数）', () => {
    const pool = new Map<number, TaskRow>([[1, running(1, 101)]])
    const snapshot = new Map(pool)
    claimPool(pool, [card], new Set(), new Set())
    expect(pool.size).toBe(snapshot.size)
    expect(pool.has(1)).toBe(true)
  })

  it('cardKeyForPayload：post_id 认领合并卡、坏 payload 返回空', () => {
    expect(cardKeyForPayload({ post_id: 102 }, [card])).toBe('cloud:1')
    expect(cardKeyForPayload({ post_id: 999 }, [card])).toBe('')
    expect(cardKeyForPayload('not-json{', [card])).toBe('')
    expect(cardKeyForPayload({ video_id: 1 }, [card])).toBe('')
  })
})
