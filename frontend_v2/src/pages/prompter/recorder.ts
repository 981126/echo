// R-215 提词器内置录像：纯逻辑层（格式协商降级、文件名、录制状态机、安全阀、录后校验）
//
// 页面只负责 getUserMedia / MediaRecorder / DOM，这一段全部可在 vitest 里离线断言。

/**
 * 格式协商阶梯（R-215 规格）：
 *   1. `video/mp4;codecs=avc1.42E01E,mp4a.40.2` —— h264 兼容性最好，但 Chrome 有产出损坏文件的已知缺陷；
 *   2. `video/webm;codecs=vp9,opus` —— 可靠基线；
 *   3. `video/webm;codecs=vp8,opus`；
 *   4. `video/webm`（让浏览器自选）。
 * 逐级降级；全都不支持时返回 `''`（交给 MediaRecorder 默认，读 `recorder.mimeType` 兜底）。
 */
export const RECORDER_MIME_CANDIDATES = [
  'video/mp4;codecs=avc1.42E01E,mp4a.40.2',
  'video/webm;codecs=vp9,opus',
  'video/webm;codecs=vp8,opus',
  'video/webm'
] as const

/** WebM 基线（MP4 校验失败后退回这里） */
export const WEBM_FALLBACK_CANDIDATE = 'video/webm;codecs=vp9,opus'

export type MimeSupportCheck = (type: string) => boolean

/** 按阶梯挑第一个被浏览器支持的格式；`''` = 都不支持（用浏览器默认） */
export function pickRecorderMime(isSupported: MimeSupportCheck, candidates: readonly string[] = RECORDER_MIME_CANDIDATES): string {
  for (const t of candidates) {
    try {
      if (isSupported(t)) return t
    } catch {
      /* isTypeSupported 抛错当作不支持 */
    }
  }
  return ''
}

/** 去掉编解码参数，只看容器：`video/webm;codecs=…` → `video/webm` */
export function mimeContainer(mime: string): string {
  return String(mime || '').split(';')[0].trim().toLowerCase()
}

/** 状态带上**明示实际格式**（作者不能以为拿到的是 mp4） */
export function formatLabel(mime: string): string {
  const c = mimeContainer(mime)
  if (!c) return '浏览器默认'
  if (c.includes('mp4')) return 'MP4'
  if (c.includes('webm')) return 'WebM'
  if (c.includes('ogg')) return 'OGG'
  return c
}

/** 下载/上传用的扩展名 */
export function fileExtension(mime: string): string {
  const c = mimeContainer(mime)
  if (c.includes('mp4')) return 'mp4'
  if (c.includes('ogg')) return 'ogv'
  return 'webm'
}

