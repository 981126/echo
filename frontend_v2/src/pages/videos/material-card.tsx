import { forwardRef, memo, useMemo } from 'react'
import { motion } from 'framer-motion'
import { Play, RefreshCw, CheckCheck, Trash2, Split, Layers, BadgeCheck, LoaderCircle } from 'lucide-react'
import { cn } from '@/lib/utils'
import { platformName, fmtNum, fmtDate } from '@/lib/format'
import { EASE_OUT_EXPO, listReplace, softIn } from '@/lib/motion'
import { Badge } from '@/components/ui/badge'
import { Checkbox } from '@/components/ui/checkbox'
import { Progress } from '@/components/ui/progress'
import { Tooltip, TooltipContent, TooltipTrigger } from '@/components/ui/tooltip'
import type { CardItem, LatestStat } from './types'
import { CoverImage } from '@/components/ui/cover-image'
import type { CardTaskState } from './use-card-tasks'

const PLATFORM_DOT: Record<string, string> = {
  douyin: 'bg-[#fe2c55]',
  xiaohongshu: 'bg-[#ff2442]',
  bilibili: 'bg-[#00a1d6]'
}

/** R-260：卡片内逐平台展示的 5 项指标（顺序固定）。 */
const METRIC_COLS = [
  { key: 'plays', label: '播放' },
  { key: 'likes', label: '点赞' },
  { key: 'favorites', label: '收藏' },
  { key: 'comments', label: '评论' },
  { key: 'shares', label: '转发' }
] as const
type MetricKey = (typeof METRIC_COLS)[number]['key']

/** 平台展示顺序：抖音 → B站 → 小红书（与作者描述一致） */
const PLATFORM_ORDER = ['douyin', 'bilibili', 'xiaohongshu']

/** R-260：实测接口拿不到的指标——B 站（列表/详情）不返回转发、小红书不返回播放量；
 *  这两类字段该列一律置灰「-」；若个别作品确实有值（>0）仍照常展示。 */
const MISSING_METRICS: Record<string, MetricKey[]> = {
  bilibili: ['shares'],
  xiaohongshu: ['plays']
}

/** R-260：某平台某指标要展示的文本；`null` = 接口没有该数据 → 置灰「-」。 */
function metricText(platform: string, stat: LatestStat | null | undefined, key: MetricKey): string | null {
  if (!stat) return null
  const value = Number(stat[key] || 0)
  if ((MISSING_METRICS[platform] || []).includes(key)) return value > 0 ? fmtNum(value) : null
  // 抖音播放量：公开接口恒 0 视为未知（创作者中心/统计接口才可信）；未知且为 0 → 灰色「-」
  if (key === 'plays' && platform === 'douyin' && stat.plays_known === false && value === 0) return null
  return fmtNum(value)
}

interface MaterialCardProps {
  item: CardItem
  index: number
  /** R-179：来自后续批次的卡片（滚到底加载的）——用轻淡入，不做列表 stagger、不跳版 */
  append?: boolean
  /** R-199：属于「换一批结果」（切博主/改筛选查询）的新卡——等旧卡退场后再入场 */
  replace?: boolean
  selectMode: boolean
  selected: boolean
  task?: CardTaskState
  busy?: boolean
  onOpen: (it: CardItem) => void
  onToggle: (it: CardItem) => void
  onPlay: (it: CardItem) => void
  onSync: (it: CardItem) => void
  onConfirmTags: (it: CardItem) => void
  onDelete: (it: CardItem) => void
  onSplit: (it: CardItem) => void
}

/**
 * R-199 关键修复：**必须把 ref 透传到根 `motion.div`**。
 *
 * `AnimatePresence mode="popLayout"` 是靠给每个子元素挂 ref、量出它的盒子再把「正在退场的子元素」
 * 用 `position: absolute !important` 弹出文档流的（见 framer-motion `PopChild`）。原来这里是
 * `memo(function …)` 且没有 forwardRef → framer 量不到元素（宽度/高度为 0）→ **退场卡一直留在流里**，
 * 结果换批时那 20 张正在退场的卡仍占着前 5 行，新卡被挤到第 6–10 行（**屏幕外**）去播入场动画，
 * 等退场卡终于被移除，新卡「啪」地弹回可视区 —— 这就是「结果卡没有动画 / 入场一点都不明显」的真凶。
 */
