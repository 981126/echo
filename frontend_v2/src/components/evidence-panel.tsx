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

/** R-227：联网事实来源（豆包搜索）；R-233：双源 + 生成方选文理由 */
export interface EvidenceSource {
  title?: string
  url?: string
  summary?: string
  site?: string
  provider?: string
  reason?: string
  date?: string
  content_chars?: number
}

/** R-227：提交给联网搜索的 query（留痕）；R-233：按 provider 区分 */
export interface EvidenceQuery {
  provider?: string
  query?: string
  count?: number
  time_range?: string
  raw_count?: number
  kept_count?: number
  elapsed_ms?: number
}

/** R-227：站内真实素材元数据（作者事例 + 对标参考） */
export interface StationMeta {
  author?: { kind?: string; title?: string; platform?: string }[]
  benchmark?: { title?: string; blogger?: string }[]
}

const _norm = (v?: string) => (v || '').trim()

const PROVIDER_LABELS: Record<string, string> = { doubao: '豆包', deepseek: 'DeepSeek' }

function providerLabel(provider?: string): string {
  return (provider && PROVIDER_LABELS[provider]) || ''
}

/**
 * R-227：生成/洗稿「依据」面板——顶部显示联网搜索词；可切换查看「论点」与
 * 「引用来源」（默认只显示已引用，可展开全部检索）；右上角可收起。
 * R-230：`outlineDrift` 为 true 时（outlines/sources 是讨论前初稿口径，讨论后正文已
 * 偏离论点），论点/来源区各加一行「以正文为准」提示。
 * R-233：顶部搜索词按 provider 标注（豆包/DeepSeek）；来源默认只显示「生成方按人设选中的
 * 2–3 篇 + 选文理由」，可展开全部候选；被正文引用的仍标「已引用」。
 */
