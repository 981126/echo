import { describe, it, expect } from 'vitest'
import {
  CHARS_PER_SECOND,
  PROMPTER_DEFAULTS,
  PROMPTER_LIMITS,
  PROMPTER_SETTINGS_KEY,
  activeSegmentIndex,
  advanceScroll,
  charsPerSecond,
  fmtClock,
  isAtEnd,
  manualStepPx,
  normalizeSettings,
  promptText,
  promptTiming,
  readPrompterSettings,
  readingLinePx,
  spokenCharCount,
  speedForSpeech,
  splitSegments,
  stepSetting,
  writePrompterSettings,
  type SettingsStore
} from './prompter-text'

function memStore(initial: Record<string, string> = {}): SettingsStore & { data: Record<string, string> } {
  const data = { ...initial }
  return {
    data,
    getItem: (k) => (k in data ? data[k] : null),
    setItem: (k, v) => {
      data[k] = v
    }
  }
}

describe('stripMarkdown / promptText（R-214 口播纯文本）', () => {
  it('剥掉标题/加粗/斜体/行内代码/引用/列表标记（口播时不该念出符号）', () => {
    const md = [
      '# 大标题',
      '这是**加粗**和*斜体*，还有 `code` 与 ~~删除线~~。',
      '> 引用一句',
      '- 第一点',
      '1. 第二点'
    ].join('\n')
    expect(promptText(md)).toBe(['大标题', '这是加粗和斜体，还有 code 与 删除线。', '引用一句', '第一点', '第二点'].join('\n'))
  })

  it('图片降级为 alt 文本、链接留文字、表格拍平成文本、围栏代码块与分隔线不口播', () => {
    const md = [
      '![封面图](http://x/y.png)',
      '[点这里](http://a/b) 看详情',
      '| 项目 | 说明 |',
      '| --- | --- |',
      '| 一 | 二 |',
      '```js',
      'const a = 1',
      '```',
      '---'
    ].join('\n')
    expect(promptText(md)).toBe(['封面图', '点这里 看详情', '项目 说明', '一 二', 'const a = 1'].join('\n'))
  })

  it('空正文 / 全格式标记 → 空字符串（不产生空段）', () => {
    expect(promptText('')).toBe('')
    expect(splitSegments(promptText('---\n\n---'))).toEqual([])
  })
})

describe('splitSegments（R-214 按空行分段）', () => {
  it('按空行切段，段内换行保留', () => {
    const segs = splitSegments('第一段\n换行\n\n第二段\n\n\n第三段')
    expect(segs.map((s) => s.text)).toEqual(['第一段\n换行', '第二段', '第三段'])
    expect(segs.map((s) => s.index)).toEqual([0, 1, 2])
  })

  it('400 字 12 段的长稿正确切段（验收清单里的样本）', () => {
    const paragraph = '这是一句用来测试提词器的口播内容大约三十几个字左右'
    const segs = splitSegments(Array.from({ length: 12 }, () => paragraph).join('\n\n'))
    expect(segs).toHaveLength(12)
    expect(spokenCharCount(segs.map((s) => s.text).join(''))).toBe(spokenCharCount(paragraph) * 12)
  })
})

describe('spokenCharCount / fmtClock / promptTiming（R-214 时长与剩余预估）', () => {
  it('口播字数不计空白', () => {
    expect(spokenCharCount('你 好\n世界')).toBe(4)
    expect(spokenCharCount('')).toBe(0)
  })

  it('时钟格式化成 mm:ss，脏值不产生 NaN', () => {
    expect(fmtClock(0)).toBe('00:00')
    expect(fmtClock(75)).toBe('01:15')
    expect(fmtClock(599.9)).toBe('09:59')
    expect(fmtClock(Number.NaN)).toBe('00:00')
    expect(fmtClock(-5)).toBe('00:00')
  })

  it('总时长 = 字数 / 4（中文口径）；剩余 = 总时长 - 已录，且不为负', () => {
    expect(promptTiming(400, 0).totalSeconds).toBe(100)
    expect(promptTiming(400, 30).remainingSeconds).toBe(70)
    expect(promptTiming(400, 130).remainingSeconds).toBe(0)
    expect(promptTiming(0, 0)).toEqual({ totalSeconds: 0, remainingSeconds: 0 })
    // 与字号/滚动速度无关：同一字数同一已录 → 同一个剩余
    expect(promptTiming(400, 30)).toEqual(promptTiming(400, 30, CHARS_PER_SECOND))
  })

  it('像素/秒 ↔ 字/秒 换算自洽（默认速度就是按 4 字/秒标定的）', () => {
    const speed = speedForSpeech(56, 1.8)
    expect(charsPerSecond(speed, 56, 1.8)).toBeCloseTo(4, 5)
    const line = manualStepPx(56, 1.8)
    expect(line).toBeGreaterThan(0)
  })
})

