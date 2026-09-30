// R-214 提词器：纯逻辑层（Markdown→口播纯文本、分段、时长预估、匀速滚动推进、设置持久化）
//
// 这一层**不碰 DOM、不碰 React**，全部可在 vitest 里离线断言（需求的验收清单要求这些纯函数有单测）。
// 页面（`index.tsx`）只负责把这里的结果渲染出来，并做测量/事件绑定。

/** 中文口播语速口径：约 4 字/秒（与 `backend/app/core/transcript.py` 的预估口径一致） */
export const CHARS_PER_SECOND = 4

/**
 * 每个可视行大约能放多少中文字。
 * 正文 `max-width: 60ch`，而一个中文字宽≈2ch → 约 30 字/行。
 * 用它把「像素/秒」换算成作者能理解的「字/秒」（字号变化时 30 不变，因为 max-width 用的是 ch）。
 */
export const CHARS_PER_LINE = 30

/**
 * 「读字基准线」= 屏幕上沿往下**一个行高**处。
 * 为什么不是屏幕高度的百分比：正文首行贴屏幕上沿（作者要求「眼睛不下移」），
 * 作者读的就是**最上面那一行**，因此基准线必须跟着行高走——这样
 * ① 一进页面（scrollTop=0）当前段一定是第一段；② 任何视口高度/字号下都成立；
 * ③ 段随滚动单调前进；④ 滚到底时一定是最后一段。
 */
export const READING_LINE_LINES = 1

/** 读字基准线距屏幕上沿的像素数 */
export function readingLinePx(fontSize: number, lineHeight: number): number {
  return lineHeightPx(fontSize, lineHeight) * READING_LINE_LINES
}

/** 控制条「3s 无操作淡出」 */
export const CONTROLS_IDLE_MS = 3000

export interface PrompterSettings {
  /** 字号 px（28–120，默认 56） */
  fontSize: number
  /** 行距倍数（1.4–2.4，默认 1.8） */
  lineHeight: number
  /** 滚动速度 px/s（4–160，默认按 4 字/秒折算） */
  speed: number
  /** 镜像翻转（给分光镜式硬件提词器） */
  mirrored: boolean
}

export const PROMPTER_SETTINGS_KEY = 'echo_v2_prompter'

export const PROMPTER_LIMITS = {
  fontSize: { min: 28, max: 120, step: 2 },
  lineHeight: { min: 1.4, max: 2.4, step: 0.1 },
  speed: { min: 4, max: 160, step: 2 }
} as const

/** 行高像素：字号 × 行距（换算「像素/秒 ↔ 字/秒」的桥梁） */
export function lineHeightPx(fontSize: number, lineHeight: number): number {
  return Math.max(1, fontSize * lineHeight)
}

/** 像素/秒 → 字/秒（纯换算，只为界面显示，不影响滚动本身） */
export function charsPerSecond(speed: number, fontSize: number, lineHeight: number): number {
  const perLine = (speed * CHARS_PER_LINE) / lineHeightPx(fontSize, lineHeight)
  return Math.max(0, perLine)
}

/** 字/秒 → 像素/秒（默认速度就用它标定，使默认滚动≈4 字/秒） */
export function speedForSpeech(fontSize: number, lineHeight: number, cps = CHARS_PER_SECOND): number {
  return (cps * lineHeightPx(fontSize, lineHeight)) / CHARS_PER_LINE
}

function clamp(v: number, min: number, max: number): number {
  return Math.min(max, Math.max(min, v))
}

/** 供页面复用的夹紧（手动滚动的边界） */
export { clamp }

function round1(v: number): number {
  return Math.round(v * 10) / 10
}

const DEFAULT_FONT_SIZE = 56
const DEFAULT_LINE_HEIGHT = 1.8

export const PROMPTER_DEFAULTS: PrompterSettings = {
  fontSize: DEFAULT_FONT_SIZE,
  lineHeight: DEFAULT_LINE_HEIGHT,
  speed: round1(speedForSpeech(DEFAULT_FONT_SIZE, DEFAULT_LINE_HEIGHT)),
  mirrored: false
}

/** 把任意来源（localStorage / 旧版本设置 / 手动输入）的值收敛成合法设置 */
export function normalizeSettings(input: Partial<PrompterSettings> | null | undefined): PrompterSettings {
  const raw = input ?? {}
  const num = (v: unknown, fallback: number): number =>
    typeof v === 'number' && Number.isFinite(v) ? v : fallback
  return {
    fontSize: Math.round(clamp(num(raw.fontSize, PROMPTER_DEFAULTS.fontSize), PROMPTER_LIMITS.fontSize.min, PROMPTER_LIMITS.fontSize.max)),
    lineHeight: round1(clamp(num(raw.lineHeight, PROMPTER_DEFAULTS.lineHeight), PROMPTER_LIMITS.lineHeight.min, PROMPTER_LIMITS.lineHeight.max)),
    speed: round1(clamp(num(raw.speed, PROMPTER_DEFAULTS.speed), PROMPTER_LIMITS.speed.min, PROMPTER_LIMITS.speed.max)),
    mirrored: raw.mirrored === true
  }
}

