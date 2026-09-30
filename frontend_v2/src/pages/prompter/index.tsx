// R-214 提词器 + R-215 内置网页录像（同一全屏页）
//
// 设计要点（依据 requirements/R-214-teleprompter.md / R-215-prompter-recorder.md）：
// - 顶层路由 `#/prompter/:draftId`，**不进 AppShell**（无导航/顶栏），真正全屏；`Esc` 回草稿列表。
// - 纯黑底暖白大字，正文 `max-width: 60ch` 居中、**首行贴屏幕上沿**（减小视线下移角）；
//   屏幕高度的 30% 处作为「读字基准线」，基准线所在段高亮（只换字色、无位移/无过渡动画）。
// - `requestAnimationFrame` 恒速推进（像素/秒），到底自动停；设置（字号/行距/速度/镜像）落 localStorage。
// - 录像：getUserMedia（默认 Ace Pro UVC + 内置麦）→ 格式协商降级并**明示实际格式** → 3s 倒计时 →
//   MediaRecorder 1s 分片 → 停止后回放/下载/存入素材库（复用既有 `POST /api/videos/upload`，后端零改动）。
// - 动效（R-175）：入场用 `softIn`（**不从 opacity:0 起步**）；正文区零动画；控制条 3s 无操作淡出；
//   录制中只保留「REC 红点呼吸 + 时长跳动」这类必要状态动效。

import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import { useNavigate, useParams } from 'react-router-dom'
import { motion } from 'framer-motion'
import {
  ArrowLeft,
  Camera,
  CameraOff,
  Captions,
  CircleStop,
  CirclePlay,
  Download,
  Eye,
  EyeOff,
  Keyboard,
  LoaderCircle,
  MonitorUp,
  Pause,
  Play,
  RotateCcw,
  Upload,
  Video
} from 'lucide-react'
import { apiJson, uploadFile } from '@/api/client'
import { Button } from '@/components/ui/button'
import { Select, SelectValue, SelectTrigger, SelectContent, SelectItem } from '@/components/ui/select'
import { toast } from '@/components/ui/toaster'
import { softIn } from '@/lib/motion'
import { cn } from '@/lib/utils'
import type { Draft } from '@/pages/drafts/types'
import {
  CONTROLS_IDLE_MS,
  advanceScroll,
  activeSegmentIndex,
  clamp,
  fmtClock,
  isAtEnd,
  manualStepPx,
  promptText,
  promptTiming,
  readPrompterSettings,
  readingLinePx,
  spokenCharCount,
  splitSegments,
  stepSetting,
  writePrompterSettings,
  type PrompterSettings,
  type SegmentBox
} from './prompter-text'
import {
  COUNTDOWN_DEFAULT,
  WEBM_FALLBACK_CANDIDATE,
  clampCountdown,
  formatLabel,
  isUsableDuration,
  mediaErrorMessage,
  mimeContainer,
  nextRecorderState,
  pickPreferredDeviceId,
  pickRecorderMime,
  recorderFileName,
  shouldAutoStop,
  spaceAction,
  validateRecording,
  type RecorderEvent,
  type RecorderState
} from './recorder'

/** 暖白（非纯白，避免眩光发灰）；高亮段更亮、其余段压暗 */
const TEXT_DIM = 'rgba(242,236,224,0.42)'
const TEXT_ACTIVE = '#fff8ea'

interface DeviceOption {
  deviceId: string
  label: string
}