describe('提词设置持久化（R-214：刷新后沿用）', () => {
  it('无记录 → 默认值（默认滚动速度≈4 字/秒）', () => {
    const s = readPrompterSettings(memStore())
    expect(s).toEqual(PROMPTER_DEFAULTS)
    expect(charsPerSecond(s.speed, s.fontSize, s.lineHeight)).toBeCloseTo(4, 1)
    expect(PROMPTER_DEFAULTS.fontSize).toBe(56)
    expect(PROMPTER_DEFAULTS.mirrored).toBe(false)
  })

  it('写入后读回一致（键名固定的 localStorage）', () => {
    const store = memStore()
    const next = { fontSize: 88, lineHeight: 2.1, speed: 24.5, mirrored: true }
    writePrompterSettings(next, store)
    expect(JSON.parse(store.data[PROMPTER_SETTINGS_KEY])).toEqual(next)
    expect(readPrompterSettings(store)).toEqual(next)
  })

  it('越界值被夹紧：字号 28–120、行距 1.4–2.4、速度 4–160', () => {
    expect(normalizeSettings({ fontSize: 999 }).fontSize).toBe(PROMPTER_LIMITS.fontSize.max)
    expect(normalizeSettings({ fontSize: 1 }).fontSize).toBe(PROMPTER_LIMITS.fontSize.min)
    expect(normalizeSettings({ lineHeight: 9 }).lineHeight).toBe(PROMPTER_LIMITS.lineHeight.max)
    expect(normalizeSettings({ speed: -3 }).speed).toBe(PROMPTER_LIMITS.speed.min)
    expect(normalizeSettings({ lineHeight: 1.83 }).lineHeight).toBe(1.8)
  })

  it('坏 JSON / 非对象 / 脏字段都不炸（提词页不能因为脏设置白屏）', () => {
    expect(readPrompterSettings(memStore({ [PROMPTER_SETTINGS_KEY]: '{oops' }))).toEqual(PROMPTER_DEFAULTS)
    expect(readPrompterSettings(memStore({ [PROMPTER_SETTINGS_KEY]: '[1,2]' }))).toEqual(PROMPTER_DEFAULTS)
    expect(readPrompterSettings(memStore({ [PROMPTER_SETTINGS_KEY]: '"x"' }))).toEqual(PROMPTER_DEFAULTS)
    const dirty = memStore({ [PROMPTER_SETTINGS_KEY]: JSON.stringify({ fontSize: 'big', mirrored: 'yes' }) })
    expect(readPrompterSettings(dirty)).toEqual(PROMPTER_DEFAULTS)
    expect(readPrompterSettings(null)).toEqual(PROMPTER_DEFAULTS)
    expect(() => writePrompterSettings(PROMPTER_DEFAULTS, null)).not.toThrow()
  })

  it('按步长加减（快捷键 ± / [ ]）', () => {
    const s = normalizeSettings({ fontSize: 56, speed: 20 })
    expect(stepSetting(s, 'fontSize', 1).fontSize).toBe(58)
    expect(stepSetting(s, 'fontSize', -1).fontSize).toBe(54)
    expect(stepSetting(s, 'speed', 1).speed).toBe(22)
    expect(stepSetting(normalizeSettings({ speed: PROMPTER_LIMITS.speed.max }), 'speed', 1).speed).toBe(PROMPTER_LIMITS.speed.max)
  })
})

describe('activeSegmentIndex（R-214 当前段高亮跟随滚动）', () => {
  const boxes = [
    { top: 0, height: 100 },
    { top: 100, height: 100 },
    { top: 200, height: 100 },
    { top: 300, height: 100 }
  ]

  it('基准线在段内 → 该段；移动后单调前进', () => {
    expect(activeSegmentIndex(boxes, 0)).toBe(0)
    expect(activeSegmentIndex(boxes, 99)).toBe(0)
    expect(activeSegmentIndex(boxes, 100)).toBe(1)
    expect(activeSegmentIndex(boxes, 250)).toBe(2)
    expect(activeSegmentIndex(boxes, 9999)).toBe(3)
  })

  it('空段列表 / 基准线在首段之前都安全', () => {
    expect(activeSegmentIndex([], 500)).toBe(0)
    expect(activeSegmentIndex(boxes, -50)).toBe(0)
  })

  it('读字基准线 = 一个行高：任何字号下，scrollTop=0 时当前段都是第一段', () => {
    for (const [fontSize, lineHeight] of [
      [28, 1.4],
      [56, 1.8],
      [120, 2.4]
    ]) {
      const line = readingLinePx(fontSize, lineHeight)
      const first = { top: 10, height: line }
      const second = { top: 10 + line + fontSize * 0.5, height: line }
      expect(activeSegmentIndex([first, second], line)).toBe(0)
    }
    // 屏幕上沿往下 1 个行高；极端值也不为 0
    expect(readingLinePx(56, 1.8)).toBeCloseTo(100.8, 3)
    expect(readingLinePx(120, 2.4)).toBeCloseTo(288, 3)
  })
})

describe('advanceScroll / isAtEnd（R-214 rAF 恒速推进）', () => {
  it('按 像素/秒 × 毫秒 推进', () => {
    expect(advanceScroll(0, 1000, 40, 1000)).toBe(40)
    expect(advanceScroll(0, 500, 40, 1000)).toBe(20)
  })

  it('夹在 [0, maxScroll]：到底不越界、不回退', () => {
    expect(advanceScroll(980, 1000, 40, 1000)).toBe(1000)
    expect(advanceScroll(0, 1000, -40, 1000)).toBe(0)
    expect(advanceScroll(50, Number.NaN, 40, 1000)).toBe(50)
    expect(advanceScroll(50, 1000, 40, -10)).toBe(0)
  })

  it('到底自动停的判据', () => {
    expect(isAtEnd(1000, 1000)).toBe(true)
    expect(isAtEnd(500, 1000)).toBe(false)
    expect(isAtEnd(0, 0)).toBe(true) // 内容比视口短：无须滚动，直接算到底
  })
})
