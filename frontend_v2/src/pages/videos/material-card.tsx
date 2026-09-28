import { memo } from 'react'
import { motion } from 'framer-motion'
import { Play, RefreshCw, CheckCheck, Trash2, Split, Layers, BadgeCheck, LoaderCircle } from 'lucide-react'
import { cn } from '@/lib/utils'
import { platformName, fmtNum, fmtDate } from '@/lib/format'
import { EASE_OUT_EXPO, listReplace, softIn } from '@/lib/motion'
import { Badge } from '@/components/ui/badge'
import { Checkbox } from '@/components/ui/checkbox'
import { Progress } from '@/components/ui/progress'
import { Tooltip, TooltipContent, TooltipTrigger } from '@/components/ui/tooltip'
import type { CardItem } from './types'
import { coverThumb } from './types'
import type { CardTaskState } from './use-card-tasks'

const PLATFORM_DOT: Record<string, string> = {
  douyin: 'bg-[#fe2c55]',
  xiaohongshu: 'bg-[#ff2442]',
  bilibili: 'bg-[#00a1d6]'
}

export const MaterialCard = memo(function MaterialCard({
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
}: {
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
}) {
  const stats = item.cloudPosts.map((p) => p.latest_stat).filter(Boolean)
  const likes = stats.reduce((m, s) => Math.max(m, Number(s?.likes || 0)), 0)
  const syncing = !!task && task.progress < 100
  // 大列表性能：前 40 张有入场动画，其余直接呈现（避免集体动画卡顿）；
  // 不再用 layout 动画（每次进度更新都会全量布局测量），改用 content-visibility 跳过屏外渲染。
  // R-179：分批加载后每批只有 20 张，入场动画只作用于「首批」；后续批次用 0.85→1 轻淡入（R-175：不能从 0 起步）
  // R-199：换一批结果时**逐格交接**——新卡的入场延迟 = 本格旧卡的退场延迟 + 退场时长 + 呼吸量；
  //        退场（老动画）严格保持原样：0.35s 淡出 + 缩到 0.94 + index×0.035 错峰扫过，
  //        append 卡沿用 softIn、40 张之后的卡沿用 0.15s。
  const animateEnter = !append && index < 40
  const exitDelay = Math.min(index, listReplace.exit.maxItems) * listReplace.exit.stagger
  const enterDelay = exitDelay + listReplace.exit.duration + listReplace.enter.breathAfterExit
  // 老动画：退场沿用「这张卡原本的过渡规则」
  const baseTransition = append
    ? softIn
    : animateEnter
      ? { duration: listReplace.exit.duration, delay: exitDelay, ease: EASE_OUT_EXPO }
      : { duration: 0.15 }
  // 入场：换批时等本格旧卡退完再飞入，其余情况与原来完全一致
  const enterTransition = replace && animateEnter ? { duration: listReplace.enter.duration, delay: enterDelay, ease: EASE_OUT_EXPO } : baseTransition

  return (
    <motion.div
      initial={append ? { opacity: 0.85, y: 8 } : animateEnter ? { opacity: 0, y: 18, scale: 0.97 } : false}
      animate={{ opacity: 1, y: 0, scale: 1 }}
      exit={{ opacity: 0, scale: listReplace.exit.scale, transition: baseTransition }}
      transition={enterTransition}
      whileHover={{ y: -4 }}
      style={{ contentVisibility: 'auto', containIntrinsicSize: 'auto 300px' } as React.CSSProperties}
      className={cn(
        'group relative overflow-hidden rounded-lg border bg-card shadow-[var(--shadow-card)] transition-colors',
        selected ? 'border-accent ring-2 ring-[var(--ring)]' : 'border-border'
      )}
    >
      {/* 封面 */}
      <div className="relative aspect-[4/3] cursor-pointer overflow-hidden bg-muted" onClick={() => (selectMode ? onToggle(item) : onPlay(item))}>
        {item.cover_url ? (
          <img
            // R-179：封面走缩略图（原图平均 191KB、首屏 20 张曾要 13MB → 缩图后 ~0.6MB）
            src={coverThumb(item.cover_url, 400)}
            alt={item.title}
            loading="lazy"
            referrerPolicy="no-referrer"
            className="h-full w-full object-cover transition-transform duration-500 ease-out group-hover:scale-[1.04]"
          />
        ) : (
          <div className="flex h-full w-full items-center justify-center bg-gradient-to-br from-muted to-accent-soft">
            <span className="text-lg font-bold tracking-widest text-muted-foreground/50">ECHO</span>
          </div>
        )}

        {/* hover 播放按钮 */}
        {!selectMode && item.hasVideo && (
          <div className="absolute inset-0 flex items-center justify-center bg-black/0 opacity-0 transition-all duration-300 group-hover:bg-black/25 group-hover:opacity-100">
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
            <span className="max-w-[85%] truncate text-[11px] text-white/90">{task.note}</span>
            <span className="tnum text-[10px] text-white/70">{Math.round(task.progress)}%</span>
          </div>
        )}
      </div>

      {/* 信息区 */}
      <div className="cursor-pointer p-3" onClick={() => (selectMode ? onToggle(item) : onOpen(item))}>
        <p className="line-clamp-2 min-h-9 text-[13px] font-medium leading-snug">{item.title}</p>
        <div className="mt-2 flex items-center gap-1.5">
          {item.platforms.map((p) => (
            <Tooltip key={p} delayDuration={0}>
              <TooltipTrigger asChild>
                <span className={cn('h-2 w-2 rounded-full', PLATFORM_DOT[p] || 'bg-muted-foreground')} />
              </TooltipTrigger>
              <TooltipContent>{platformName(p)}</TooltipContent>
            </Tooltip>
          ))}
          {likes > 0 && <span className="tnum text-[11px] text-muted-foreground">👍 {fmtNum(likes)}</span>}
          <span className="flex-1" />
          <span className="text-[11px] text-muted-foreground">{fmtDate(item.date)}</span>
        </div>
        {!!item.tags.length && (
          <div className="mt-1.5 flex flex-wrap gap-1">
            {item.tags.slice(0, 3).map((t) => (
              <span key={t} className="rounded-full bg-muted px-1.5 py-0.5 text-[10px] text-muted-foreground">
                {t}
              </span>
            ))}
            {item.tags.length > 3 && <span className="text-[10px] text-muted-foreground">+{item.tags.length - 3}</span>}
          </div>
        )}
      </div>

      {/* 操作行 */}
      {!selectMode && (
        <div className="flex items-center gap-0.5 border-t border-border px-2 py-1.5">
          <Tooltip delayDuration={0}>
            <TooltipTrigger asChild>
              <button onClick={() => onSync(item)} className="flex h-7 w-7 items-center justify-center rounded-md text-muted-foreground transition-colors hover:bg-muted hover:text-foreground cursor-pointer">
                <RefreshCw className="h-3.5 w-3.5" />
              </button>
            </TooltipTrigger>
            <TooltipContent>同步数据</TooltipContent>
          </Tooltip>
          {item.kind === 'local' && item.tags_confirmed === false && (
            <Tooltip delayDuration={0}>
              <TooltipTrigger asChild>
                <button onClick={() => onConfirmTags(item)} className="flex h-7 w-7 items-center justify-center rounded-md text-warning transition-colors hover:bg-muted cursor-pointer">
                  <CheckCheck className="h-3.5 w-3.5" />
                </button>
              </TooltipTrigger>
              <TooltipContent>确认标签</TooltipContent>
            </Tooltip>
          )}
          {item.kind === 'cloud' && item.type === 'work' && item.merged > 1 && (
            <Tooltip delayDuration={0}>
              <TooltipTrigger asChild>
                <button onClick={() => onSplit(item)} className="flex h-7 w-7 items-center justify-center rounded-md text-muted-foreground transition-colors hover:bg-muted hover:text-foreground cursor-pointer">
                  <Split className="h-3.5 w-3.5" />
                </button>
              </TooltipTrigger>
              <TooltipContent>拆分合并</TooltipContent>
            </Tooltip>
          )}
          <span className="flex-1" />
          <Tooltip delayDuration={0}>
            <TooltipTrigger asChild>
              <button onClick={() => onDelete(item)} className="flex h-7 w-7 items-center justify-center rounded-md text-muted-foreground transition-colors hover:bg-[rgba(239,68,68,0.1)] hover:text-destructive cursor-pointer">
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
