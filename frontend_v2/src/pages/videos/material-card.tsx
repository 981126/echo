import { motion } from 'framer-motion'
import { Play, RefreshCw, CheckCheck, Trash2, Split, Layers, BadgeCheck, LoaderCircle } from 'lucide-react'
import { cn } from '@/lib/utils'
import { platformName, fmtNum, fmtDate } from '@/lib/format'
import { Badge } from '@/components/ui/badge'
import { Checkbox } from '@/components/ui/checkbox'
import { Progress } from '@/components/ui/progress'
import { Tooltip, TooltipContent, TooltipTrigger } from '@/components/ui/tooltip'
import type { CardItem } from './types'
import type { CardTaskState } from './use-card-tasks'

const PLATFORM_DOT: Record<string, string> = {
  douyin: 'bg-[#fe2c55]',
  xiaohongshu: 'bg-[#ff2442]',
  bilibili: 'bg-[#00a1d6]'
}

export function MaterialCard({
  item,
  index,
  selectMode,
  selected,
  task,
  onOpen,
  onToggle,
  onPlay,
  onSync,
  onConfirmTags,
  onDelete,
  onSplit
}: {
  item: CardItem
  index: number
  selectMode: boolean
  selected: boolean
  task?: CardTaskState
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

  return (
    <motion.div
      layout
      initial={{ opacity: 0, y: 18, scale: 0.97 }}
      animate={{ opacity: 1, y: 0, scale: 1 }}
      exit={{ opacity: 0, scale: 0.94 }}
      transition={{ duration: 0.35, delay: Math.min(index, 16) * 0.035, ease: [0.16, 1, 0.3, 1] }}
      whileHover={{ y: -4 }}
      className={cn(
        'group relative overflow-hidden rounded-lg border bg-card shadow-[var(--shadow-card)] transition-colors',
        selected ? 'border-accent ring-2 ring-[var(--ring)]' : 'border-border'
      )}
    >
      {/* 封面 */}
      <div className="relative aspect-[4/3] cursor-pointer overflow-hidden bg-muted" onClick={() => (selectMode ? onToggle(item) : onPlay(item))}>
        {item.cover_url ? (
          <img
            src={item.cover_url}
            alt={item.title}
            loading="lazy"
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
}