export default function PrompterPage() {
  const { draftId } = useParams()
  const id = Number(draftId)
  const navigate = useNavigate()

  const [draft, setDraft] = useState<Draft | null>(null)
  const [loadError, setLoadError] = useState('')
  const [settings, setSettings] = useState<PrompterSettings>(() => readPrompterSettings())
  const [playing, setPlaying] = useState(false)
  const [elapsed, setElapsed] = useState(0)
  const [activeIdx, setActiveIdx] = useState(0)
  const [controlsVisible, setControlsVisible] = useState(true)
  const [helpOpen, setHelpOpen] = useState(false)
  const [viewportH, setViewportH] = useState(0)

  // 录像状态
  const [recState, setRecState] = useState<RecorderState>('idle')
  const [cameraError, setCameraError] = useState('')
  const [cameraReady, setCameraReady] = useState(false)
  const [videoOptions, setVideoOptions] = useState<DeviceOption[]>([])
  const [audioOptions, setAudioOptions] = useState<DeviceOption[]>([])
  const [videoDeviceId, setVideoDeviceId] = useState('')
  const [audioDeviceId, setAudioDeviceId] = useState('')
  const [mime, setMime] = useState('')
  const [countdownLeft, setCountdownLeft] = useState(0)
  const [previewOn, setPreviewOn] = useState(true)
  const [clipUrl, setClipUrl] = useState('')
  const [clipBlob, setClipBlob] = useState<Blob | null>(null)
  const [clipDuration, setClipDuration] = useState<number | null>(null)
  const [uploading, setUploading] = useState(false)
  const [uploadedId, setUploadedId] = useState<number | null>(null)

  // ---- refs：rAF 循环里的可变状态全部走 ref（避免闭包读到旧值 / 每帧重挂监听）----
  const scrollerRef = useRef<HTMLDivElement>(null)
  const contentRef = useRef<HTMLDivElement>(null)
  const previewVideoRef = useRef<HTMLVideoElement>(null)
  const playbackRef = useRef<HTMLVideoElement>(null)
  const segmentBoxesRef = useRef<SegmentBox[]>([])
  // 滚动位置的**权威值用浮点**：Chromium 会把小数 scrollTop 取整，直接读回 DOM 会把每帧 0.2px 的推进抹成 0（实测卡死不动）
  const scrollPosRef = useRef(0)
  const activeIdxRef = useRef(0)
  const settingsRef = useRef(settings)
  const playingRef = useRef(false)
  const elapsedRef = useRef(0)
  const notifiedRef = useRef(false)
  const hideTimerRef = useRef<number | null>(null)
  const streamRef = useRef<MediaStream | null>(null)
  const recorderRef = useRef<MediaRecorder | null>(null)
  const chunksRef = useRef<Blob[]>([])
  const recStateRef = useRef<RecorderState>('idle')
  const recStartRef = useRef(0)
  const activeMimeRef = useRef('')
  const forceWebmRef = useRef(false)
  const countdownTimerRef = useRef<number | null>(null)
  const countdownLeftRef = useRef(0)
  const countdownSecondsRef = useRef(COUNTDOWN_DEFAULT)
  const sessionRef = useRef(0)
  const videoDeviceRef = useRef('')
  const audioDeviceRef = useRef('')
  const clipBlobRef = useRef<Blob | null>(null)
  const draftRef = useRef<Draft | null>(null)
  const keyHandlerRef = useRef<(e: KeyboardEvent) => void>(() => {})
  const stopRef = useRef<(reason?: 'manual' | 'escape' | 'timeout') => void>(() => {})

  const text = useMemo(() => promptText(draft?.script || ''), [draft])
  const segments = useMemo(() => splitSegments(text), [text])
  const charCount = useMemo(() => spokenCharCount(text), [text])
  const timing = promptTiming(charCount, elapsed)
  const speedCps = (settings.speed * 30) / Math.max(1, settings.fontSize * settings.lineHeight)
  // 预览小窗是否真的占位（开摄像头 + 没被隐藏）
  const previewVisible = cameraReady && previewOn
  // 下载/入库的文件名 = 标题-YYYYMMDD-HHmm.ext（实际录制格式的扩展名）
  const fileName = useMemo(
    () => recorderFileName(draft?.title || '口播录像', activeMimeRef.current || mime),
    // eslint-disable-next-line react-hooks/exhaustive-deps
    [draft?.title, mime, recState, clipUrl]
  )

  // ---- 载入草稿（只读；提词页不改稿、不回写）----
  useEffect(() => {
    if (!Number.isFinite(id) || id <= 0) {
      setLoadError('草稿编号无效')
      return
    }
    let alive = true
    apiJson<Draft>(`/api/drafts/${id}`)
      .then((d) => {
        if (!alive) return
        setDraft(d)
        draftRef.current = d
        if (!promptText(d.script || '').trim()) setLoadError('这篇草稿还没有口播正文')
      })
      .catch((e) => alive && setLoadError((e as Error).message || '草稿加载失败'))
    return () => {
      alive = false
    }
  }, [id])

  // ---- 设置：改动即写 localStorage（刷新后沿用）----
  const applySettings = useCallback((updater: (s: PrompterSettings) => PrompterSettings) => {
    const next = updater(settingsRef.current)
    settingsRef.current = next
    setSettings(next)
    writePrompterSettings(next)
  }, [])

  // ---- 测量每段的盒子（正文容器坐标系），供「基准线所在段」判定 ----
  const measure = useCallback(() => {
    const content = contentRef.current
    if (!content) return
    const contentTop = content.getBoundingClientRect().top
    segmentBoxesRef.current = Array.from(content.querySelectorAll<HTMLElement>('[data-segment]')).map((node) => {
      const r = node.getBoundingClientRect()
      return { top: r.top - contentTop, height: r.height }
    })
  }, [])

  useEffect(() => {
    const raf = requestAnimationFrame(measure)
    return () => cancelAnimationFrame(raf)
  }, [measure, segments, settings.fontSize, settings.lineHeight, settings.mirrored, controlsVisible, viewportH, previewVisible])

  // 视口高度（底部占位 = 视口高 - 读字基准线，让最后一段正好停在基准线；resize 后重新量）
  useEffect(() => {
    const el = scrollerRef.current
    if (!el) return
    const sync = () => setViewportH(el.clientHeight)
    sync()
    const ro = new ResizeObserver(sync)
    ro.observe(el)
    return () => ro.disconnect()
    // draft 到位后才是真正的提词 DOM（加载态时 scrollerRef 还是 null，必须在挂载后再量一次）
  }, [draft])

  useEffect(() => {
    const onResize = () => measure()
    window.addEventListener('resize', onResize)
    return () => window.removeEventListener('resize', onResize)
  }, [measure])

  // ---- 主循环：恒速推进 + 已录时长 + 当前段高亮（一个 rAF 干完，避免多循环抢帧）----
  useEffect(() => {
    let raf = 0
    let last = performance.now()
    let lastPush = 0
    const tick = (now: number) => {
      const dt = now - last
      last = now
      const el = scrollerRef.current
      // 未播放时（作者滚轮/拖拽/↑↓ 找位置，或点检脚本直接改 scrollTop）一律以 DOM 为准，
      // 否则高亮会停在旧的浮点位置不动（实测：手动滚到底但高亮还在第一段）
      if (el && !playingRef.current && Math.abs(el.scrollTop - scrollPosRef.current) > 1) {
        scrollPosRef.current = el.scrollTop
      }
      if (playingRef.current && el) {
        const line = readingLinePx(settingsRef.current.fontSize, settingsRef.current.lineHeight)
        const boxes = segmentBoxesRef.current
        const natural = el.scrollHeight - el.clientHeight
        // 「念完」= 最后一段的上沿到达读字基准线（不是滚过尾部占位空白）
        const endTop = boxes.length ? Math.max(0, boxes[boxes.length - 1].top - line) : natural
        const limit = Math.max(0, Math.min(natural, endTop))
        // 用户中途手动滚（滚轮/拖拽/↑↓）→ 以 DOM 为准重新起算
        if (Math.abs(el.scrollTop - scrollPosRef.current) > 4) scrollPosRef.current = el.scrollTop
        scrollPosRef.current = advanceScroll(scrollPosRef.current, dt, settingsRef.current.speed, limit)
        const target = Math.round(scrollPosRef.current)
        if (Math.round(el.scrollTop) !== target) el.scrollTop = target
        // 稿子短到不用滚时不停表（作者自己按空格停），否则一到结尾就假装读完了
        if (limit > 0 && isAtEnd(scrollPosRef.current, limit)) {
          // 到底自动停（不假装还在读）
          playingRef.current = false
          setPlaying(false)
        }
      }
      if (recStateRef.current === 'recording' && recStartRef.current) {
        // 录制中：已录时长以录制起点为准（最接近真实录音长度）
        elapsedRef.current = (now - recStartRef.current) / 1000
        if (shouldAutoStop(now - recStartRef.current)) stopRef.current('timeout')
      } else if (playingRef.current) {
        elapsedRef.current += dt / 1000
      }
      if (now - lastPush > 200) {
        lastPush = now
        setElapsed(elapsedRef.current)
      }
      if (el && segmentBoxesRef.current.length) {
        // 读字基准线 = 屏幕上沿往下一个行高（作者读的就是最上面那行，视线不下移）
        const line = scrollPosRef.current + readingLinePx(settingsRef.current.fontSize, settingsRef.current.lineHeight)
        const idx = activeSegmentIndex(segmentBoxesRef.current, line)
        if (idx !== activeIdxRef.current) {
          activeIdxRef.current = idx
          setActiveIdx(idx)
        }
      }
      raf = requestAnimationFrame(tick)
    }
    raf = requestAnimationFrame(tick)
    return () => cancelAnimationFrame(raf)
  }, [])

  useEffect(() => {
    playingRef.current = playing
  }, [playing])
  useEffect(() => {
    recStateRef.current = recState
  }, [recState])
  useEffect(() => {
    settingsRef.current = settings
  }, [settings])
  useEffect(() => {
    draftRef.current = draft
  }, [draft])
  useEffect(() => {
    videoDeviceRef.current = videoDeviceId
  }, [videoDeviceId])
  useEffect(() => {
    audioDeviceRef.current = audioDeviceId
  }, [audioDeviceId])

  // ---- 到预估时长提示一次（不打断）----
  useEffect(() => {
    if (timing.totalSeconds > 0 && timing.remainingSeconds === 0 && !notifiedRef.current) {
      notifiedRef.current = true
      toast.info('已到预估时长（不打断，可以继续念）')
    }
  }, [timing.totalSeconds, timing.remainingSeconds])

  // ---- 控制条 3s 无操作淡出（录制回放/入库阶段常显，否则点不到按钮）----
  const scheduleHide = useCallback(() => {
    if (hideTimerRef.current) window.clearTimeout(hideTimerRef.current)
    hideTimerRef.current = window.setTimeout(() => setControlsVisible(false), CONTROLS_IDLE_MS)
  }, [])
  const wake = useCallback(() => {
    setControlsVisible(true)
    if (recStateRef.current !== 'recorded') scheduleHide()
  }, [scheduleHide])
  useEffect(() => {
    if (recState === 'recorded' || helpOpen) {
      if (hideTimerRef.current) window.clearTimeout(hideTimerRef.current)
      setControlsVisible(true)
      return
    }
    scheduleHide()
  }, [recState, helpOpen, scheduleHide])
  useEffect(() => () => {
    if (hideTimerRef.current) window.clearTimeout(hideTimerRef.current)
  }, [])
  useEffect(() => {
    const onMove = () => wake()
    window.addEventListener('mousemove', onMove)
    window.addEventListener('mousedown', onMove)
    window.addEventListener('wheel', onMove, { passive: true })
    return () => {
      window.removeEventListener('mousemove', onMove)
      window.removeEventListener('mousedown', onMove)
      window.removeEventListener('wheel', onMove)
    }
  }, [wake])

  // -------------------------------------------------------------------------
  // 播出控制
  // -------------------------------------------------------------------------
  const togglePlay = useCallback(() => {
    const el = scrollerRef.current
    if (!playingRef.current && el) {
      const line = readingLinePx(settingsRef.current.fontSize, settingsRef.current.lineHeight)
      const boxes = segmentBoxesRef.current
      const natural = el.scrollHeight - el.clientHeight
      const endTop = boxes.length ? Math.max(0, boxes[boxes.length - 1].top - line) : natural
      const limit = Math.max(0, Math.min(natural, endTop))
      if (limit > 0 && isAtEnd(el.scrollTop, limit)) {
        el.scrollTop = 0 // 已在结尾再按播放 → 从头开始
        scrollPosRef.current = 0
      }
    }
    const next = !playingRef.current
    playingRef.current = next
    setPlaying(next)
  }, [])

  const restart = useCallback(() => {
    const el = scrollerRef.current
    scrollPosRef.current = 0
    if (el) el.scrollTop = 0
    if (recStateRef.current !== 'recording') {
      elapsedRef.current = 0
      setElapsed(0)
      notifiedRef.current = false
    }
    activeIdxRef.current = 0
    setActiveIdx(0)
  }, [])

  const nudge = useCallback((dir: 1 | -1) => {
    playingRef.current = false
    setPlaying(false) // 手动找位置时先暂停（规格：暂停时用 ↑/↓ 手动）
    const el = scrollerRef.current
    if (!el) return
    const max = el.scrollHeight - el.clientHeight
    const next = clamp(el.scrollTop + dir * manualStepPx(settingsRef.current.fontSize, settingsRef.current.lineHeight), 0, Math.max(0, max))
    el.scrollTop = next
    scrollPosRef.current = next
  }, [])

  // -------------------------------------------------------------------------
  // 录像
  // -------------------------------------------------------------------------
  const refreshDeviceOptions = useCallback((devices: MediaDeviceInfo[]) => {
    const toOptions = (kind: MediaDeviceKind): DeviceOption[] =>
      devices
        .filter((d) => d.kind === kind && d.deviceId)
        .map((d, i) => ({
          deviceId: d.deviceId,
          label: d.label || `${kind === 'videoinput' ? '摄像头' : '麦克风'} ${i + 1}`
        }))
    const vids = toOptions('videoinput')
    const auds = toOptions('audioinput')
    setVideoOptions(vids)
    setAudioOptions(auds)
    if (!videoDeviceRef.current && vids.length) {
      const pick = pickPreferredDeviceId(devices.map((d) => ({ deviceId: d.deviceId, kind: d.kind, label: d.label })), 'videoinput')
      videoDeviceRef.current = pick
      setVideoDeviceId(pick)
    }
    if (!audioDeviceRef.current && auds.length) {
      const pick = pickPreferredDeviceId(devices.map((d) => ({ deviceId: d.deviceId, kind: d.kind, label: d.label })), 'audioinput')
      audioDeviceRef.current = pick
      setAudioDeviceId(pick)
    }
  }, [])

  const stopStream = useCallback(() => {
    streamRef.current?.getTracks().forEach((t) => t.stop())
    streamRef.current = null
    setCameraReady(false)
  }, [])

  const openCamera = useCallback(async (opts: { videoId?: string; audioId?: string } = {}) => {
    setCameraError('')
    if (typeof navigator === 'undefined' || !navigator.mediaDevices?.getUserMedia) {
      setCameraError('这个浏览器不支持摄像头采集（请用 Chrome/Edge）')
      return false
    }
    const videoId = opts.videoId ?? videoDeviceRef.current
    const audioId = opts.audioId ?? audioDeviceRef.current
    try {
      const stream = await navigator.mediaDevices.getUserMedia({
        video: videoId
          ? { deviceId: { exact: videoId }, width: 1920, height: 1080, frameRate: 30 }
          : { width: 1920, height: 1080, frameRate: 30 },
        audio: audioId
          ? { deviceId: { exact: audioId }, echoCancellation: false, noiseSuppression: false }
          : { echoCancellation: false, noiseSuppression: false }
      })
      streamRef.current?.getTracks().forEach((t) => t.stop())
      streamRef.current = stream
      setCameraReady(true)
      if (previewVideoRef.current) {
        previewVideoRef.current.srcObject = stream
        void previewVideoRef.current.play().catch(() => undefined)
      }
      const devices = await navigator.mediaDevices.enumerateDevices()
      refreshDeviceOptions(devices)
      // 授权后才知道真实标签：把实际用上的设备回填到选择器
      const used = stream.getVideoTracks()[0]?.getSettings().deviceId
      if (used) {
        videoDeviceRef.current = used
        setVideoDeviceId(used)
      }
      const usedAudio = stream.getAudioTracks()[0]?.getSettings().deviceId
      if (usedAudio) {
        audioDeviceRef.current = usedAudio
        setAudioDeviceId(usedAudio)
      }
      setMime(
        forceWebmRef.current
          ? WEBM_FALLBACK_CANDIDATE
          : pickRecorderMime((t) => typeof MediaRecorder !== 'undefined' && MediaRecorder.isTypeSupported(t))
      )
      return true
    } catch (err) {
      setCameraError(mediaErrorMessage(err))
      return false
    }
  }, [refreshDeviceOptions])

  const closeCamera = useCallback(() => {
    if (recStateRef.current === 'recording' || recStateRef.current === 'countdown') stopRef.current('manual')
    stopStream()
  }, [stopStream])

  const setRec = useCallback((next: RecorderState) => {
    recStateRef.current = next
    setRecState(next)
  }, [])
  const applyEvent = useCallback(
    (event: RecorderEvent) => setRec(nextRecorderState(recStateRef.current, event)),
    [setRec]
  )

  /** 录后校验 + 回放准备：块为空 / MP4 读不出时长 → 判失败，并按规格自动退回 WebM */
  const finalizeClip = useCallback(async (chunks: Blob[], usedMime: string) => {
    const type = mimeContainer(usedMime) || 'video/webm'
    const blob = new Blob(chunks, { type })
    const url = URL.createObjectURL(blob)
    const duration = await probeDuration(url)
    const check = validateRecording(blob.size, duration, usedMime)
    if (!check.ok) {
      URL.revokeObjectURL(url)
      setRec('idle')
      if (formatLabel(usedMime) === 'MP4') {
        forceWebmRef.current = true
        setMime(WEBM_FALLBACK_CANDIDATE)
        toast.warning(`${check.reason}，已自动切回 WebM，请重录`)
      } else {
        toast.error(`${check.reason}，请重录`)
      }
      return
    }
    setClipUrl((old) => {
      if (old) URL.revokeObjectURL(old)
      return url
    })
    clipBlobRef.current = blob
    setClipBlob(blob)
    setClipDuration(duration)
    setRec('recorded')
  }, [setRec])

  const beginRecording = useCallback(() => {
    const stream = streamRef.current
    if (!stream) {
      setCameraError('摄像头未就绪，请先点【开启摄像头】')
      setRec('idle')
      return
    }
    const chosen = forceWebmRef.current ? WEBM_FALLBACK_CANDIDATE : mime
    let recorder: MediaRecorder | null = null
    try {
      recorder = chosen ? new MediaRecorder(stream, { mimeType: chosen }) : new MediaRecorder(stream)
    } catch {
      try {
        recorder = new MediaRecorder(stream)
      } catch (err) {
        toast.error(`浏览器不支持录制：${(err as Error).message}`)
        setRec('idle')
        return
      }
    }
    const rec = recorder
    recorderRef.current = rec
    activeMimeRef.current = rec.mimeType || chosen || ''
    chunksRef.current = []
    // 会话号：重录/再次开始时作废旧回调（MediaRecorder 的 onstop 可能晚到）
    sessionRef.current += 1
    const session = sessionRef.current
    rec.ondataavailable = (ev: BlobEvent) => {
      if (session !== sessionRef.current) return
      if (ev.data && ev.data.size > 0) chunksRef.current.push(ev.data)
    }
    rec.onerror = () => {
      if (session !== sessionRef.current) return
      toast.error('录制中途出错，已停止（已录部分会尽量保留）')
      stopRef.current('manual')
    }
    rec.onstop = () => {
      if (session !== sessionRef.current) return
      const chunks = chunksRef.current
      chunksRef.current = []
      setPlaying(false)
      playingRef.current = false
      setRec('recorded') // 先落「已停录」形态（回放/校验进度另用 clipUrl 是否就绪表达）
      void finalizeClip(chunks, activeMimeRef.current || mime)
    }
    rec.start(1000) // 1s 分片：停止时最多丢不到 1s
    recStartRef.current = performance.now()
    elapsedRef.current = 0
    setElapsed(0)
    notifiedRef.current = false
    setUploadedId(null)
    // 规格：录制中提词自动匀速滚动
    playingRef.current = true
    setPlaying(true)
    setRec('recording')
  }, [finalizeClip, mime, setRec])

  const clearCountdown = useCallback(() => {
    if (countdownTimerRef.current) window.clearInterval(countdownTimerRef.current)
    countdownTimerRef.current = null
  }, [])

  const startCountdown = useCallback(async () => {
    if (recStateRef.current !== 'idle') return
    const ok = streamRef.current ? true : await openCamera()
    if (!ok) return
    const total = clampCountdown(countdownSecondsRef.current)
    countdownLeftRef.current = total
    setCountdownLeft(total)
    applyEvent('arm')
    clearCountdown()
    countdownTimerRef.current = window.setInterval(() => {
      countdownLeftRef.current -= 1
      if (countdownLeftRef.current <= 0) {
        clearCountdown()
        setCountdownLeft(0)
        beginRecording()
        return
      }
      setCountdownLeft(countdownLeftRef.current)
    }, 1000)
  }, [applyEvent, beginRecording, clearCountdown, openCamera])

  const stop = useCallback((reason: 'manual' | 'escape' | 'timeout' = 'manual') => {
    const state = recStateRef.current
    if (state === 'countdown') {
      clearCountdown()
      setCountdownLeft(0)
      setRec('idle')
      return
    }
    if (state !== 'recording') return
    if (reason === 'timeout') toast.warning('已录满 5 分钟，自动停止（本次录像仍可保存）')
    const rec = recorderRef.current
    if (rec && rec.state !== 'inactive') {
      try {
        rec.stop()
      } catch {
        setRec('recorded')
        void finalizeClip(chunksRef.current, activeMimeRef.current || mime)
      }
    } else {
      setRec('recorded')
      void finalizeClip(chunksRef.current, activeMimeRef.current || mime)
    }
    playingRef.current = false
    setPlaying(false)
  }, [clearCountdown, finalizeClip, mime, setRec])
  useEffect(() => {
    stopRef.current = stop
  }, [stop])

  const resetRecording = useCallback(() => {
    clearCountdown()
    clipBlobRef.current = null
    setClipBlob(null)
    setClipDuration(null)
    setUploadedId(null)
    setClipUrl((old) => {
      if (old) URL.revokeObjectURL(old)
      return ''
    })
    elapsedRef.current = 0
    setElapsed(0)
    notifiedRef.current = false
    applyEvent('reset')
  }, [applyEvent, clearCountdown])

  const uploadClip = useCallback(async () => {
    const blob = clipBlobRef.current
    if (!blob || uploading) return
    setUploading(true)
    try {
      const name = recorderFileName(draftRef.current?.title || '口播录像', activeMimeRef.current || mime)
      const file = new File([blob], name, { type: blob.type || 'video/webm' })
      const created = await uploadFile<{ id: number }>('/api/videos/upload', file)
      setUploadedId(created.id)
      toast.success('已存入素材库（未自动转写，可在素材库手动触发）')
    } catch (e) {
      toast.error(`${(e as Error).message}（已录内容不丢，可重试）`)
    } finally {
      setUploading(false)
    }
  }, [mime, uploading])

  const exit = useCallback(() => {
    stopRef.current('manual')
    stopStream()
    clearCountdown()
    navigate('/drafts')
  }, [clearCountdown, navigate, stopStream])

  /** 下载：`<a download>` 的程序化等价物（文件名 = 标题-YYYYMMDD-HHmm.ext） */
  const downloadClip = useCallback(() => {
    const url = clipUrl
    if (!url) return
    const a = document.createElement('a')
    a.href = url
    a.download = fileName
    document.body.appendChild(a)
    a.click()
    a.remove()
  }, [clipUrl, fileName])

  // 预览小窗挂载/切换时把流接上（openCamera 时 video 元素可能还没渲染出来）
  useEffect(() => {
    const v = previewVideoRef.current
    if (!v || !streamRef.current) return
    if (v.srcObject !== streamRef.current) v.srcObject = streamRef.current
    void v.play().catch(() => undefined)
  }, [cameraReady, previewOn])

  // 卸载时彻底收尾：停流、清定时器、释放 blob URL（避免内存增长）
  useEffect(
    () => () => {
      clearCountdown()
      streamRef.current?.getTracks().forEach((t) => t.stop())
      streamRef.current = null
    },
    [clearCountdown]
  )
  useEffect(
    () => () => {
      if (clipUrl) URL.revokeObjectURL(clipUrl)
    },
    [clipUrl]
  )

  // -------------------------------------------------------------------------
  // 快捷键（R-214：空格/↑↓/±/[]/M/R/Esc；R-215：录制中空格=停止且优先）
  // 处理函数每次渲染都换成最新闭包（ref 转发），监听只绑一次。
  // -------------------------------------------------------------------------
  useEffect(() => {
    keyHandlerRef.current = (e: KeyboardEvent) => {
      wake()
      const k = e.key
      if (k === 'Escape') {
        e.preventDefault()
        // 录制中/倒计时：exit 内部会先停止录制（规格：Esc=停止并退出），随后回草稿列表
        exit()
        return
      }
      if (k === ' ' || k === 'Spacebar') {
        e.preventDefault()
        const action = spaceAction({ state: recStateRef.current, cameraReady: !!streamRef.current })
        if (action === 'stop') stopRef.current('manual')
        else if (action === 'record') void startCountdown()
        else togglePlay()
        return
      }
      if (k === 'ArrowUp' || k === 'ArrowDown') {
        e.preventDefault()
        nudge(k === 'ArrowUp' ? -1 : 1)
        return
      }
      if (k === '+' || k === '=' || k === '-' || k === '_') {
        e.preventDefault()
        const dir: 1 | -1 = k === '+' || k === '=' ? 1 : -1
        // 倒计时中 ± 调倒计时秒数（规格），其余时候调字号
        if (recStateRef.current === 'countdown') {
          const next = clampCountdown(countdownSecondsRef.current + dir)
          countdownSecondsRef.current = next
          toast.info(`倒计时 ${next} 秒`)
        } else {
          applySettings((s) => stepSetting(s, 'fontSize', dir))
        }
        return
      }
      if (k === '[' || k === ']') {
        e.preventDefault()
        applySettings((s) => stepSetting(s, 'speed', k === ']' ? 1 : -1))
        return
      }
      if (k === 'm' || k === 'M') {
        e.preventDefault()
        applySettings((s) => ({ ...s, mirrored: !s.mirrored }))
        return
      }
      if (k === 'r' || k === 'R') {
        e.preventDefault()
        restart()
        return
      }
      if (k === '?') {
        e.preventDefault()
        setHelpOpen((v) => !v)
        setControlsVisible(true)
      }
    }
    return undefined
  })
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => keyHandlerRef.current(e)
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  }, [])

  // ---- 渲染 ----
  if (loadError) {
    return (
      <motion.div
        data-testid="prompter-error"
        initial={{ opacity: 0.9, y: 6 }}
        animate={{ opacity: 1, y: 0 }}
        transition={softIn}
        className="fixed inset-0 z-50 flex flex-col items-center justify-center gap-4 bg-black text-center text-[#f2ece0]"
      >
        <Captions className="h-8 w-8 opacity-70" />
        <p className="text-lg">{loadError}</p>
        <Button variant="secondary" size="sm" onClick={() => navigate('/drafts')}>
          <ArrowLeft className="h-4 w-4" /> 回草稿列表
        </Button>
      </motion.div>
    )
  }

  if (!draft) {
    return (
      <div data-testid="prompter-loading" className="fixed inset-0 z-50 flex items-center justify-center bg-black text-[#f2ece0]">
        <LoaderCircle className="h-6 w-6 animate-spin" />
      </div>
    )
  }

  const recLabel = formatLabel(activeMimeRef.current || mime)

  return (
    // R-175：入场只做极轻的一段（0.9 → 1 + y6），**不从 opacity:0 起步**；正文区零动画
    <motion.div
      data-testid="prompter-root"
      data-state={recState}
      data-mirrored={settings.mirrored ? '1' : '0'}
      data-font-size={settings.fontSize}
      data-speed={settings.speed}
      initial={{ opacity: 0.9, y: 6 }}
      animate={{ opacity: 1, y: 0 }}
      transition={softIn}
      className="fixed inset-0 z-50 select-none overflow-hidden bg-black text-[#f2ece0]"
    >
      {/* 提词正文：首行贴屏幕上沿；底部占位让最后一段正好停在读字基准线；
          预览小窗打开时右侧留出空带（R-215：小窗不遮挡正文） */}
      <div
        ref={scrollerRef}
        data-testid="prompter-scroll"
        className="absolute inset-0 overflow-y-auto overflow-x-hidden [scrollbar-width:none] [&::-webkit-scrollbar]:hidden"
        style={{ paddingLeft: 24, paddingRight: previewVisible ? 316 : 24 }}
      >
        <div
          ref={contentRef}
          data-testid="prompter-content"
          className="w-full"
          style={{
            paddingTop: 10,
            // 底部占位：滚到底时最后一段的上沿正好落在读字基准线上（=「全部念完」）
            paddingBottom: Math.max(0, viewportH - readingLinePx(settings.fontSize, settings.lineHeight))
          }}
        >
          <div
            data-testid="prompter-text"
            className="mx-auto"
            style={{
              // 30em（1em = 一个中文字宽）≈ 每行 30 字，与 prompter-text 的 CHARS_PER_LINE 口径一致
              maxWidth: '30em',
              fontSize: settings.fontSize,
              lineHeight: settings.lineHeight,
              transform: settings.mirrored ? 'scaleX(-1)' : 'none',
              transition: 'none'
            }}
          >
            {segments.map((seg) => (
              <p
                key={seg.index}
                data-segment={seg.index}
                data-active={seg.index === activeIdx ? '1' : '0'}
                style={{
                  color: seg.index === activeIdx ? TEXT_ACTIVE : TEXT_DIM,
                  whiteSpace: 'pre-wrap',
                  margin: 0,
                  marginBottom: '0.5em',
                  transition: 'none'
                }}
              >
                {seg.text}
              </p>
            ))}
          </div>
        </div>
      </div>

      {/* 倒计时覆盖层（必要状态动效；不从 opacity:0 起步） */}
      {recState === 'countdown' && (
        <motion.div
          data-testid="prompter-countdown"
          initial={{ opacity: 0.85 }}
          animate={{ opacity: 1 }}
          transition={softIn}
          className="pointer-events-none absolute inset-0 z-30 flex flex-col items-center justify-center gap-3 bg-black/45"
        >
          <motion.span
            key={countdownLeft}
            initial={{ opacity: 0.7, scale: 0.92 }}
            animate={{ opacity: 1, scale: 1 }}
            transition={softIn}
            className="tnum text-[18vh] font-semibold leading-none"
          >
            {Math.max(1, countdownLeft)}
          </motion.span>
          <span className="text-sm opacity-70">空格/点按可取消 · `-`/`+` 调秒数</span>
        </motion.div>
      )}

      {/* 录制状态带（右上角，不挡读字基准线） */}
      <div className="pointer-events-none absolute right-4 top-4 z-20 flex flex-col items-end gap-2">
        {recState === 'recording' && (
          <span
            data-testid="prompter-rec-chip"
            className="flex items-center gap-2 rounded-full bg-black/70 px-3 py-1.5 text-xs font-medium backdrop-blur"
          >
            <span className="h-2.5 w-2.5 animate-pulse rounded-full bg-red-500" />
            REC {fmtClock(elapsed)} · {recLabel}
          </span>
        )}
        {recState !== 'recording' && recState !== 'idle' && (
          <span className="rounded-full bg-black/70 px-3 py-1.5 text-xs backdrop-blur">
            {recState === 'countdown' ? `倒计时 ${Math.max(1, countdownLeft)}s` : `已录 ${fmtClock(clipDuration ?? elapsed)} · ${recLabel}`}
          </span>
        )}
        {cameraError && (
          <span data-testid="prompter-camera-error" className="max-w-xs rounded-lg bg-destructive/90 px-3 py-2 text-xs">
            {cameraError}
          </span>
        )}
      </div>

      {/* 实时预览小窗（右下角，位于读字基准线以下，不遮挡正文；可开关） */}
      {previewVisible && (
        <motion.div
          data-testid="prompter-preview"
          initial={{ opacity: 0.85, y: 8 }}
          animate={{ opacity: 1, y: 0 }}
          transition={softIn}
          className="absolute bottom-24 right-4 z-20 w-[min(280px,32vw)] overflow-hidden rounded-xl border border-white/15 bg-black/80 shadow-lg"
        >
          <video ref={previewVideoRef} autoPlay muted playsInline className="aspect-video w-full bg-black object-cover" />
          <div className="flex items-center justify-between px-2 py-1 text-[10px] opacity-70">
            <span>实时预览</span>
            <button type="button" className="cursor-pointer hover:opacity-100" onClick={() => setPreviewOn(false)}>
              隐藏
            </button>
          </div>
        </motion.div>
      )}

      {/* 录后回放/下载/入库面板 */}
      {recState === 'recorded' && (
        <motion.div
          data-testid="prompter-playback"
          data-duration={clipDuration ?? ''}
          initial={{ opacity: 0.85, y: 10 }}
          animate={{ opacity: 1, y: 0 }}
          transition={softIn}
          className="absolute bottom-28 left-1/2 z-30 w-[min(680px,92vw)] -translate-x-1/2 space-y-2 rounded-2xl border border-white/15 bg-black/85 p-3 backdrop-blur"
        >
          {clipUrl ? (
            <video ref={playbackRef} src={clipUrl} controls playsInline className="max-h-[32vh] w-full rounded-lg bg-black" />
          ) : (
            <div className="flex h-24 items-center justify-center gap-2 text-sm opacity-80">
              <LoaderCircle className="h-4 w-4 animate-spin" /> 正在校验录像（MP4 若损坏会自动退回 WebM）…
            </div>
          )}
          <div className="flex flex-wrap items-center gap-2 text-xs">
            <span className="opacity-80">
              已录 {fmtClock(clipDuration ?? elapsed)} · {recLabel} · {clipBlob ? `${(clipBlob.size / 1024 / 1024).toFixed(1)}MB` : '校验中'}
            </span>
            <span className="flex-1" />
            <Button variant="secondary" size="sm" onClick={resetRecording}>
              <RotateCcw className="h-3.5 w-3.5" /> 重录
            </Button>
            <Button
              variant="secondary"
              size="sm"
              disabled={!clipUrl}
              data-testid="prompter-download"
              data-filename={fileName}
              onClick={downloadClip}
            >
              <Download className="h-3.5 w-3.5" /> 下载
            </Button>
            {uploadedId ? (
              <Button size="sm" data-testid="prompter-goto-videos" onClick={() => navigate('/videos')}>
                <Video className="h-3.5 w-3.5" /> 去素材库
              </Button>
            ) : (
              <Button size="sm" data-testid="prompter-upload" disabled={!clipBlob || uploading} onClick={() => void uploadClip()}>
                {uploading ? <LoaderCircle className="h-3.5 w-3.5 animate-spin" /> : <Upload className="h-3.5 w-3.5" />}
                {uploading ? '入库中…' : '存入素材库'}
              </Button>
            )}
          </div>
          {uploadedId && (
            <p className="text-[11px] text-accent" data-testid="prompter-uploaded">
              已入库（素材 #{uploadedId}）· 按 R-033 不自动转写，可在素材库手动触发语音转文字
            </p>
          )}
        </motion.div>
      )}

      {/* 底部控制条：3s 无操作淡出（只改透明度，不改变布局 → 正文不跳） */}
      <motion.div
        data-testid="prompter-controls"
        data-visible={controlsVisible ? '1' : '0'}
        animate={{ opacity: controlsVisible ? 1 : 0 }}
        transition={{ duration: 0.2 }}
        className={cn(
          'absolute bottom-0 left-0 right-0 z-40 border-t border-white/10 bg-black/80 backdrop-blur',
          controlsVisible ? '' : 'pointer-events-none'
        )}
      >
        <div className="mx-auto flex w-full max-w-[1400px] flex-wrap items-center gap-x-3 gap-y-2 px-4 py-2.5 text-xs">
          <Button variant="ghost" size="sm" className="text-[#f2ece0] hover:bg-white/10" onClick={exit} data-testid="prompter-back">
            <ArrowLeft className="h-3.5 w-3.5" /> 退出 (Esc)
          </Button>
          <Button variant="secondary" size="sm" onClick={togglePlay} data-testid="prompter-play">
            {playing ? <Pause className="h-3.5 w-3.5" /> : <Play className="h-3.5 w-3.5" />}
            {playing ? '暂停' : '播放'} (空格)
          </Button>
          <Button variant="ghost" size="sm" className="text-[#f2ece0] hover:bg-white/10" onClick={restart}>
            <RotateCcw className="h-3.5 w-3.5" /> 回到开头 (R)
          </Button>

          <Divider />
          <Stepper
            label="字号"
            value={String(settings.fontSize)}
            onMinus={() => applySettings((s) => stepSetting(s, 'fontSize', -1))}
            onPlus={() => applySettings((s) => stepSetting(s, 'fontSize', 1))}
          />
          <Stepper
            label="行距"
            value={settings.lineHeight.toFixed(1)}
            onMinus={() => applySettings((s) => stepSetting(s, 'lineHeight', -1))}
            onPlus={() => applySettings((s) => stepSetting(s, 'lineHeight', 1))}
          />
          <Stepper
            label={`速度 [ ]`}
            value={`${settings.speed}px/s ≈ ${speedCps.toFixed(1)}字/秒`}
            onMinus={() => applySettings((s) => stepSetting(s, 'speed', -1))}
            onPlus={() => applySettings((s) => stepSetting(s, 'speed', 1))}
          />
          <Button
            variant={settings.mirrored ? 'default' : 'ghost'}
            size="sm"
            className={settings.mirrored ? '' : 'text-[#f2ece0] hover:bg-white/10'}
            onClick={() => applySettings((s) => ({ ...s, mirrored: !s.mirrored }))}
            data-testid="prompter-mirror"
          >
            <Eye className="h-3.5 w-3.5" /> 镜像 (M)
          </Button>

          <Divider />
          <span className="tnum" data-testid="prompter-clock" data-elapsed={elapsed} data-remaining={timing.remainingSeconds} data-total={timing.totalSeconds}>
            已录 {fmtClock(elapsed)} · 剩余 {fmtClock(timing.remainingSeconds)} · 全长 {fmtClock(timing.totalSeconds)}
          </span>
          <span className="opacity-60">第 {activeIdx + 1}/{segments.length} 段</span>

          <Divider />
          {!cameraReady ? (
            <>
              <Button variant="secondary" size="sm" onClick={() => void openCamera()} data-testid="prompter-camera-on">
                <Camera className="h-3.5 w-3.5" /> {cameraError ? '重试授权' : '开启摄像头'}
              </Button>
              {cameraError && (
                <Button
                  variant="ghost"
                  size="sm"
                  className="text-[#f2ece0] hover:bg-white/10"
                  onClick={() => void openCamera()}
                  data-testid="prompter-camera-retry"
                >
                  <MonitorUp className="h-3.5 w-3.5" /> 重试授权
                </Button>
              )}
            </>
          ) : (
            <>
              <Button
                size="sm"
                variant={recState === 'recording' ? 'destructive' : 'default'}
                onClick={() => (recState === 'recording' || recState === 'countdown' ? stop('manual') : void startCountdown())}
                data-testid="prompter-record"
              >
                {recState === 'recording' ? <CircleStop className="h-3.5 w-3.5" /> : <CirclePlay className="h-3.5 w-3.5" />}
                {recState === 'recording' ? '停止录制 (空格)' : recState === 'countdown' ? '取消倒计时' : '开始录制 (空格)'}
              </Button>
              <span className="rounded bg-white/10 px-2 py-0.5" data-testid="prompter-format">
                格式 {recLabel}
              </span>
              <label className="flex items-center gap-1">
                视频
                <Select
                  value={videoDeviceId || 'default'}
                  onValueChange={(v) => {
                    const next = v === 'default' ? '' : v
                    videoDeviceRef.current = next
                    setVideoDeviceId(next)
                    void openCamera({ videoId: next })
                  }}
                >
                  <SelectTrigger className="h-7 w-[160px] text-[11px]" data-testid="prompter-video-device">
                    <SelectValue placeholder="默认摄像头" />
                  </SelectTrigger>
                  <SelectContent>
                    <SelectItem value="default">默认摄像头</SelectItem>
                    {videoOptions.map((d) => (
                      <SelectItem key={d.deviceId} value={d.deviceId}>
                        {d.label}
                      </SelectItem>
                    ))}
                  </SelectContent>
                </Select>
              </label>
              <label className="flex items-center gap-1">
                麦克风
                <Select
                  value={audioDeviceId || 'default'}
                  onValueChange={(v) => {
                    const next = v === 'default' ? '' : v
                    audioDeviceRef.current = next
                    setAudioDeviceId(next)
                    void openCamera({ audioId: next })
                  }}
                >
                  <SelectTrigger className="h-7 w-[140px] text-[11px]" data-testid="prompter-audio-device">
                    <SelectValue placeholder="默认麦克风" />
                  </SelectTrigger>
                  <SelectContent>
                    <SelectItem value="default">默认麦克风</SelectItem>
                    {audioOptions.map((d) => (
                      <SelectItem key={d.deviceId} value={d.deviceId}>
                        {d.label}
                      </SelectItem>
                    ))}
                  </SelectContent>
                </Select>
              </label>
              <Button variant="ghost" size="sm" className="text-[#f2ece0] hover:bg-white/10" onClick={() => setPreviewOn((v) => !v)}>
                {previewOn ? <EyeOff className="h-3.5 w-3.5" /> : <Eye className="h-3.5 w-3.5" />}
                {previewOn ? '隐藏预览' : '显示预览'}
              </Button>
              <Button variant="ghost" size="sm" className="text-[#f2ece0] hover:bg-white/10" onClick={closeCamera}>
                <CameraOff className="h-3.5 w-3.5" /> 关闭摄像头
              </Button>
            </>
          )}
          {cameraReady && recState === 'idle' && (
            <Button variant="ghost" size="sm" className="text-[#f2ece0] hover:bg-white/10" onClick={() => void openCamera()} title="换设备后重新授权">
              <MonitorUp className="h-3.5 w-3.5" /> 重试授权
            </Button>
          )}
          <span className="flex-1" />
          <Button variant="ghost" size="sm" className="text-[#f2ece0] hover:bg-white/10" onClick={() => setHelpOpen((v) => !v)} data-testid="prompter-help">
            <Keyboard className="h-3.5 w-3.5" /> 快捷键 (?)
          </Button>
        </div>

        {helpOpen && (
          <motion.div
            initial={{ opacity: 0.85, y: 6 }}
            animate={{ opacity: 1, y: 0 }}
            transition={softIn}
            className="border-t border-white/10 px-4 py-2 text-[11px] leading-relaxed opacity-80"
            data-testid="prompter-help-panel"
          >
            空格 播放/暂停（开摄像头后=开始/停止录制，录制中空格=停止） · ↑/↓ 手动滚动 · +/- 字号（倒计时中调秒数） ·
            [ / ] 滚动速度 · M 镜像 · R 回到开头 · Esc 退出 · ? 快捷键
          </motion.div>
        )}
      </motion.div>
    </motion.div>
  )
}