/** 可注入的存储（测试用；默认 `window.localStorage`） */
export interface SettingsStore {
  getItem(key: string): string | null
  setItem(key: string, value: string): void
}

function defaultStore(): SettingsStore | null {
  try {
    return typeof localStorage === 'undefined' ? null : localStorage
  } catch {
    return null
  }
}

/** 读设置：坏 JSON / 脏字段都收敛成默认值，绝不抛（提词页不能因为一份脏设置白屏） */
export function readPrompterSettings(store: SettingsStore | null = defaultStore()): PrompterSettings {
  if (!store) return { ...PROMPTER_DEFAULTS }
  try {
    const raw = store.getItem(PROMPTER_SETTINGS_KEY)
    if (!raw) return { ...PROMPTER_DEFAULTS }
    const parsed: unknown = JSON.parse(raw)
    if (!parsed || typeof parsed !== 'object' || Array.isArray(parsed)) return { ...PROMPTER_DEFAULTS }
    return normalizeSettings(parsed as Partial<PrompterSettings>)
  } catch {
    return { ...PROMPTER_DEFAULTS }
  }
}

/** 写设置：写失败（隐私模式/配额）也不抛 */
export function writePrompterSettings(s: PrompterSettings, store: SettingsStore | null = defaultStore()): void {
  if (!store) return
  try {
    store.setItem(PROMPTER_SETTINGS_KEY, JSON.stringify(normalizeSettings(s)))
  } catch {
    /* 存不下就算了，本次会话内仍然生效 */
  }
}

/** 调试/点检用：把设置值按步长加减并夹紧 */
export function stepSetting<K extends 'fontSize' | 'lineHeight' | 'speed'>(
  s: PrompterSettings,
  key: K,
  direction: 1 | -1
): PrompterSettings {
  const limit = PROMPTER_LIMITS[key]
  const next = s[key] + limit.step * direction
  return normalizeSettings({ ...s, [key]: next })
}

// ---------------------------------------------------------------------------
// Markdown → 口播纯文本
// ---------------------------------------------------------------------------

const IMAGE_RE = /!\[([^\]]*)\]\([^)\s]*(?:\s+"[^"]*")?\)/g
const LINK_RE = /\[([^\]]*)\]\([^)\s]*(?:\s+"[^"]*")?\)/g
const AUTOLINK_RE = /<((?:https?|mailto):[^>\s]+)>/g
const INLINE_CODE_RE = /`([^`\n]*)`/g
const BOLD_RE = /\*\*([\s\S]+?)\*\*/g
const BOLD_ALT_RE = /__([\s\S]+?)__/g
const ITALIC_RE = /\*([^*\n]+)\*/g
const ITALIC_ALT_RE = /(^|\s)_([^_\n]+)_(?=\s|$)/g
const STRIKE_RE = /~~([\s\S]+?)~~/g
const CODE_FENCE_RE = /^\s*(?:```|~~~).*$/
const HEADING_RE = /^\s{0,3}#{1,6}\s+/
const QUOTE_RE = /^\s{0,3}>\s?/
const LIST_RE = /^\s*(?:[-*+]|\d+[.)])\s+/
const HR_RE = /^\s{0,3}(?:([-*_])\s*){3,}$/
const HTML_TAG_RE = /<\/?[a-zA-Z][^>\n]*>/g
const TABLE_SEP_RE = /^\s*\|?[\s:|-]*-[\s:|-]*\|?\s*$/

/** 一行是不是表格数据行（`| a | b |`） */
function isTableRow(line: string): boolean {
  const t = line.trim()
  return t.length > 1 && t.startsWith('|') && t.endsWith('|')
}