/** 文件名主干：去掉文件系统不认的字符与控制字符，过长截断 */
export function sanitizeFileStem(name: string): string {
  const cleaned = Array.from(String(name ?? ''))
    .filter((ch) => ch.charCodeAt(0) >= 32) // 控制字符（\x00-\x1f）
    .join('')
    .replace(/[\\/:*?"<>|]/g, '-')
    .replace(/\s+/g, ' ')
    .trim()
    .replace(/^[.\s-]+|[.\s-]+$/g, '')
  return cleaned.slice(0, 60) || '口播录像'
}

function pad2(n: number): string {
  return String(n).padStart(2, '0')
}

/** `标题-YYYYMMDD-HHmm.webm`（规格原文的命名口径） */
export function recorderFileName(title: string, mime: string, at: Date = new Date()): string {
  const d = at instanceof Date && !Number.isNaN(at.getTime()) ? at : new Date()
  const stamp = `${d.getFullYear()}${pad2(d.getMonth() + 1)}${pad2(d.getDate())}-${pad2(d.getHours())}${pad2(d.getMinutes())}`
  return `${sanitizeFileStem(title)}-${stamp}.${fileExtension(mime)}`
}

// ---------------------------------------------------------------------------
// 状态机
// ---------------------------------------------------------------------------

/** idle(未开录) → countdown(3s 倒计时) → recording(录制中) → recorded(已录，待回放/下载/入库) */
export type RecorderState = 'idle' | 'countdown' | 'recording' | 'recorded'

export type RecorderEvent = 'arm' | 'countdown-done' | 'stop' | 'reset'

export function nextRecorderState(state: RecorderState, event: RecorderEvent): RecorderState {
  if (event === 'reset') return 'idle'
  switch (state) {
    case 'idle':
      return event === 'arm' ? 'countdown' : 'idle'
    case 'countdown':
      return event === 'countdown-done' ? 'recording' : 'countdown'
    case 'recording':
      return event === 'stop' ? 'recorded' : 'recording'
    case 'recorded':
      return state
    default:
      return 'idle'
  }
}

export interface SpaceActionInput {
  state: RecorderState
  /** 摄像头是否已就绪（未就绪时空格仍是「提词播放/暂停」） */
  cameraReady: boolean
}

/**
 * 空格键判据（R-215：「停止优先于播放/暂停」；R-214：空格=播放/暂停）。
 * - 倒计时 / 录制中 → `stop`（停止优先，避免录制时误暂停提词）
 * - 摄像头已就绪且空闲 → `record`（开始录制）
 * - 其余 → `toggle-play`（纯提词用法，键盘行为与 R-214 完全一致）
 */
export function spaceAction({ state, cameraReady }: SpaceActionInput): 'stop' | 'record' | 'toggle-play' {
  if (state === 'countdown' || state === 'recording') return 'stop'
  if (state === 'idle' && cameraReady) return 'record'
  return 'toggle-play'
}

// ---------------------------------------------------------------------------
// 安全阀与录后校验
// ---------------------------------------------------------------------------

/** 单次录制上限 5 分钟（内存与上传体积护栏） */
export const MAX_RECORDING_MS = 5 * 60 * 1000

export function shouldAutoStop(elapsedMs: number, limitMs: number = MAX_RECORDING_MS): boolean {
  return Number.isFinite(elapsedMs) && elapsedMs >= limitMs
}

/** 倒计时秒数可调（`-`/`+`，规格：默认 3s、Esc 可跳过） */
export const COUNTDOWN_DEFAULT = 3
export const COUNTDOWN_LIMITS = { min: 1, max: 10 } as const

export function clampCountdown(v: number): number {
  if (!Number.isFinite(v)) return COUNTDOWN_DEFAULT
  return Math.min(COUNTDOWN_LIMITS.max, Math.max(COUNTDOWN_LIMITS.min, Math.round(v)))
}

/**
 * 录后校验（规格：MP4 若「时长为 0 / 无法解码」→ 自动退回 WebM 重录）。
 * - 空块（`size <= 0`）→ 一律不合法；
 * - MP4：必须能读出一个 > 0 的有限时长（Chrome 的 mp4/avc1 缺陷就是这里读不出来）；
 * - WebM：浏览器常把时长报成 `Infinity`（未 seek 前），只看块大小，不误判。
 */
export interface RecordingCheck {
  ok: boolean
  reason: string
}

export function validateRecording(sizeBytes: number, durationSec: number | null, mime: string): RecordingCheck {
  if (!Number.isFinite(sizeBytes) || sizeBytes <= 0) return { ok: false, reason: '没有录到数据（文件为空）' }
  if (formatLabel(mime) === 'MP4') {
    if (durationSec == null || !Number.isFinite(durationSec) || durationSec <= 0) {
      return { ok: false, reason: 'MP4 文件无法解码（Chrome 已知缺陷）' }
    }
  }
  return { ok: true, reason: '' }
}

/** 有效的媒体时长（`Infinity`/`NaN`/`<=0` 都算「读不出来」） */
export function isUsableDuration(durationSec: number | null | undefined): boolean {
  return typeof durationSec === 'number' && Number.isFinite(durationSec) && durationSec > 0
}

// ---------------------------------------------------------------------------
// 设备选择（R-215：默认选内置麦克风 + Ace Pro UVC，设备选择器保留）
// ---------------------------------------------------------------------------

export interface DeviceLike {
  deviceId: string
  kind: string
  label: string
}

/** 相机默认优先：作者现场用的是 Insta360 Ace Pro（UVC） */
export const CAMERA_LABEL_PREFERENCES = [/insta360/i, /ace\s*pro/i, /uvc/i, /\busb\b/i, /webcam|camera|摄像头/i]
/** 麦克风默认优先：笔记本内置麦（正式录制再换 USB/无线麦接收器） */
export const MIC_LABEL_PREFERENCES = [/built-?in/i, /内建|内置/i, /macbook|imac/i, /internal/i, /default|默认/i]

/**
 * 从设备清单里挑默认设备：按偏好正则逐条匹配 label，命中即用；都不命中用第一个有 id 的；
 * 一个都没有 → `''`（交给浏览器默认设备）。
 */
export function pickPreferredDeviceId(
  devices: readonly DeviceLike[],
  kind: 'videoinput' | 'audioinput',
  preferred: readonly RegExp[] = kind === 'videoinput' ? CAMERA_LABEL_PREFERENCES : MIC_LABEL_PREFERENCES
): string {
  const pool = devices.filter((d) => d.kind === kind && d.deviceId)
  if (!pool.length) return ''
  for (const re of preferred) {
    const hit = pool.find((d) => re.test(d.label || ''))
    if (hit) return hit.deviceId
  }
  return pool[0].deviceId
}

/** getUserMedia 失败原因转成作者能看懂的话 */
export function mediaErrorMessage(err: unknown): string {
  const name = (err as { name?: string } | null)?.name || ''
  const map: Record<string, string> = {
    NotAllowedError: '浏览器拒绝了摄像头/麦克风权限，请在地址栏左侧的权限里允许后点【重试授权】',
    PermissionDeniedError: '浏览器拒绝了摄像头/麦克风权限，请允许后点【重试授权】',
    NotFoundError: '没有找到摄像头或麦克风（相机是否已切到 Webcam/UVC 模式？）',
    DevicesNotFoundError: '没有找到摄像头或麦克风（相机是否已切到 Webcam/UVC 模式？）',
    NotReadableError: '设备被其它程序占用（先关掉 Photo Booth / 会议软件），然后点【重试授权】',
    TrackStartError: '设备被其它程序占用（先关掉 Photo Booth / 会议软件），然后点【重试授权】',
    OverconstrainedError: '当前设备不支持 1080p 采集，请换一个视频设备'
  }
  if (name && map[name]) return map[name]
  const msg = (err as { message?: string } | null)?.message
  return msg ? `打开摄像头失败：${msg}` : '打开摄像头失败，请点【重试授权】'
}