function Divider() {
  return <span className="hidden h-5 w-px bg-white/15 sm:block" />
}

function Stepper({
  label,
  value,
  onMinus,
  onPlus
}: {
  label: string
  value: string
  onMinus: () => void
  onPlus: () => void
}) {
  return (
    <span className="flex items-center gap-1">
      <span className="opacity-70">{label}</span>
      <Button variant="ghost" size="sm" className="h-7 w-7 p-0 text-[#f2ece0] hover:bg-white/10" onClick={onMinus}>
        −
      </Button>
      <span className="tnum min-w-6 text-center">{value}</span>
      <Button variant="ghost" size="sm" className="h-7 w-7 p-0 text-[#f2ece0] hover:bg-white/10" onClick={onPlus}>
        +
      </Button>
    </span>
  )
}

/**
 * 读出媒体时长（WebM 在未 seek 前 `duration` 常是 `Infinity`——用大步 seek 逼出真实值）。
 * 读不出来返回 `null`（MP4 走此路径即判「无法解码」，按 R-215 退回 WebM）。
 */
function probeDuration(url: string): Promise<number | null> {
  return new Promise((resolve) => {
    if (typeof document === 'undefined') {
      resolve(null)
      return
    }
    const v = document.createElement('video')
    v.preload = 'metadata'
    v.muted = true
    let settled = false
    const finish = (d: number | null) => {
      if (settled) return
      settled = true
      window.clearTimeout(timer)
      v.removeAttribute('src')
      try {
        v.load()
      } catch {
        /* ignore */
      }
      resolve(d)
    }
    const timer = window.setTimeout(() => finish(isUsableDuration(v.duration) ? v.duration : null), 4000)
    v.onloadedmetadata = () => {
      if (isUsableDuration(v.duration)) {
        finish(v.duration)
        return
      }
      try {
        v.currentTime = 1e101
      } catch {
        finish(null)
      }
    }
    v.ontimeupdate = () => {
      if (isUsableDuration(v.duration)) finish(v.duration)
    }
    v.onerror = () => finish(null)
    v.src = url
  })
}