/** 剥掉 Markdown 格式标记：图片/表格降级为纯文本、其余标记只去符号（口播时不该念出 `**`） */
export function stripMarkdown(markdown: string): string {
  const out: string[] = []
  for (const rawLine of String(markdown ?? '').split(/\r?\n/)) {
    if (CODE_FENCE_RE.test(rawLine)) continue
    const t = rawLine.trim()
    if (!t) {
      out.push('')
      continue
    }
    if (HR_RE.test(t)) continue // 分隔线不是口播内容（`---` / `***` / `- - -`）
    if (TABLE_SEP_RE.test(t) && t.includes('-')) continue // 表格对齐行
    let line = rawLine
    if (isTableRow(line)) line = line.replace(/^\||\|$/g, '').replace(/\|/g, ' ')
    line = line.replace(IMAGE_RE, '$1').replace(LINK_RE, '$1').replace(AUTOLINK_RE, '')
    line = line
      .replace(INLINE_CODE_RE, '$1')
      .replace(BOLD_RE, '$1')
      .replace(BOLD_ALT_RE, '$1')
      .replace(STRIKE_RE, '$1')
      .replace(ITALIC_RE, '$1')
      .replace(ITALIC_ALT_RE, '$1$2')
    line = line.replace(HTML_TAG_RE, '').replace(/\\([\\`*_{}[\]()#+.!-])/g, '$1')
    line = line.replace(HEADING_RE, '').replace(QUOTE_RE, '').replace(LIST_RE, '')
    out.push(line.replace(/\s+/g, ' ').trim())
  }
  // 压缩连续空行（分段靠空行，多留一行没有意义）
  return out
    .join('\n')
    .replace(/\n{3,}/g, '\n\n')
    .replace(/^\n+|\n+$/g, '')
}

/** 提词正文 = 剥格式 + 压空行 */
export function promptText(markdown: string): string {
  return stripMarkdown(markdown)
}

export interface PrompterSegment {
  index: number
  text: string
}

/** 按空行分段（空行是作者写的「换段」标记） */
export function splitSegments(text: string): PrompterSegment[] {
  return String(text ?? '')
    .split(/\n\s*\n/)
    .map((s) => s.trim())
    .filter(Boolean)
    .map((s, index) => ({ index, text: s }))
}

/** 口播字数：不计空白（换行/空格不占时间） */
export function spokenCharCount(text: string): number {
  return String(text ?? '').replace(/\s/g, '').length
}

/** `00:00` / `12:34`（负数与 NaN 都归 0，界面上不能出现 `NaN:NaN`） */
export function fmtClock(totalSeconds: number): string {
  const s = Number.isFinite(totalSeconds) ? Math.max(0, Math.floor(totalSeconds)) : 0
  const m = Math.floor(s / 60)
  return `${String(m).padStart(2, '0')}:${String(s % 60).padStart(2, '0')}`
}

export interface PrompterTiming {
  /** 全文按语速折算的总时长（秒） */
  totalSeconds: number
  /** 剩余秒数（已录超过总时长则 0） */
  remainingSeconds: number
}

/** 时长预估：只跟「正文字数 + 已录时长 + 语速口径」有关，与字号/滚动速度无关 */
export function promptTiming(chars: number, elapsedSeconds: number, charsPerSecond = CHARS_PER_SECOND): PrompterTiming {
  const cps = charsPerSecond > 0 ? charsPerSecond : CHARS_PER_SECOND
  const totalSeconds = Math.max(0, Math.ceil(Math.max(0, chars) / cps))
  const elapsed = Number.isFinite(elapsedSeconds) ? Math.max(0, elapsedSeconds) : 0
  return { totalSeconds, remainingSeconds: Math.max(0, totalSeconds - Math.floor(elapsed)) }
}

// ---------------------------------------------------------------------------
// 滚动与分段高亮
// ---------------------------------------------------------------------------

export interface SegmentBox {
  /** 段落在正文容器坐标系里的上沿（不随滚动变化） */
  top: number
  height: number
}

/**
 * 基准线落在哪一段（>=0）。
 * `line` = 正文容器坐标系里的读字基准线（= scrollTop + 视口内基准线偏移）。
 * 取「上沿不超过基准线」的最后一段：单调、不抖，滚到底时落在最后一段。
 */
export function activeSegmentIndex(boxes: ReadonlyArray<SegmentBox>, line: number): number {
  if (!boxes.length) return 0
  let idx = 0
  for (let i = 0; i < boxes.length; i += 1) {
    if (boxes[i].top <= line) idx = i
    else break
  }
  return idx
}

/** 匀速推进一帧（`dtMs` 毫秒 × `speed` 像素/秒），夹在 [0, maxScroll] */
export function advanceScroll(scrollTop: number, dtMs: number, speed: number, maxScroll: number): number {
  const max = Math.max(0, maxScroll)
  const base = Number.isFinite(scrollTop) ? scrollTop : 0
  const dt = Number.isFinite(dtMs) ? Math.max(0, dtMs) : 0
  const sp = Number.isFinite(speed) ? Math.max(0, speed) : 0
  const next = base + (sp * dt) / 1000
  return clamp(next, 0, max)
}

/** 是否已经滚到底（用于「到底自动停」） */
export function isAtEnd(scrollTop: number, maxScroll: number, tolerance = 1): boolean {
  const max = Math.max(0, maxScroll)
  if (max <= 0) return true
  return scrollTop >= max - tolerance
}

/** 手动 ↑/↓ 的步长：约 3 行 */
export function manualStepPx(fontSize: number, lineHeight: number): number {
  return Math.round(lineHeightPx(fontSize, lineHeight) * 3)
}
