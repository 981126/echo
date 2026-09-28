import { describe, it, expect } from 'vitest'
import { listReplace } from './motion'

// R-199：素材库「换一批结果」的编排不变量。
// 教训一：新卡的入场动画会被旧卡的退场动画盖住（popLayout 把退场卡绝对定位在原格子上），
//         所以新卡必须等「同一格」的旧卡退完再入场（逐格交接）。
// 教训二：退场是作者点名要保留的老动画（0.35s + 缩到 0.94 + index×0.035 错峰），不许再被改掉。
// 教训三：进场照着退场做镜像（0.94）、或改成 150ms 就落定的 spring，作者都反馈「一点都不明显」——
//         进场必须**幅度更大 + 更慢 + 中段有过冲**，肉眼才跟得上。
describe('listReplace 换批编排（R-199）', () => {
  it('旧卡退场 = 换批前的老动画（0.35s / 0.035 错峰 / 封顶 16 / scale 0.94）', () => {
    expect(listReplace.exit).toEqual({ duration: 0.35, stagger: 0.035, maxItems: 16, scale: 0.94 })
  })

  it('新卡进场幅度明显大于退场（否则「一点都不明显」）', () => {
    expect(listReplace.enter.fromScale).toBeLessThan(listReplace.exit.scale - 0.1)
    expect(listReplace.enter.fromScale).toBeGreaterThanOrEqual(0.7) // 别夸张到糊成一团
  })

  it('新卡进场比退场慢，且用带过冲的缓动（中段看得见）', () => {
    expect(listReplace.enter.duration).toBeGreaterThan(listReplace.exit.duration)
    expect(listReplace.enter.ease).toBe('backOut')
  })

  it('同一格：新卡必须等旧卡退完（含呼吸量）再入场 → 两段动画不互相抵消', () => {
    const enterDelayFor = (i: number) =>
      Math.min(i, listReplace.exit.maxItems) * listReplace.exit.stagger +
      listReplace.exit.duration +
      listReplace.enter.breathAfterExit
    for (const i of [0, 1, 5, 9, 15, 19]) {
      const exitDone = Math.min(i, listReplace.exit.maxItems) * listReplace.exit.stagger + listReplace.exit.duration
      expect(enterDelayFor(i)).toBeGreaterThanOrEqual(exitDone)
    }
  })

  it('首屏前 4 张：新卡从开始到落定 ≤ 1.1s（不至于等到人走）', () => {
    const done =
      Math.min(3, listReplace.exit.maxItems) * listReplace.exit.stagger +
      listReplace.exit.duration +
      listReplace.enter.breathAfterExit +
      listReplace.enter.duration
    expect(done).toBeLessThan(1.1)
  })
})
