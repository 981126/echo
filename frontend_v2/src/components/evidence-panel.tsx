import { useState } from 'react'
import { ChevronDown, Link2 } from 'lucide-react'
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

const _norm = (v?: string) => (v || '').trim()

/**
 * R-227：洗稿「依据」面板——可切换查看「论点」与「引用来源」，右上角可收起。
 *
 * - 论点（outlines）/ 引用来源（onlineSources=检索到的全部，sources=实际引用）分两个标签；
 * - 来源里已引用的排前并标「已引用」，未引用的置灰在后；
 * - 两者皆空则不渲染。
 */
export function EvidencePanel({
  outlines = [],
  outline = '',
  sources = [],
  onlineSources = [],
  className,
}: {
  outlines?: EvidenceOutline[]
  /** 兼容旧数据：单条论点字符串 */
  outline?: string
  /** 模型实际引用到的来源 */
  sources?: EvidenceSource[]
  /** 本次联网检索到的全部来源（留痕） */
  onlineSources?: EvidenceSource[]
  className?: string
}) {
  const [collapsed, setCollapsed] = useState(false)
  const [tab, setTab] = useState<'outlines' | 'sources'>('outlines')

  const items = (outlines || []).filter((o) => _norm(o.claim))
  const outlineItems: EvidenceOutline[] = items.length ? items : _norm(outline) ? [{ claim: outline }] : []

  const usedUrls = new Set(sources.map((s) => _norm(s.url)).filter(Boolean))
  const usedTitles = new Set(sources.map((s) => _norm(s.title)).filter(Boolean))
  const isUsed = (s: EvidenceSource) =>
    (!!_norm(s.url) && usedUrls.has(_norm(s.url))) ||
    (!!_norm(s.title) && usedTitles.has(_norm(s.title)))

  const pool = onlineSources.length ? onlineSources : sources
  const orderedSources = [...pool].sort((a, b) => Number(isUsed(b)) - Number(isUsed(a)))
  const usedCount = orderedSources.filter(isUsed).length

  const hasOutlines = outlineItems.length > 0
  const hasSources = orderedSources.length > 0
  if (!hasOutlines && !hasSources) return null

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
    <ul className="mt-1.5 space-y-1.5">
      {orderedSources.map((s, i) => {
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
      {hasSources && usedCount === 0 && (
        <li className="text-[11px] text-muted-foreground">本次联网检索到的内容未直接引用。</li>
      )}
    </ul>
  )

  return (
    <div className={cn('rounded-lg border border-border p-2.5', className)}>
      {both ? (
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
            <button
              type="button"
              aria-label={collapsed ? '展开' : '收起'}
              onClick={() => setCollapsed((v) => !v)}
              className="grid h-6 w-6 shrink-0 cursor-pointer place-items-center rounded-md text-muted-foreground transition-colors hover:bg-muted hover:text-foreground"
            >
              <ChevronDown className={cn('h-3.5 w-3.5 transition-transform', collapsed && '-rotate-90')} />
            </button>
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
            <button
              type="button"
              aria-label={collapsed ? '展开' : '收起'}
              onClick={() => setCollapsed((v) => !v)}
              className="ml-auto grid h-6 w-6 shrink-0 cursor-pointer place-items-center rounded-md text-muted-foreground transition-colors hover:bg-muted hover:text-foreground"
            >
              <ChevronDown className={cn('h-3.5 w-3.5 transition-transform', collapsed && '-rotate-90')} />
            </button>
          </div>
          {!collapsed && <div className="mt-0.5">{hasOutlines ? outlinesBody : sourcesBody}</div>}
        </>
      )}
    </div>
  )
}