export function EvidencePanel({
  outlines = [],
  outline = '',
  sources = [],
  onlineSources = [],
  references = [],
  queries = [],
  station,
  outlineDrift = false,
  className,
}: {
  outlines?: EvidenceOutline[]
  /** 兼容旧数据：单条论点字符串 */
  outline?: string
  /** 模型实际引用到的来源 */
  sources?: EvidenceSource[]
  /** 本次联网检索到的全部来源（留痕） */
  onlineSources?: EvidenceSource[]
  /** R-233：生成方按人设选中的 2–3 篇（带 reason），默认优先展示 */
  references?: EvidenceSource[]
  /** 提交给联网搜索的 query（留痕） */
  queries?: EvidenceQuery[]
  /** R-227 第 2 步：站内真实素材（作者事例 + 对标参考） */
  station?: StationMeta
  /** R-230：论点/引用为讨论前初稿口径，讨论后正文可能已调整 */
  outlineDrift?: boolean
  className?: string
}) {
  const [collapsed, setCollapsed] = useState(false)
  const [tab, setTab] = useState<'outlines' | 'sources'>('outlines')
  const [showAll, setShowAll] = useState(false)

  const items = (outlines || []).filter((o) => _norm(o.claim))
  const outlineItems: EvidenceOutline[] = items.length ? items : _norm(outline) ? [{ claim: outline }] : []

  const queryTexts = (queries || []).filter((q) => _norm(q.query))

  const refs = (references || []).filter((s) => _norm(s.title) || _norm(s.url))
  const refUrls = new Set(refs.map((s) => _norm(s.url)).filter(Boolean))
  const refTitles = new Set(refs.map((s) => _norm(s.title)).filter(Boolean))
  const isRef = (s: EvidenceSource) =>
    (!!_norm(s.url) && refUrls.has(_norm(s.url))) ||
    (!!_norm(s.title) && refTitles.has(_norm(s.title)))

  const usedUrls = new Set(sources.map((s) => _norm(s.url)).filter(Boolean))
  const usedTitles = new Set(sources.map((s) => _norm(s.title)).filter(Boolean))
  const isUsed = (s: EvidenceSource) =>
    (!!_norm(s.url) && usedUrls.has(_norm(s.url))) ||
    (!!_norm(s.title) && usedTitles.has(_norm(s.title)))

  const pool = onlineSources.length ? onlineSources : sources
  const orderedSources = [...pool].sort(
    (a, b) =>
      Number(isRef(b)) - Number(isRef(a)) || Number(isUsed(b)) - Number(isUsed(a)),
  )
  const usedCount = orderedSources.filter(isUsed).length
  const refsMode = refs.length > 0 && !showAll
  const displayedSources = refsMode
    ? refs
    : usedCount > 0 && !showAll && refs.length === 0
      ? orderedSources.filter(isUsed)
      : orderedSources

  const stationAuthor = station?.author || []
  const stationBench = station?.benchmark || []
  const stationTotal = stationAuthor.length + stationBench.length
  const sourceCount = orderedSources.length + stationTotal
  const hasOutlines = outlineItems.length > 0
  const hasSources = orderedSources.length > 0 || refs.length > 0
  const hasEvidenceSources = hasSources || stationTotal > 0

  const hasQueries = queryTexts.length > 0
  if (!hasOutlines && !hasEvidenceSources && !hasQueries) return null

  const queryLine = hasQueries ? (
    <div className="flex items-start gap-1.5 text-[11px] text-muted-foreground">
      <Search className="mt-0.5 h-3 w-3 shrink-0" />
      <span>
        <span className="text-muted-foreground/80">联网搜索词：</span>
        {queryTexts.map((q, i) => (
          <span key={i} className="text-foreground/80">
            {i > 0 ? ' · ' : ''}
            {providerLabel(q.provider) && (
              <span className="text-muted-foreground/70">{providerLabel(q.provider)} </span>
            )}
            「{_norm(q.query)}」
          </span>
        ))}
      </span>
    </div>
  ) : null

  // 只有搜索词（没有论点/来源）：只显示来源区顶部那一行
  if (!hasOutlines && !hasEvidenceSources) {
    return <div className={cn('rounded-lg border border-border p-2.5', className)}>{queryLine}</div>
  }

  const both = hasOutlines && hasEvidenceSources

  const outlinesBody = (
    <div className="mt-1.5">
      {outlineDrift && (
        <p className="mb-1.5 text-[11px] text-warning">
          论点为讨论前初稿口径，讨论后已调整，以正文为准
        </p>
      )}
      <ol className="list-inside list-decimal space-y-1.5">
        {outlineItems.map((o, i) => (
          <li key={i} className="text-[11px] leading-relaxed">
            <span className="font-medium text-foreground">{o.claim}</span>
            {_norm(o.support) && <span className="text-muted-foreground">：{o.support}</span>}
          </li>
        ))}
      </ol>
    </div>
  )

  const stationBody =
    stationTotal > 0 ? (
      <div className="mt-1.5 space-y-1">
        {stationAuthor.length > 0 && (
          <div className="text-[11px] leading-relaxed">
            <span className="text-muted-foreground/80">你的素材：</span>
            {stationAuthor.map((s, i) => (
              <span key={i} className="text-foreground/80">
                {i > 0 ? ' · ' : ''}
                {s.title || '（无标题）'}
                {s.platform ? `（${s.platform}）` : ''}
              </span>
            ))}
          </div>
        )}
        {stationBench.length > 0 && (
          <div className="text-[11px] leading-relaxed">
            <span className="text-muted-foreground/80">对标参考（他人，非你经历）：</span>
            {stationBench.map((s, i) => (
              <span key={i} className="text-foreground/80">
                {i > 0 ? ' · ' : ''}
                {s.title || '（无标题）'}
                {s.blogger ? `（${s.blogger}）` : ''}
              </span>
            ))}
          </div>
        )}
      </div>
    ) : null

  const sourcesBody = (
    <div>
      {stationBody}
      {refs.length > 0 && (
        <p className="mt-1.5 text-[11px] text-muted-foreground">
          {refsMode
            ? `生成方按人设选了 ${refs.length} 篇作为参考`
            : `生成方选文 ${refs.length} 篇 · 当前展开全部候选`}
        </p>
      )}
      <ul className="mt-1.5 space-y-1.5">
        {displayedSources.map((s, i) => {
          const used = isUsed(s)
          const picked = isRef(s)
          return (
            <li
              key={i}
              className={cn('text-[11px] leading-relaxed', !used && !picked && 'opacity-60')}
            >
              {providerLabel(s.provider) && (
                <Badge variant="secondary" className="mr-1 align-middle text-[9px]">
                  {providerLabel(s.provider)}
                </Badge>
              )}
              {used && (
                <Badge variant="success" className="mr-1 align-middle text-[9px]">
                  已引用
                </Badge>
              )}
              {!used && picked && (
                <Badge variant="outline" className="mr-1 align-middle text-[9px]">
                  参考
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
              {_norm(s.date) && (
                <span className="text-muted-foreground/60"> · {_norm(s.date).slice(0, 10)}</span>
              )}
              {_norm(s.reason) && (
                <p className="mt-0.5 text-[10px] text-muted-foreground">选文理由：{s.reason}</p>
              )}
            </li>
          )
        })}
      </ul>
      {hasSources && usedCount === 0 && refs.length === 0 && (
        <p className="mt-1.5 text-[11px] text-muted-foreground">本次联网检索到的内容未直接引用。</p>
      )}
      {outlineDrift && hasSources && (
        <p className="mt-1.5 text-[11px] text-warning">引用为讨论前初稿口径，讨论后正文可能已调整</p>
      )}
      {hasSources && (usedCount > 0 || refs.length > 0) && (
        <button
          type="button"
          onClick={() => setShowAll((v) => !v)}
          className="mt-1 cursor-pointer text-[11px] text-muted-foreground/80 hover:text-foreground"
        >
          {refs.length > 0
            ? showAll
              ? '只看生成方选文'
              : `查看全部候选 ${orderedSources.length} 条 ▸`
            : showAll
              ? '只看已引用'
              : `查看全部检索到的 ${orderedSources.length} 条 ▸`}
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
            引用来源 {sourceCount}
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
          {hasOutlines ? `论点 ${outlineItems.length}` : `引用来源 ${sourceCount}`}
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
