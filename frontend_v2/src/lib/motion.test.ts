import { describe, it, expect } from 'vitest'
import { listReplace } from './motion'

// R-199：素材库「换一批结果」的编排不变量——新卡必须等旧卡退场后再入场，
// 否则两组卡在同一批网格位置上交叉淡入，看起来就像「结果卡没有动画」。
describe('listReplace 换批编排（R-199）', () => {
  it('新卡的基础延迟晚于旧卡退场时长', () => {
    expect(listReplace.baseDelay).toBeGreaterThanOrEqual(listReplace.exitDuration)
  })

  it('错峰封顶项数覆盖一整批（PAGE_SIZE=20），一屏内不留「整块同时进场」', () => {
    expect(listReplace.maxItems).toBeGreaterThanOrEqual(20)
  })

  it('铺满一屏的总时长控制在 1s 内（基础延迟 + 错峰上限）', () => {
    expect(listReplace.baseDelay + listReplace.maxItems * listReplace.stagger).toBeLessThan(1)
  })
})
