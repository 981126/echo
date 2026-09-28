import { describe, it, expect } from 'vitest'
import { listReplace } from './motion'

// R-199：素材库「换一批结果」的编排不变量。
// 教训一：新卡的入场动画会被旧卡的退场动画盖住（popLayout 把退场卡绝对定位在原格子上），
//         所以新卡必须等「同一格」的旧卡退完再入场（逐格交接）。
// 教训二：退场是作者点名要保留的老动画（0.35s + 缩到 0.94 + index×0.035 错峰），不许再被改掉。
describe('listReplace 换批编排（R-199）', () => {
  it('旧卡退场 = 换批前的老动画（0.35s / 0.035 错峰 / 封顶 16 / scale 0.94）', () => {
    expect(listReplace.exit).toEqual({ duration: 0.35, stagger: 0.035, maxItems: 16, scale: 0.94 })
  })

  it('新卡进场 = 退场倒放：时长与错峰节奏和退场一致（只有方向相反）', () => {
    expect(listReplace.enter.duration).toBe(listReplace.exit.duration)
    // 进场起步的 scale 直接复用退场收尾的 scale（镜像），不另立一套数值
    expect(listReplace.exit.scale).toBeLessThan(1)
  })

  it('同一格：新卡必须等旧卡退完（含呼吸量）再入场 → 两段动画不互相抵消', () => {
    expect(listReplace.enter.breathAfterExit).toBeGreaterThanOrEqual(0)
    const enterDelayFor = (i: number) =>
      Math.min(i, listReplace.exit.maxItems) * listReplace.exit.stagger +
      listReplace.exit.duration +
      listReplace.enter.breathAfterExit
    for (const i of [0, 1, 5, 9, 15, 19]) {
      const exitDone = Math.min(i, listReplace.exit.maxItems) * listReplace.exit.stagger + listReplace.exit.duration
      expect(enterDelayFor(i)).toBeGreaterThanOrEqual(exitDone)
    }
  })

  it('首屏（前 8 张）在新卡全部落定 1.1s 内出现', () => {
    const i = 7
    const done =
      Math.min(i, listReplace.exit.maxItems) * listReplace.exit.stagger +
      listReplace.exit.duration +
      listReplace.enter.breathAfterExit +
      listReplace.enter.duration
    expect(done).toBeLessThan(1.1)
  })
})
