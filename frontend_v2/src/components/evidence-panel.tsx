import { useState } from 'react'
import { ChevronDown, Link2, Search } from 'lucide-react'
import { Tabs, TabsContent, TabsList, TabsTrigger } from '@/components/ui/tabs'
import { Badge } from '@/components/ui/badge'
import { cn } from '@/lib/utils'

/** R-227：一条论点 + 其支撑（事例/数据/经历） */
export interface EvidenceOutline {
  claim?: string
  support?: string
}

/** R-227：联网事实来源（豆包搜索） */
export interface EvidenceSource {
  title?: string
  url?: string
  summary?: string
  site?: string
}

/** R-227：提交给豆包搜索的 query（留痕） */
export interface EvidenceQuery {
  query?: string
  count?: number
  time_range?: string
  raw_count?: number
}

const _norm = (v?: string) => (v || '').trim()

/**
 * R-227：生成/洗稿「依据」面板——顶部显示提交给豆包的搜索词；可切换查看「论点」与
 * 「引用来源」（默认只显示已引用，可展开全部检索）；右上角可收起。
 */
export function EvidencePanel({
  outlines = [],
  outline = '',
  sources = [],
  onlineSources = [],
  queries = [],
  className,
}: {
  outlines?: EvidenceOutline[]
  /** 兼容旧数据：单条论点字符串 */
  outline?: string
  /** 模型实际引用到的来源 */
  sources?: EvidenceSource[]
  /** 本次联网检索到的全部来源（留痕） */
  onlineSources?: EvidenceSource[]
  /** 提交给豆包的搜索词（留痕） */
  queries?: EvidenceQuery[]
  className?: string
}) {
  const [collapsed, setCollapsed] = useState(false)
  const [tab, setTab] = useState<'outlines' | 'sources'>('outlines')
  const [showAll, setShowAll] = useState(false)

  const items = (outlines || []).filter((o) => _norm(o.claim))
  const outlineItems: EvidenceOutline[] = items.length ? items : _norm(outline) ? [{ claim: outline }] : []

  const queryTexts = (queries || []).map((q) => _norm(q.query)).filter(Boolean)

  const usedUrls = new Set(sources.map((s) => _norm(s.url)).filter(Boolean))
  const usedTitles = new Set(sources.map((s) => _norm(s.title)).filter(Boolean))
  const isUsed = (s: EvidenceSource) =>
    (!!_norm(s.url) && usedUrls.has(_norm(s.url))) ||
    (!!_norm(s.title) && usedTitles.has(_norm(s.title)))

  const pool = onlineSources.length ? onlineSources : sources
  const orderedSources = [...pool].sort((a, b) => Number(isUsed(b)) - Number(isUsed(a)))
  const usedCount = orderedSources.filter(isUsed).length
  const displayedSources = usedCount > 0 && !showAll ? orderedSources.filter(isUsed) : orderedSources

  const hasOutlines = outlineItems.length > 0
  const hasSources = orderedSources.length > 0
  const hasQueries = queryTexts.length > 0
  if (!hasOutlines && !hasSources && !hasQueries) return null

  const queryLine = hasQueries ? (
    <div className="flex items-start gap-1.5 text-[11px] text-muted-foreground">
      <Search className="mt-0.5 h-3 w-3 shrink-0" />
      <span>
        <span className="text-muted-foreground/80">豆包搜索词：</span>
        {queryTexts.map((q, i) => (
          <span key={i} className="text-foreground/80">
            {i > 0 ? ' · ' : ''}「{q}」
          </span>
        ))}
      </span>
    </div>
  ) : null

  // 只有搜索词（没有论点/来源）：只显示来源区顶部那一行
  if (!hasOutlines && !hasSources) {
    return <div className={cn('rounded-lg border border-border p-2.5', className)}>{queryLine}</div>
  }

  const both = hasOutlines && hasSources

  const outlinesBody = (
    <ol className="mt-1.5 list-inside list-decimal space-y-1.5">
      {outlineItems.map((o, i) => (
        <li key={i} className="text-[11px] leading-relaxed">
          <span className="font-medium text-foreground">{o.claim}</span>
          {_norm(o.support) && <span className="text-muted-foreground">：{o.support}</span>}
        </li>
      ))}
    </ol>
  )

  const sourcesBody = (
    <div>
      <ul className="mt-1.5 space-y-1.5">
        {displayedSources.map((s, i) => {
          const used = isUsed(s)
          return (
            <li key={i} className={cn('text-[11px] leading-relaxed', !used && 'opacity-60')}>
              {used && (
                <Badge variant="success" className="mr-1 align-middle text-[9px]">
                  已引用
                </Badge>
              )}
              {s.url ? (
                <a
                  href={s.url}
                  target="_blank"
                  rel="noreferrer"
                  className="align-middle text-accent hover:underline"
                >
                  {s.title || s.url}
                </a>
              ) : (
                <span className="align-middle">{s.title || '—'}</span>
              )}
              {_norm(s.site) && <span className="text-muted-foreground/70"> · {s.site}</span>}
            </li>
          )
        })}
      </ul>
      {hasSources && usedCount === 0 && (
        <p className="mt-1.5 text-[11px] text-muted-foreground">本次联网检索到的内容未直接引用。</p>
      )}
      {hasSources && usedCount > 0 && (
        <button
          type="button"
          onClick={() => setShowAll((v) => !v)}
          className="mt-1 cursor-pointer text-[11px] text-muted-foreground/80 hover:text-foreground"
        >
          {showAll ? '只看已引用' : `查看全部检索到的 ${orderedSources.length} 条 ▸`}
        </button>
      )}
    </div>
  )

  const header = both ? (
    <Tabs value={tab} onValueChange={(v) => setTab(v as 'outlines' | 'sources')}>
      <div className="flex items-center gap-1.5">
        <Link2 className="h-3.5 w-3.5 shrink-0 text-accent" />
        <TabsList className="h-7 flex-1 justify-start bg-transparent p-0">
          <TabsTrigger value="outlines" className="h-7 px-2 text-[11px]">
            论点 {outlineItems.length}
          </TabsTrigger>
          <TabsTrigger value="sources" className="h-7 px-2 text-[11px]">
            引用来源 {orderedSources.length}
          </TabsTrigger>
        </TabsList>
        <CollapseButton collapsed={collapsed} onClick={() => setCollapsed((v) => !v)} />
      </div>
      {!collapsed && (
        <>
          <TabsContent value="outlines" className="mt-0.5">
            {outlinesBody}
          </TabsContent>
          <TabsContent value="sources" className="mt-0.5">
            {sourcesBody}
          </TabsContent>
        </>
      )}
    </Tabs>
  ) : (
    <>
      <div className="flex items-center gap-1.5">
        <Link2 className="h-3.5 w-3.5 shrink-0 text-accent" />
        <span className="text-[11px] font-medium">
          {hasOutlines ? `论点 ${outlineItems.length}` : `引用来源 ${orderedSources.length}`}
        </span>
        <CollapseButton collapsed={collapsed} onClick={() => setCollapsed((v) => !v)} className="ml-auto" />
      </div>
      {!collapsed && <div className="mt-0.5">{hasOutlines ? outlinesBody : sourcesBody}</div>}
    </>
  )

  return (
    <div className={cn('rounded-lg border border-border p-2.5', className)}>
      {/* 顶部：提交给豆包的搜索词（留痕） */}
      {queryLine && <div className="mb-1.5">{queryLine}</div>}
      {header}
    </div>
  )
}

function CollapseButton({
  collapsed,
  onClick,
  className,
}: {
  collapsed: boolean
  onClick: () => void
  className?: string
}) {
  return (
    <button
      type="button"
      aria-label={collapsed ? '展开' : '收起'}
      onClick={onClick}
      className={cn(
        'grid h-6 w-6 shrink-0 cursor-pointer place-items-center rounded-md text-muted-foreground transition-colors hover:bg-muted hover:text-foreground',
        className,
      )}
    >
      <ChevronDown className={cn('h-3.5 w-3.5 transition-transform', collapsed && '-rotate-90')} />
    </button>
  )
}
