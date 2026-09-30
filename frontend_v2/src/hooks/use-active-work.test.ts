import { describe, it, expect } from 'vitest'
import { taskRowToActiveItem, syncJobToActiveItem } from './use-active-work'

describe('进行中任务映射（R-202）', () => {
  it('taskRowToActiveItem：映射字段、解析 payload、进度钳制', () => {
    const item = taskRowToActiveItem({
      id: 7,
      kind: 'opportunity_gap',
      status: 'running',
      progress: 130,
      note: '找缺口选题中',
      label: '缺口选题',
      target: '/home',
      payload: '{"limit":6}'
    })
    expect(item.key).toBe('task:7')
    expect(item.source).toBe('task')
    expect(item.label).toBe('缺口选题')
    expect(item.target).toBe('/home')
    expect(item.progress).toBe(100) // 钳制
    expect(item.payload).toEqual({ limit: 6 })
  })

  it('taskRowToActiveItem：无 label 回退 kind、坏 payload 回退空对象', () => {
    const item = taskRowToActiveItem({ id: 1, kind: 'hot_refresh', status: 'pending', payload: 'not-json' })
    expect(item.label).toBe('hot_refresh')
    expect(item.progress).toBe(0)
    expect(item.payload).toEqual({})
  })

  it('syncJobToActiveItem：按 done/total 计算百分比并带 /creators 跳转', () => {
    const item = syncJobToActiveItem({
      id: 3,
      creator_id: 5,
      status: 'running',
      progress_done: 3,
      progress_total: 12,
      progress_note: '同步作品 3/12'
    })
    expect(item.key).toBe('sync:3')
    expect(item.kind).toBe('platform_sync')
    expect(item.target).toBe('/creators')
    expect(item.progress).toBe(25)
    expect(item.note).toBe('同步作品 3/12')
    expect(item.payload).toEqual({ creator_id: 5, scope: undefined })
  })
})