const MaterialCardBase = forwardRef<HTMLDivElement, MaterialCardProps>(function MaterialCard(
  {
    item,
    index,
    selectMode,
    selected,
    task,
    busy,
    onOpen,
    onToggle,
    onPlay,
    onSync,
    onConfirmTags,
    onDelete,
    onSplit,
    append,
    replace
  },
  ref
) {
  const stats = item.cloudPosts.map((p) => p.latest_stat).filter(Boolean)
  const likes = stats.reduce((m, s) => Math.max(m, Number(s?.likes || 0)), 0)
  const knownPlays = stats.filter((s) => Boolean(s?.plays_known))
  const playsSource = knownPlays.length ? knownPlays : stats
  const plays = playsSource.reduce((m, s) => Math.max(m, Number(s?.plays || 0)), 0)
  const showPlays = knownPlays.length > 0 || plays > 0
  const syncing = !!task && task.progress < 100
  // R-260：逐平台指标行——同一平台取互动最高的一条；没有发布作品的平台不出现。
  const statRows = useMemo(() => {
    const best = new Map<string, LatestStat | null>()
    const score = (s: LatestStat | null | undefined) =>
      s ? Number(s.likes || 0) + Number(s.favorites || 0) + Number(s.comments || 0) + Number(s.shares || 0) : -1
    for (const post of item.cloudPosts) {
      if (!post.platform) continue
      if (!best.has(post.platform) || score(post.latest_stat) > score(best.get(post.platform))) {
        best.set(post.platform, post.latest_stat ?? null)
      }
    }
    const rank = (platform: string) => {
      const i = PLATFORM_ORDER.indexOf(platform)
      return i === -1 ? PLATFORM_ORDER.length : i
    }
    return [...best.entries()]
      .sort((a, b) => rank(a[0]) - rank(b[0]))
      .map(([platform, stat]) => ({ platform, stat }))
  }, [item.cloudPosts])
  const hasStatTable = statRows.length > 0
  // 大列表性能：前 40 张有入场动画，其余直接呈现（避免集体动画卡顿）；
  // 不再用 layout 动画（每次进度更新都会全量布局测量），改用 content-visibility 跳过屏外渲染。
  // R-179：分批加载后每批只有 20 张，入场动画只作用于「首批」；后续批次用 0.85→1 轻淡入（R-175：不能从 0 起步）
  // R-199：换一批结果时**逐格交接**——新卡的入场延迟 = 本格旧卡的退场延迟 + 退场时长 + 呼吸量；
  //        退场（老动画）严格保持原样：0.35s 淡出 + 缩到 0.94 + index×0.035 错峰扫过，
  //        append 卡沿用 softIn、40 张之后的卡沿用 0.15s。
  //        **新卡进场 = 退场倒着播（幅度拉大 + 回弹）**：从 `opacity 0 / fromScale 0.78` 显影长大回 1，
  //        节奏沿用退场的错峰，但放慢并用 backOut 过冲（0.8 → 冲过 1 → 落回），保证肉眼看得见。
  const animateEnter = !append && index < 40
  const replacing = !!replace && animateEnter
  const exitDelay = Math.min(index, listReplace.exit.maxItems) * listReplace.exit.stagger
  const enterDelay = exitDelay + listReplace.exit.duration + listReplace.enter.breathAfterExit
  // 老动画：退场沿用「这张卡原本的过渡规则」
  const baseTransition = append
    ? softIn
    : animateEnter
      ? { duration: listReplace.exit.duration, delay: exitDelay, ease: EASE_OUT_EXPO }
      : { duration: 0.15 }
  // 入场：换批时按「退场倒放 + 慢一点 + 过冲」来，其余情况与原来完全一致
  const enterTransition = replacing
    ? { duration: listReplace.enter.duration, delay: enterDelay, ease: listReplace.enter.ease }
    : baseTransition

  return (
    <motion.div
      ref={ref}
      initial={
        append
          ? { opacity: 0.85, y: 8 }
          : replacing
            ? { opacity: 0, scale: listReplace.enter.fromScale } // 退场的反向：更小、透明 → 长大、显影
            : animateEnter
              ? { opacity: 0, y: 18, scale: 0.97 }
              : false
      }
      animate={{ opacity: 1, y: 0, scale: 1 }}
      exit={{ opacity: 0, scale: listReplace.exit.scale, transition: baseTransition }}
      transition={enterTransition}
      whileHover={{ y: -4 }}
      style={{ contentVisibility: 'auto', containIntrinsicSize: 'auto 356px' } as React.CSSProperties}
      className={cn(
        'group relative overflow-hidden rounded-lg border bg-card shadow-[var(--shadow-card)] transition-colors',
        selected ? 'border-accent ring-2 ring-[var(--ring)]' : 'border-border'
      )}
    >
      {/* 封面 */}
      <div className="relative aspect-[4/3] cursor-pointer overflow-hidden bg-muted" onClick={() => (selectMode ? onToggle(item) : onPlay(item))}>
        <CoverImage
          // R-179：封面走缩略图；R-249：缩略图坏图回退原图，再失败用占位，避免裂图
          url={item.cover_url}
          alt={item.title}
          className="h-full w-full object-cover transition-transform duration-500 ease-out group-hover:scale-[1.04]"
          placeholder={
            <div className="flex h-full w-full items-center justify-center bg-gradient-to-br from-muted to-accent-soft">
              <span className="text-lg font-bold tracking-widest text-muted-foreground/50">ECHO</span>
            </div>
          }
        />

        {/* hover 播放按钮 */}
        {!selectMode && item.hasVideo && (
          <div className="absolute inset-0 flex items-center justify-center bg-black/0 opacity-0 transition-all duration-300 group-hover:bg-black/25 group-hover:opacity-100 max-md:opacity-100">
            <motion.span
              initial={false}
              className="flex h-11 w-11 items-center justify-center rounded-full bg-white/90 text-black shadow-lg"
            >
              <Play className="ml-0.5 h-5 w-5" fill="currentColor" />
            </motion.span>
          </div>
        )}

        {/* 角标行 */}
        <div className="absolute left-2 top-2 flex gap-1">
          {item.kind === 'cloud' ? (
            <Badge variant="secondary" className="bg-black/45 text-white border-transparent backdrop-blur-sm">
              云端
            </Badge>
          ) : (
            <Badge variant="secondary" className="bg-black/45 text-white border-transparent backdrop-blur-sm">
              本地
            </Badge>
          )}
          {item.merged > 1 && (
            <Badge variant="secondary" className="bg-black/45 text-white border-transparent backdrop-blur-sm">
              <Layers className="h-3 w-3" /> {item.merged} 平台
            </Badge>
          )}
          {item.is_ad && <Badge variant="warning" className="backdrop-blur-sm">广告</Badge>}
        </div>

        {/* 多选框 */}
        {selectMode && (
          <div className="absolute right-2 top-2 rounded-md bg-black/45 p-1 backdrop-blur-sm" onClick={(e) => e.stopPropagation()}>
            <Checkbox checked={selected} onCheckedChange={() => onToggle(item)} className="border-white/60 data-[state=checked]:border-accent" />
          </div>
        )}

        {/* 操作即时反馈（拆分/删除等快操作） */}
        {busy && !task && (
          <div className="absolute inset-0 z-10 flex items-center justify-center bg-black/45 backdrop-blur-[2px]">
            <LoaderCircle className="h-6 w-6 animate-spin text-white" />
          </div>
        )}

        {/* 同步进度覆盖层 */}
        {task && (
          <div className="absolute inset-0 flex flex-col items-center justify-center gap-2 bg-black/55 backdrop-blur-[2px]">
            {syncing ? <LoaderCircle className="h-5 w-5 animate-spin text-white" /> : <BadgeCheck className="h-5 w-5 text-success" />}
            <Progress value={task.progress} className="w-3/4 bg-white/20" />
            <span className="max-w-[85%] truncate text-xs md:text-[11px] text-white/90">{task.note}</span>
            <span className="tnum text-xs md:text-[10px] text-white/70">{Math.round(task.progress)}%</span>
          </div>
        )}
      </div>

      {/* 信息区 */}
      <div className="cursor-pointer p-3" onClick={() => (selectMode ? onToggle(item) : onOpen(item))}>
        <p className="line-clamp-2 text-[13px] font-medium leading-snug">{item.title}</p>

        {/* R-260：逐平台 播放/点赞/收藏/评论/转发（桌面端表格）；接口没有的字段置灰「-」 */}
        {hasStatTable && (
          <div className="mt-2 hidden md:block">
            <div className="flex items-center text-[10px] leading-none text-muted-foreground/60">
              <span className="w-12 shrink-0" />
              {METRIC_COLS.map((m) => (
                <span key={m.key} className="flex-1 text-right">
                  {m.label}
                </span>
              ))}
            </div>
            {statRows.map((row) => (
              <div key={row.platform} className="mt-1 flex items-center text-[10px] leading-none">
                <span className="flex w-12 shrink-0 items-center gap-1 text-muted-foreground">
                  <span
                    className={cn(
                      'h-1.5 w-1.5 shrink-0 rounded-full',
                      PLATFORM_DOT[row.platform] || 'bg-muted-foreground'
                    )}
                  />
                  <span className="truncate">{platformName(row.platform)}</span>
                </span>
                {METRIC_COLS.map((m) => {
                  const text = metricText(row.platform, row.stat, m.key)
                  return (
                    <span
                      key={m.key}
                      aria-label={`${platformName(row.platform)}${m.label}`}
                      className={cn(
                        'tnum flex-1 text-right',
                        text === null ? 'text-muted-foreground/40' : 'text-foreground/80'
                      )}
                    >
                      {text ?? '-'}
                    </span>
                  )
                })}
              </div>
            ))}
          </div>
        )}

        {/* 聚合行：移动端始终展示；桌面端只在没有逐平台指标（本地素材等）时展示 */}
        <div className={cn('mt-2 flex flex-wrap items-center gap-x-1.5 gap-y-0.5', hasStatTable && 'md:hidden')}>
          {item.platforms.map((p) => (
            <Tooltip key={p} delayDuration={0}>
              <TooltipTrigger asChild>
                <span className={cn('h-2 w-2 rounded-full', PLATFORM_DOT[p] || 'bg-muted-foreground')} />
              </TooltipTrigger>
              <TooltipContent>{platformName(p)}</TooltipContent>
            </Tooltip>
          ))}
          {showPlays && <span className="tnum text-xs md:text-[11px] text-muted-foreground">▶ {fmtNum(plays)}</span>}
          {likes > 0 && <span className="tnum text-xs md:text-[11px] text-muted-foreground">👍 {fmtNum(likes)}</span>}
        </div>

        <div className="mt-1.5 flex flex-wrap items-center gap-1">
          {item.tags.slice(0, 3).map((t) => (
            <span key={t} className="rounded-full bg-muted px-1.5 py-0.5 text-xs md:text-[10px] text-muted-foreground">
              {t}
            </span>
          ))}
          {item.tags.length > 3 && <span className="text-xs md:text-[10px] text-muted-foreground">+{item.tags.length - 3}</span>}
          <span className="ml-auto whitespace-nowrap text-xs md:text-[11px] text-muted-foreground">{fmtDate(item.date)}</span>
        </div>
      </div>

      {/* 操作行 */}
      {!selectMode && (
        <div className="flex flex-wrap items-center gap-0.5 border-t border-border px-2 py-1.5 md:flex-nowrap">
          <Tooltip delayDuration={0}>
            <TooltipTrigger asChild>
              <button onClick={() => onSync(item)} className="flex h-11 w-11 items-center justify-center rounded-md text-muted-foreground transition-colors hover:bg-muted hover:text-foreground cursor-pointer max-md:flex-1 md:h-7 md:w-7">
                <RefreshCw className="h-3.5 w-3.5" />
              </button>
            </TooltipTrigger>
            <TooltipContent>数据同步</TooltipContent>
          </Tooltip>
          {item.kind === 'local' && item.tags_confirmed === false && (
            <Tooltip delayDuration={0}>
              <TooltipTrigger asChild>
                <button onClick={() => onConfirmTags(item)} className="flex h-11 w-11 items-center justify-center rounded-md text-warning transition-colors hover:bg-muted cursor-pointer max-md:flex-1 md:h-7 md:w-7">
                  <CheckCheck className="h-3.5 w-3.5" />
                </button>
              </TooltipTrigger>
              <TooltipContent>确认标签</TooltipContent>
            </Tooltip>
          )}
          {item.kind === 'cloud' && item.type === 'work' && item.merged > 1 && (
            <Tooltip delayDuration={0}>
              <TooltipTrigger asChild>
                <button onClick={() => onSplit(item)} className="flex h-11 w-11 items-center justify-center rounded-md text-muted-foreground transition-colors hover:bg-muted hover:text-foreground cursor-pointer max-md:flex-1 md:h-7 md:w-7">
                  <Split className="h-3.5 w-3.5" />
                </button>
              </TooltipTrigger>
              <TooltipContent>拆分合并</TooltipContent>
            </Tooltip>
          )}
          <span className="hidden flex-1 md:block" />
          <Tooltip delayDuration={0}>
            <TooltipTrigger asChild>
              <button onClick={() => onDelete(item)} className="flex h-11 w-11 items-center justify-center rounded-md text-muted-foreground transition-colors hover:bg-[rgba(239,68,68,0.1)] hover:text-destructive cursor-pointer max-md:flex-1 md:h-7 md:w-7">
                <Trash2 className="h-3.5 w-3.5" />
              </button>
            </TooltipTrigger>
            <TooltipContent>删除</TooltipContent>
          </Tooltip>
        </div>
      )}
    </motion.div>
  )
})

/** popLayout 需要子元素可被 ref 量测（见上方说明），这里用 memo 包住 forwardRef 的结果 */
export const MaterialCard = memo(MaterialCardBase)
