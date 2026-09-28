import { describe, it, expect } from 'vitest'
import { buildTimelineModel } from './timeline'

describe('buildTimelineModel', () => {
  it('空数据返回空模型', () => {
    const m = buildTimelineModel([], [])
    expect(m.events).toEqual([])
    expect(m.width).toBe(0)
    expect(m.todayLeft).toBeNull()
  })

  it('本地素材入轴、倒序（最新在左）、未来日期不入轴', () => {
    const m = buildTimelineModel(
      [
        { id: 1, title: '旧', published_at: '2026-09-01T10:00:00' },
        { id: 2, title: '新', published_at: '2026-09-20T10:00:00' },
        { id: 3, title: '未来', planned_publish_at: '2099-01-01T00:00:00' }
      ],
      []
    )
    expect(m.events.map((e) => e.id)).toEqual([2, 1]) // 最新在前（左）
    expect(m.events[0].left).toBeLessThan(m.events[1].left)
    expect(m.width).toBeGreaterThan(0)
  })

  it('已绑定云端/合并的本地素材不重复入轴；云端作品带来源标签', () => {
    const m = buildTimelineModel(
      [{ id: 9, title: '本地已绑', published_at: '2026-09-10T00:00:00', platform_post_id: 'douyin:x' }],
      [{ id: 5, title: '云端', publish_time: '2026-09-12T00:00:00', platform: 'douyin', creator_kind: 'benchmark' }]
    )
    expect(m.events).toHaveLength(1)
    expect(m.events[0].kind).toBe('cloud')
    expect(m.events[0].srcLabel).toBe('抖音·对标')
  })
})
