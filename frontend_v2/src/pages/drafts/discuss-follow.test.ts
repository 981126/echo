import { describe, it, expect } from 'vitest'
import { NEAR_BOTTOM_PX, countNewRows, isNearBottom, maxRowId } from './discuss-follow'
import type { Discussion } from './types'

const row = (id: number, kind = 'draft'): Discussion => ({ id, actor: 'model1', kind, round: 1, content: `#${id}` })

describe('isNearBottom（R-206 讨论留痕跟随）', () => {
  it('元素未挂载时按贴底处理（没切到 tab 时不该显示新留痕提示）', () => {
    expect(isNearBottom(null)).toBe(true)
    expect(isNearBottom(undefined)).toBe(true)
  })

  it('滚到底 / 距底 ≤ 阈值 → 贴底（新留痕自动跟随）', () => {
    expect(isNearBottom({ scrollTop: 3515, scrollHeight: 4009, clientHeight: 494 })).toBe(true)
    expect(isNearBottom({ scrollTop: 4009 - 494 - NEAR_BOTTOM_PX, scrollHeight: 4009, clientHeight: 494 })).toBe(true)
  })

  it('翻看历史（距底 > 阈值）→ 不贴底（改成浮出「N 条新留痕」提示，不抢滚动条）', () => {
    expect(isNearBottom({ scrollTop: 0, scrollHeight: 4009, clientHeight: 494 })).toBe(false)
    expect(isNearBottom({ scrollTop: 4009 - 494 - NEAR_BOTTOM_PX - 1, scrollHeight: 4009, clientHeight: 494 })).toBe(false)
  })

  it('内容比视口短（没有滚动条）也算贴底', () => {
    expect(isNearBottom({ scrollTop: 0, scrollHeight: 300, clientHeight: 494 })).toBe(true)
  })
})

describe('countNewRows / maxRowId（R-206）', () => {
  const rows = [row(1), row(2, 'run'), row(3, 'critique')]

  it('只数「真留痕」，运行头（kind=run）不算模型发言', () => {
    expect(countNewRows(rows, 0)).toBe(2)
    expect(countNewRows(rows, 1)).toBe(1)
    expect(countNewRows(rows, 3)).toBe(0)
  })

  it('游标按最大 id 推进（运行头也要推进，否则它会被反复当成新内容）', () => {
    expect(maxRowId(rows)).toBe(3)
    expect(maxRowId([])).toBe(0)
  })
})
