import { describe, it, expect } from 'vitest'
import {
  COUNTDOWN_DEFAULT,
  MAX_RECORDING_MS,
  RECORDER_MIME_CANDIDATES,
  clampCountdown,
  fileExtension,
  formatLabel,
  isUsableDuration,
  mediaErrorMessage,
  mimeContainer,
  nextRecorderState,
  pickPreferredDeviceId,
  pickRecorderMime,
  recorderFileName,
  sanitizeFileStem,
  shouldAutoStop,
  spaceAction,
  validateRecording,
  type RecorderState
} from './recorder'

const MP4 = RECORDER_MIME_CANDIDATES[0]
const VP9 = RECORDER_MIME_CANDIDATES[1]
const VP8 = RECORDER_MIME_CANDIDATES[2]
const WEBM = RECORDER_MIME_CANDIDATES[3]

describe('pickRecorderMime / formatLabel（R-215 格式协商降级 + 明示实际格式）', () => {
  it('全支持时优先 MP4；逐个降级到 vp9 → vp8 → webm', () => {
    expect(pickRecorderMime(() => true)).toBe(MP4)
    expect(pickRecorderMime((t) => t !== MP4)).toBe(VP9)
    expect(pickRecorderMime((t) => t === VP8 || t === WEBM)).toBe(VP8)
    expect(pickRecorderMime((t) => t === WEBM)).toBe(WEBM)
  })

  it('全不支持 → 空串（交给浏览器默认，事后用 recorder.mimeType 兜底）', () => {
    expect(pickRecorderMime(() => false)).toBe('')
  })

  it('isTypeSupported 抛错当作不支持，不炸', () => {
    expect(
      pickRecorderMime((t) => {
        if (t === MP4) throw new Error('boom')
        return t === VP9
      })
    ).toBe(VP9)
  })

  it('状态带文案与扩展名：MP4 / WebM / 浏览器默认', () => {
    expect(formatLabel(MP4)).toBe('MP4')
    expect(formatLabel('video/webm;codecs=vp9,opus')).toBe('WebM')
    expect(formatLabel('video/webm')).toBe('WebM')
    expect(formatLabel('')).toBe('浏览器默认')
    expect(mimeContainer('video/webm;codecs="vp9,opus"')).toBe('video/webm')
    expect(fileExtension(MP4)).toBe('mp4')
    expect(fileExtension('')).toBe('webm')
  })
})

describe('sanitizeFileStem / recorderFileName（R-215 文件名 = 标题-时间戳）', () => {
  it('去掉文件系统不认的字符、压空白、空标题兜底', () => {
    expect(sanitizeFileStem('a/b:c*d?e"f<g>h|i')).toBe('a-b-c-d-e-f-g-h-i')
    expect(sanitizeFileStem('  多个   空格  ')).toBe('多个 空格')
    expect(sanitizeFileStem('')).toBe('口播录像')
    expect(sanitizeFileStem('///')).toBe('口播录像')
    expect(sanitizeFileStem('长'.repeat(200)).length).toBe(60)
  })

  it('文件名 = 标题-YYYYMMDD-HHmm.webm，扩展名跟随实际格式', () => {
    const at = new Date(2026, 8, 29, 9, 5) // 2026-09-29 09:05
    expect(recorderFileName('面试怎么讲薪资', VP9, at)).toBe('面试怎么讲薪资-20260929-0905.webm')
    expect(recorderFileName('求职/避坑', MP4, new Date(2026, 11, 1, 18, 30))).toBe('求职-避坑-20261201-1830.mp4')
  })
})

describe('nextRecorderState（R-215 录制状态机）', () => {
  it('idle → countdown → recording → recorded → reset → idle', () => {
    let s: RecorderState = 'idle'
    s = nextRecorderState(s, 'arm')
    expect(s).toBe('countdown')
    s = nextRecorderState(s, 'countdown-done')
    expect(s).toBe('recording')
    s = nextRecorderState(s, 'stop')
    expect(s).toBe('recorded')
    s = nextRecorderState(s, 'reset')
    expect(s).toBe('idle')
  })

  it('非法事件不改变状态（录制中重复 arm / 已录后再 stop 都无效）', () => {
    expect(nextRecorderState('recording', 'arm')).toBe('recording')
    expect(nextRecorderState('recorded', 'stop')).toBe('recorded')
    expect(nextRecorderState('countdown', 'stop')).toBe('countdown') // 倒计时靠 reset 收口
    expect(nextRecorderState('idle', 'countdown-done')).toBe('idle')
    expect(nextRecorderState('idle', 'reset')).toBe('idle')
  })
})

describe('spaceAction（R-215 空格：停止优先；未开摄像头时仍是 R-214 的播放/暂停）', () => {
  it('倒计时 / 录制中 → 停止（优先于播放暂停，避免录制时误暂停提词）', () => {
    expect(spaceAction({ state: 'countdown', cameraReady: true })).toBe('stop')
    expect(spaceAction({ state: 'recording', cameraReady: true })).toBe('stop')
  })

  it('摄像头就绪且空闲 → 开始录制', () => {
    expect(spaceAction({ state: 'idle', cameraReady: true })).toBe('record')
  })

  it('未开摄像头 / 已录完 → 提词播放暂停', () => {
    expect(spaceAction({ state: 'idle', cameraReady: false })).toBe('toggle-play')
    expect(spaceAction({ state: 'recorded', cameraReady: true })).toBe('toggle-play')
  })
})

describe('安全阀与倒计时（R-215 超 5 分钟自动停、倒计时可调）', () => {
  it('超过 5 分钟判自动停', () => {
    expect(MAX_RECORDING_MS).toBe(300000)
    expect(shouldAutoStop(299_000)).toBe(false)
    expect(shouldAutoStop(300_000)).toBe(true)
    expect(shouldAutoStop(Number.NaN)).toBe(false)
  })

  it('倒计时 1–10 秒，脏值回默认 3', () => {
    expect(COUNTDOWN_DEFAULT).toBe(3)
    expect(clampCountdown(0)).toBe(1)
    expect(clampCountdown(99)).toBe(10)
    expect(clampCountdown(Number.NaN)).toBe(3)
    expect(clampCountdown(4.4)).toBe(4)
  })
})

describe('validateRecording / isUsableDuration（R-215 MP4 损坏自动退回 WebM）', () => {
  it('空文件一律不合法', () => {
    expect(validateRecording(0, 10, VP9).ok).toBe(false)
    expect(validateRecording(0, 10, MP4).reason).toContain('空')
  })

  it('MP4 读不出时长 → 判损坏（Chrome 已知缺陷），提示退回 WebM', () => {
    expect(validateRecording(1024, 0, MP4).ok).toBe(false)
    expect(validateRecording(1024, Number.POSITIVE_INFINITY, MP4).ok).toBe(false)
    expect(validateRecording(1024, null, MP4).ok).toBe(false)
    expect(validateRecording(1024, 3.2, MP4).ok).toBe(true)
  })

  it('WebM 未 seek 前时长常为 Infinity，只看块大小不误判', () => {
    expect(validateRecording(2048, null, VP9).ok).toBe(true)
    expect(validateRecording(2048, Number.POSITIVE_INFINITY, WEBM).ok).toBe(true)
  })

  it('isUsableDuration 只认有限正数', () => {
    expect(isUsableDuration(3.2)).toBe(true)
    expect(isUsableDuration(0)).toBe(false)
    expect(isUsableDuration(Number.POSITIVE_INFINITY)).toBe(false)
    expect(isUsableDuration(null)).toBe(false)
    expect(isUsableDuration(undefined)).toBe(false)
  })
})

describe('设备选择与错误文案（R-215：默认内置麦 + Ace Pro UVC）', () => {
  const devices = [
    { deviceId: 'cam-generic', kind: 'videoinput', label: 'HD Webcam' },
    { deviceId: 'cam-ace', kind: 'videoinput', label: 'Insta360 Ace Pro' },
    { deviceId: 'mic-usb', kind: 'audioinput', label: 'USB Audio Device' },
    { deviceId: 'mic-builtin', kind: 'audioinput', label: 'MacBook Pro 麦克风' },
    { deviceId: '', kind: 'videoinput', label: '' }
  ]

  it('相机优先 Ace Pro / UVC，麦克风优先内置麦', () => {
    expect(pickPreferredDeviceId(devices, 'videoinput')).toBe('cam-ace')
    expect(pickPreferredDeviceId(devices, 'audioinput')).toBe('mic-builtin')
  })

  it('偏好都不命中 → 第一个有 id 的设备；清单为空 → 空串（交给浏览器默认）', () => {
    const other = [
      { deviceId: 'a', kind: 'videoinput', label: 'Cam A' },
      { deviceId: 'b', kind: 'videoinput', label: 'Cam B' }
    ]
    expect(pickPreferredDeviceId(other, 'videoinput')).toBe('a')
    expect(pickPreferredDeviceId([], 'videoinput')).toBe('')
    expect(pickPreferredDeviceId([{ deviceId: '', kind: 'videoinput', label: '' }], 'videoinput')).toBe('')
  })

  it('权限/占用/无设备都给明确中文文案（不让作者猜）', () => {
    expect(mediaErrorMessage({ name: 'NotAllowedError' })).toContain('权限')
    expect(mediaErrorMessage({ name: 'NotFoundError' })).toContain('Webcam')
    expect(mediaErrorMessage({ name: 'NotReadableError' })).toContain('占用')
    expect(mediaErrorMessage(new Error('boom'))).toContain('boom')
    expect(mediaErrorMessage(null)).toContain('重试授权')
  })
})
