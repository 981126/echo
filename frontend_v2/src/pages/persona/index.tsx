import { useMemo, useState } from 'react'
import { useQuery, useQueryClient } from '@tanstack/react-query'
import { AnimatePresence, motion } from 'framer-motion'
import {
  Sparkles,
  LoaderCircle,
  RefreshCw,
  Plus,
  Trash2,
  Pencil,
  Check,
  X,
  Quote,
  SlidersHorizontal,
  Fingerprint,
  TriangleAlert
} from 'lucide-react'
import { apiJson } from '@/api/client'
import { cn } from '@/lib/utils'
import { listVariants, itemVariants } from '@/lib/motion'
import { Card, CardContent, CardHeader, CardTitle, CardDescription } from '@/components/ui/card'
import { Button } from '@/components/ui/button'
import { Badge } from '@/components/ui/badge'
import { Input } from '@/components/ui/input'
import { Checkbox } from '@/components/ui/checkbox'
import { Skeleton } from '@/components/ui/skeleton'
import { Select, SelectValue, SelectTrigger, SelectContent, SelectItem } from '@/components/ui/select'
import { Dialog, DialogContent, DialogHeader, DialogTitle } from '@/components/ui/dialog'
import { ConfirmDialog } from '@/components/ui/confirm-dialog'
import { toast } from '@/components/ui/toaster'

interface PersonaTag {
  id: number
  label: string
  description: string
  dimension: string
  category: string
  layer: string
  evidence?: string
  frequency?: number
  last_seen_at?: string | null
  status: string
}

interface PersonaCheck {
  id: number
  mode: string
  source_count: number
  coverage: number
  semantic?: number | null
  passed: boolean
  fallback: boolean
  detail: string
  created_at: string
}

interface StyleInfo {
  profile: string
  avoid_words?: string[]
  sample_count?: number
  anchor_ids?: number[]
  anchor_candidates?: { id: number; title: string }[]
}

interface Phrase {
  text: string
  source_title?: string
}

const CATEGORY: Record<string, { label: string; variant: 'default' | 'secondary' | 'destructive' | 'warning' }> = {
  style: { label: '风格', variant: 'default' },
  topic: { label: '赛道', variant: 'secondary' },
  redline: { label: '红线', variant: 'destructive' },
  phrase: { label: '金句锚点', variant: 'warning' }
}

// R-182 四层：核心DNA / 内容立场 / 创作模式 / 禁区
const LAYERS: { key: string; label: string; hint: string }[] = [
  { key: 'core_dna', label: '核心 DNA', hint: '最稳定的写作口吻特征（6–10 条）' },
  { key: 'stance', label: '内容立场', hint: '观点立场与可信经历，可随创作演化' },
  { key: 'mode', label: '创作模式', hint: '常用内容形态（犀利干货/个人独白/热点评论/实验复盘）' },
  { key: 'forbidden', label: '禁区', hint: '真正的行为禁区（平台风险/商业边界/绝不做）' }
]
const LAYER_LABEL: Record<string, string> = Object.fromEntries(LAYERS.map((l) => [l.key, l.label]))
const layerOf = (t: PersonaTag) => t.layer || 'stance'

export default function PersonaPage() {
  const qc = useQueryClient()
  const [running, setRunning] = useState(false)
  const [rebuilding, setRebuilding] = useState(false)
  const [rebuildOpen, setRebuildOpen] = useState(false)
  const [checking, setChecking] = useState(false)
  const [confirmingAll, setConfirmingAll] = useState(false)
  const [multiMode, setMultiMode] = useState(false)
  const [selected, setSelected] = useState<Set<number>>(new Set())
  const [editForm, setEditForm] = useState<{ id: number | null; label: string; description: string; dimension: string; category: string; layer: string; evidence: string } | null>(null)
  const [deleteTag, setDeleteTag] = useState<PersonaTag | null>(null)
  const [rejectAllOpen, setRejectAllOpen] = useState(false)
  const [batchOpen, setBatchOpen] = useState(false)
  const [phrases, setPhrases] = useState<Phrase[]>([])
  const [phraseLoading, setPhraseLoading] = useState(false)
  const [avoidText, setAvoidText] = useState('')
  const [savingStyle, setSavingStyle] = useState(false)
  const [styleDraft, setStyleDraft] = useState<{ avoid: string[]; sample: number; anchors: number[] } | null>(null)

  const suggestedQ = useQuery({
    queryKey: ['persona', 'suggested'],
    queryFn: () => apiJson<PersonaTag[]>('/api/persona?status=suggested')
  })
  const confirmedQ = useQuery({
    queryKey: ['persona', 'confirmed'],
    queryFn: () => apiJson<PersonaTag[]>('/api/persona?status=confirmed')
  })
  const checkQ = useQuery({
    queryKey: ['persona', 'check'],
    queryFn: () => apiJson<PersonaCheck | null>('/api/persona/check/latest')
  })
  const styleQ = useQuery({
    queryKey: ['persona', 'style'],
    queryFn: () => apiJson<StyleInfo | null>('/api/persona/style')
  })

  const suggested = suggestedQ.data ?? []
  const confirmed = confirmedQ.data ?? []
  const check = checkQ.data
  const style = styleQ.data

  // 初始化 style 草稿
  useMemo(() => {
    if (style && !styleDraft) {
      setStyleDraft({
        avoid: [...(style.avoid_words || [])],
        sample: style.sample_count || 5,
        anchors: [...(style.anchor_ids || [])]
      })
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [style])

  const reload = () => {
    qc.invalidateQueries({ queryKey: ['persona'] })
  }

  const missingItems = useMemo(() => {
    if (!check) return []
    try {
      return (JSON.parse(check.detail || '{}').missing || []) as { label: string }[]
    } catch {
      return []
    }
  }, [check])

  // ---------- 任务 ----------
  async function initPersona() {
    setRunning(true)
    try {
      await apiJson('/api/persona/init', { method: 'POST', body: '{}' })
      toast.success('已入队：用历史转写稿初始化人设（完成后通知）')
    } catch (e) {
      toast.error((e as Error).message)
    } finally {
      setRunning(false)
    }
  }

  async function rebuildPersona() {
    setRebuilding(true)
    try {
      await apiJson('/api/persona/rebuild', { method: 'POST', body: '{}' })
      toast.success('已入队：推倒重建人设（清空旧档案 → 四层重建为待确认，完成后通知）')
      setRebuildOpen(false)
      setTimeout(reload, 5000)
    } catch (e) {
      toast.error((e as Error).message)
    } finally {
      setRebuilding(false)
    }
  }

  async function recheck() {
    setChecking(true)
    try {
      await apiJson('/api/persona/recheck', { method: 'POST', body: '{}' })
      toast.success('已入队增量校验')
      setTimeout(reload, 4000)
    } catch (e) {
      toast.error((e as Error).message)
    } finally {
      setChecking(false)
    }
  }

  async function decide(t: PersonaTag, status: 'confirmed' | 'rejected') {
    try {
      await apiJson(`/api/persona/tags/${t.id}/decision`, { method: 'POST', body: JSON.stringify({ status }) })
      reload()
    } catch (e) {
      toast.error((e as Error).message)
    }
  }

  async function confirmAll() {
    setConfirmingAll(true)
    try {
      await apiJson('/api/persona/confirm-all', { method: 'POST', body: '{}' })
      toast.success('已全部确认')
      reload()
    } catch (e) {
      toast.error((e as Error).message)
    } finally {
      setConfirmingAll(false)
    }
  }

  async function rejectAll() {
    try {
      await apiJson('/api/persona/reject-all', { method: 'POST', body: '{}' })
      toast.success('已全部拒绝')
      setRejectAllOpen(false)
      reload()
    } catch (e) {
      toast.error((e as Error).message)
    }
  }

  async function saveTag() {
    if (!editForm) return
    try {
      const body = { label: editForm.label, description: editForm.description, dimension: editForm.dimension, category: editForm.category, layer: editForm.layer, evidence: editForm.evidence }
      if (editForm.id) {
        await apiJson(`/api/persona/tags/${editForm.id}`, { method: 'PATCH', body: JSON.stringify(body) })
      } else {
        await apiJson('/api/persona/tags', { method: 'POST', body: JSON.stringify({ ...body, source: 'manual' }) })
      }
      toast.success('已保存')
      setEditForm(null)
      reload()
    } catch (e) {
      toast.error((e as Error).message)
    }
  }

  async function doDeleteTag() {
    if (!deleteTag) return
    try {
      await apiJson(`/api/persona/tags/${deleteTag.id}`, { method: 'DELETE' })
      toast.success('已删除')
      setDeleteTag(null)
      reload()
    } catch (e) {
      toast.error((e as Error).message)
    }
  }

  async function batchDelete() {
    try {
      await apiJson('/api/persona/tags/batch-delete', { method: 'POST', body: JSON.stringify({ ids: [...selected] }) })
      toast.success(`已删除 ${selected.size} 项`)
      setBatchOpen(false)
      setMultiMode(false)
      setSelected(new Set())
      reload()
    } catch (e) {
      toast.error((e as Error).message)
    }
  }

  // ---------- 金句 ----------
  async function suggestPhrases() {
    setPhraseLoading(true)
    try {
      const r = await apiJson<{ items?: Phrase[] } | Phrase[]>('/api/persona/phrases/suggest?limit=12')
      setPhrases(Array.isArray(r) ? r : r.items ?? [])
    } catch (e) {
      toast.error((e as Error).message)
    } finally {
      setPhraseLoading(false)
    }
  }

  async function adoptPhrase(ph: Phrase) {
    try {
      await apiJson('/api/persona/tags', {
        method: 'POST',
        body: JSON.stringify({ label: ph.text.slice(0, 30), description: ph.text, category: 'phrase', source: 'manual' })
      })
      setPhrases(phrases.filter((p) => p !== ph))
      toast.success('已收为锚点')
      reload()
    } catch (e) {
      toast.error((e as Error).message)
    }
  }

  // ---------- 风格 ----------
  async function saveStyle() {
    if (!styleDraft) return
    setSavingStyle(true)
    try {
      await apiJson('/api/persona/style', {
        method: 'PUT',
        body: JSON.stringify({ avoid_words: styleDraft.avoid, sample_count: styleDraft.sample, anchor_ids: styleDraft.anchors })
      })
      toast.success('风格设置已保存')
      qc.invalidateQueries({ queryKey: ['persona', 'style'] })
    } catch (e) {
      toast.error((e as Error).message)
    } finally {
      setSavingStyle(false)
    }
  }

  function TagRow({ t, picking }: { t: PersonaTag; picking?: boolean }) {
    const cat = CATEGORY[t.category] || CATEGORY.style
    const picked = selected.has(t.id)
    return (
      <motion.div
        layout
        variants={itemVariants}
        exit={{ opacity: 0, x: 12 }}
        onClick={() => {
          if (picking) {
            const next = new Set(selected)
            if (picked) next.delete(t.id)
            else next.add(t.id)
            setSelected(next)
          }
        }}
        className={cn(
          'flex items-start gap-3 rounded-lg border px-3.5 py-3 transition-colors',
          picking ? 'cursor-pointer' : '',
          picked ? 'border-accent bg-accent-soft/50' : 'border-border bg-card'
        )}
      >
        {picking && <Checkbox checked={picked} className="mt-0.5" />}
        <div className="min-w-0 flex-1">
          <div className="flex flex-wrap items-center gap-1.5">
            <b className="text-[13px]">{t.label}</b>
            <Badge variant={cat.variant}>{cat.label}</Badge>
            <Badge variant="secondary">{LAYER_LABEL[layerOf(t)] || layerOf(t)}</Badge>
            {t.dimension && t.category !== 'redline' && <Badge variant="secondary">{t.dimension}</Badge>}
            {!!t.frequency && <span className="text-[10px] text-muted-foreground">出现 {t.frequency} 次</span>}
          </div>
          {t.description && <p className="mt-1 text-xs leading-relaxed text-muted-foreground">{t.description}</p>}
          {!!t.evidence && <p className="mt-0.5 text-[11px] italic text-muted-foreground/80">“{t.evidence}”</p>}
        </div>
        {!picking && (
          <div className="flex shrink-0 gap-1">
            <Button variant="ghost" size="icon" className="h-7 w-7" onClick={() => setEditForm({ id: t.id, label: t.label, description: t.description, dimension: t.dimension, category: t.category, layer: layerOf(t), evidence: t.evidence || '' })}>
              <Pencil className="h-3.5 w-3.5" />
            </Button>
            <Button variant="ghost" size="icon" className="h-7 w-7 text-destructive" onClick={() => setDeleteTag(t)}>
              <Trash2 className="h-3.5 w-3.5" />
            </Button>
          </div>
        )}
      </motion.div>
    )
  }

  return (
    <motion.div variants={listVariants} initial="initial" animate="animate" className="space-y-4">
      {/* 顶部任务条 */}
      <motion.div variants={itemVariants} className="flex flex-wrap items-center gap-2">
        <Fingerprint className="h-4 w-4 text-accent" />
        <span className="text-sm text-muted-foreground">人设 = 标签 + 描述 + 红线，AI 建议需你确认</span>
        <span className="flex-1" />
        <Button variant="secondary" size="sm" onClick={initPersona} disabled={running}>
          {running ? <LoaderCircle className="h-3.5 w-3.5 animate-spin" /> : <Sparkles className="h-3.5 w-3.5" />}
          用历史转写稿初始化人设
        </Button>
        <Button variant="outline" size="sm" onClick={() => setRebuildOpen(true)} disabled={rebuilding}>
          {rebuilding ? <LoaderCircle className="h-3.5 w-3.5 animate-spin" /> : <TriangleAlert className="h-3.5 w-3.5" />}
          推倒重建（四层）
        </Button>
      </motion.div>

      {/* 增量校验 */}
      <motion.div variants={itemVariants}>
        <Card>
          <CardContent className="flex flex-wrap items-center gap-2 py-3">
            <SlidersHorizontal className="h-4 w-4 text-accent" />
            <b className="text-[13px]">增量 vs 全量对齐（5% 口径）</b>
            {check ? (
              <>
                <Badge variant={check.fallback ? 'destructive' : 'success'}>
                  覆盖率 {((Number(check.coverage) || 0) * 100).toFixed(1)}%{check.semantic != null ? ` · 语义 ${Math.round(check.semantic)}` : ''}
                </Badge>
                <Badge variant={check.fallback ? 'warning' : 'secondary'}>{check.fallback ? '差异超标 · 已回退全量' : '增量通过'}</Badge>
                <span className="text-xs text-muted-foreground">
                  {String(check.created_at).replace('T', ' ').slice(0, 16)} · 对照 {check.source_count} 篇{check.mode === 'manual' ? ' · 手动' : ''}
                </span>
              </>
            ) : (
              <span className="text-xs text-muted-foreground">还没有校验记录</span>
            )}
            <span className="flex-1" />
            <Button variant="outline" size="sm" onClick={recheck} disabled={checking}>
              {checking ? <LoaderCircle className="h-3.5 w-3.5 animate-spin" /> : <RefreshCw className="h-3.5 w-3.5" />}
              重跑增量校验
            </Button>
          </CardContent>
          {!!missingItems.length && (
            <CardContent className="border-t border-border pt-3 text-xs text-muted-foreground">
              增量未覆盖（已按全量补齐）：{missingItems.map((m) => m.label).join('、')}
            </CardContent>
          )}
        </Card>
      </motion.div>

      {/* 金句库 */}
      <motion.section variants={itemVariants}>
        <Card>
          <CardHeader className="flex-row flex-wrap items-center gap-2">
            <Quote className="h-4 w-4 text-accent" />
            <CardTitle>像我金句库</CardTitle>
            <CardDescription>确认后的句子会作为风格锚点强注入生成</CardDescription>
            <span className="flex-1" />
            <Button variant="outline" size="sm" onClick={suggestPhrases} disabled={phraseLoading}>
              {phraseLoading ? <LoaderCircle className="h-3.5 w-3.5 animate-spin" /> : <Sparkles className="h-3.5 w-3.5" />}
              从高表现素材提取
            </Button>
          </CardHeader>
          <CardContent className="space-y-2">
            {!phrases.length ? (
              <p className="py-4 text-center text-sm text-muted-foreground">点「从高表现素材提取」生成候选（需已有素材转写稿）</p>
            ) : (
              <AnimatePresence initial={false}>
                {phrases.map((ph, i) => (
                  <motion.div
                    key={ph.text}
                    layout
                    initial={{ opacity: 0, y: 10 }}
                    animate={{ opacity: 1, y: 0 }}
                    exit={{ opacity: 0, x: 16 }}
                    transition={{ delay: i * 0.04 }}
                    className="flex items-start gap-3 rounded-lg border border-border px-3.5 py-3"
                  >
                    <div className="min-w-0 flex-1">
                      <p className="text-[13px] leading-relaxed">“{ph.text}”</p>
                      <span className="text-xs text-muted-foreground">{ph.source_title || '素材'}</span>
                    </div>
                    <Button size="sm" className="h-7 text-xs" onClick={() => adoptPhrase(ph)}>
                      <Check className="h-3 w-3" /> 收为锚点
                    </Button>
                    <Button variant="ghost" size="sm" className="h-7 text-xs" onClick={() => setPhrases(phrases.filter((p) => p !== ph))}>
                      <X className="h-3 w-3" />
                    </Button>
                  </motion.div>
                ))}
              </AnimatePresence>
            )}
          </CardContent>
        </Card>
      </motion.section>

      {/* 表达风格 */}
      <motion.section variants={itemVariants}>
        <Card>
          <CardHeader className="flex-row items-center gap-2">
            <CardTitle>表达风格（自动统计）</CardTitle>
            <span className="flex-1" />
            <Button variant="ghost" size="sm" onClick={() => qc.invalidateQueries({ queryKey: ['persona', 'style'] })}>
              <RefreshCw className="h-3.5 w-3.5" /> 刷新
            </Button>
          </CardHeader>
          <CardContent className="space-y-3">
            {!style ? (
              <p className="py-4 text-center text-sm text-muted-foreground">暂无统计（需先有素材转写稿）</p>
            ) : (
              <>
                <p className="whitespace-pre-wrap text-[13px] leading-relaxed">{style.profile}</p>
                {styleDraft && (
                  <>
                    <div>
                      <span className="mb-1.5 block text-xs text-muted-foreground">AI 腔禁用/少用词：</span>
                      <div className="flex flex-wrap gap-1.5">
                        <AnimatePresence initial={false}>
                          {styleDraft.avoid.map((w) => (
                            <motion.span key={w} layout initial={{ opacity: 0, scale: 0.8 }} animate={{ opacity: 1, scale: 1 }} exit={{ opacity: 0, scale: 0.8 }}>
                              <Badge variant="secondary" className="gap-1">
                                {w}
                                <button onClick={() => setStyleDraft({ ...styleDraft, avoid: styleDraft.avoid.filter((x) => x !== w) })}>
                                  <X className="h-3 w-3" />
                                </button>
                              </Badge>
                            </motion.span>
                          ))}
                        </AnimatePresence>
                      </div>
                      <div className="mt-2 flex flex-wrap items-center gap-2">
                        <Input value={avoidText} onChange={(e) => setAvoidText(e.target.value)} placeholder="添加（逗号分隔）" className="h-8 w-64 text-xs" />
                        <Button
                          variant="outline"
                          size="sm"
                          onClick={() => {
                            const words = avoidText.split(/[,，]/).map((x) => x.trim()).filter(Boolean)
                            if (words.length) {
                              setStyleDraft({ ...styleDraft, avoid: [...new Set([...styleDraft.avoid, ...words])] })
                              setAvoidText('')
                            }
                          }}
                        >
                          添加
                        </Button>
                        <span className="text-xs text-muted-foreground">风格样本条数：</span>
                        <Input
                          type="number"
                          min={3}
                          max={8}
                          className="h-8 w-20 text-xs"
                          value={styleDraft.sample}
                          onChange={(e) => setStyleDraft({ ...styleDraft, sample: Number(e.target.value) })}
                        />
                        <Button size="sm" onClick={saveStyle} disabled={savingStyle}>
                          {savingStyle ? <LoaderCircle className="h-3.5 w-3.5 animate-spin" /> : <Check className="h-3.5 w-3.5" />}
                          保存
                        </Button>
                      </div>
                    </div>
                    {!!style.anchor_candidates?.length && (
                      <div>
                        <span className="mb-1.5 block text-xs text-muted-foreground">
                          生成风格范本（勾选的素材必定注入生成上下文，不参与检索淘汰）——建议选 5–10 条、覆盖不同内容模式
                        </span>
                        <div className="flex flex-wrap gap-x-4 gap-y-1.5">
                          {style.anchor_candidates.map((c) => (
                            <label key={c.id} className="flex cursor-pointer items-center gap-1.5 text-xs">
                              <Checkbox
                                checked={styleDraft.anchors.includes(c.id)}
                                onCheckedChange={(v) =>
                                  setStyleDraft({
                                    ...styleDraft,
                                    anchors: v ? [...styleDraft.anchors, c.id] : styleDraft.anchors.filter((x) => x !== c.id)
                                  })
                                }
                              />
                              {c.title}
                            </label>
                          ))}
                        </div>
                      </div>
                    )}
                  </>
                )}
              </>
            )}
          </CardContent>
        </Card>
      </motion.section>

      {/* 待确认建议 */}
      <motion.section variants={itemVariants}>
        <Card>
          <CardHeader className="flex-row flex-wrap items-center gap-2">
            <CardTitle>待确认建议</CardTitle>
            {!!suggested.length && <Badge variant="warning">{suggested.length}</Badge>}
            <span className="flex-1" />
            {!!suggested.length && (
              <>
                <Button variant="secondary" size="sm" onClick={confirmAll} disabled={confirmingAll}>
                  {confirmingAll ? <LoaderCircle className="h-3.5 w-3.5 animate-spin" /> : <Check className="h-3.5 w-3.5" />}
                  一键确认
                </Button>
                <Button variant="outline" size="sm" className="text-destructive" onClick={() => setRejectAllOpen(true)}>
                  一键拒绝
                </Button>
              </>
            )}
          </CardHeader>
          <CardContent className="space-y-2">
            {suggestedQ.isLoading ? (
              <Skeleton className="h-20 w-full" />
            ) : !suggested.length ? (
              <p className="py-4 text-center text-sm text-muted-foreground">暂无待确认建议</p>
            ) : (
              <AnimatePresence initial={false}>
                {suggested.map((t) => (
                  <motion.div key={t.id} layout variants={itemVariants} exit={{ opacity: 0, x: -16 }} className="flex items-start gap-3 rounded-lg border border-warning/40 bg-[rgba(245,158,11,0.05)] px-3.5 py-3">
                    <div className="min-w-0 flex-1">
                      <div className="flex flex-wrap items-center gap-1.5">
                        <b className="text-[13px]">{t.label}</b>
                        <Badge variant={(CATEGORY[t.category] || CATEGORY.style).variant}>
                          {(CATEGORY[t.category] || CATEGORY.style).label}
                        </Badge>
                        <Badge variant="secondary">{LAYER_LABEL[layerOf(t)] || layerOf(t)}</Badge>
                        {t.dimension && <Badge variant="secondary">{t.dimension}</Badge>}
                        {!!t.frequency && <span className="text-[10px] text-muted-foreground">出现 {t.frequency} 次</span>}
                      </div>
                      {t.description && <p className="mt-1 text-xs leading-relaxed text-muted-foreground">{t.description}</p>}
                      {!!t.evidence && <p className="mt-0.5 text-[11px] italic text-muted-foreground/80">“{t.evidence}”</p>}
                    </div>
                    <Button size="sm" className="h-7 text-xs" onClick={() => decide(t, 'confirmed')}>
                      <Check className="h-3 w-3" /> 确认
                    </Button>
                    <Button variant="ghost" size="sm" className="h-7 text-xs" onClick={() => decide(t, 'rejected')}>
                      <X className="h-3 w-3" /> 拒绝
                    </Button>
                  </motion.div>
                ))}
              </AnimatePresence>
            )}
          </CardContent>
        </Card>
      </motion.section>

      {/* 已确认档案 */}
      <motion.section variants={itemVariants}>
        <Card>
          <CardHeader className="flex-row items-center gap-2">
            <CardTitle>已确认档案</CardTitle>
            <Badge variant="secondary">{confirmed.length}</Badge>
            <span className="flex-1" />
            {!multiMode ? (
              <>
                <Button variant="outline" size="sm" onClick={() => setMultiMode(true)} disabled={!confirmed.length}>多选</Button>
                <Button size="sm" onClick={() => setEditForm({ id: null, label: '', description: '', dimension: '', category: 'style', layer: 'stance', evidence: '' })}>
                  <Plus className="h-3.5 w-3.5" /> 新增
                </Button>
              </>
            ) : (
              <>
                <span className="text-xs text-muted-foreground">已选 {selected.size} 项</span>
                <Button variant="destructive" size="sm" disabled={!selected.size} onClick={() => setBatchOpen(true)}>
                  <Trash2 className="h-3.5 w-3.5" /> 删除所选
                </Button>
                <Button variant="ghost" size="sm" onClick={() => { setMultiMode(false); setSelected(new Set()) }}>取消</Button>
              </>
            )}
          </CardHeader>
          <CardContent className="space-y-2">
            {confirmedQ.isLoading ? (
              <Skeleton className="h-20 w-full" />
            ) : !confirmed.length ? (
              <p className="py-4 text-center text-sm text-muted-foreground">暂无已确认人设</p>
            ) : (
              <div className="space-y-4">
                {LAYERS.map((l) => {
                  const items = confirmed.filter((t) => layerOf(t) === l.key)
                  if (!items.length) return null
                  return (
                    <div key={l.key} className="space-y-2">
                      <div className="flex flex-wrap items-center gap-2">
                        <span className="text-xs font-medium">{l.label}</span>
                        <Badge variant="secondary">{items.length}</Badge>
                        <span className="text-[11px] text-muted-foreground">{l.hint}</span>
                      </div>
                      <motion.div layout className="space-y-2">
                        <AnimatePresence initial={false}>
                          {items.map((t) => (
                            <TagRow key={t.id} t={t} picking={multiMode} />
                          ))}
                        </AnimatePresence>
                      </motion.div>
                    </div>
                  )
                })}
              </div>
            )}
          </CardContent>
        </Card>
      </motion.section>

      {/* 编辑/新增 */}
      <Dialog open={editForm !== null} onOpenChange={(v) => !v && setEditForm(null)}>
        <DialogContent className="w-[min(460px,92vw)]">
          <DialogHeader>
            <DialogTitle>{editForm?.id ? '编辑人设标签' : '新增风格档案'}</DialogTitle>
          </DialogHeader>
          {editForm && (
            <div className="space-y-3">
              <div>
                <label className="mb-1.5 block text-xs font-medium text-muted-foreground">标签</label>
                <Input value={editForm.label} onChange={(e) => setEditForm({ ...editForm, label: e.target.value })} placeholder="如：犀利敢说" />
              </div>
              <div>
                <label className="mb-1.5 block text-xs font-medium text-muted-foreground">描述</label>
                <Input value={editForm.description} onChange={(e) => setEditForm({ ...editForm, description: e.target.value })} placeholder="一句话描述" />
              </div>
              <div>
                <label className="mb-1.5 block text-xs font-medium text-muted-foreground">维度（可留空）</label>
                <Input value={editForm.dimension} onChange={(e) => setEditForm({ ...editForm, dimension: e.target.value })} placeholder="如：语气 / 价值观 / 口头禅 / 受众" />
              </div>
              <div>
                <label className="mb-1.5 block text-xs font-medium text-muted-foreground">类别</label>
                <Select value={editForm.category} onValueChange={(v) => setEditForm({ ...editForm, category: v })}>
                  <SelectTrigger><SelectValue /></SelectTrigger>
                  <SelectContent>
                    {Object.entries(CATEGORY).map(([k, v]) => (
                      <SelectItem key={k} value={k}>{v.label}</SelectItem>
                    ))}
                  </SelectContent>
                </Select>
              </div>
              <div>
                <label className="mb-1.5 block text-xs font-medium text-muted-foreground">分层（R-182 四层）</label>
                <Select value={editForm.layer} onValueChange={(v) => setEditForm({ ...editForm, layer: v })}>
                  <SelectTrigger><SelectValue /></SelectTrigger>
                  <SelectContent>
                    {LAYERS.map((l) => (
                      <SelectItem key={l.key} value={l.key}>{l.label}</SelectItem>
                    ))}
                  </SelectContent>
                </Select>
              </div>
              <div>
                <label className="mb-1.5 block text-xs font-medium text-muted-foreground">证据（原文短句，可留空）</label>
                <Input value={editForm.evidence} onChange={(e) => setEditForm({ ...editForm, evidence: e.target.value })} placeholder="摘一句原文" />
              </div>
              <div className="flex justify-end gap-2">
                <Button variant="ghost" size="sm" onClick={() => setEditForm(null)}>取消</Button>
                <Button size="sm" onClick={saveTag} disabled={!editForm.label.trim()}>{editForm.id ? '保存' : '新增'}</Button>
              </div>
            </div>
          )}
        </DialogContent>
      </Dialog>

      <ConfirmDialog open={deleteTag !== null} onOpenChange={(v) => !v && setDeleteTag(null)} title={`删除人设标签「${deleteTag?.label}」？`} confirmText="删除" destructive onConfirm={doDeleteTag} />
      <ConfirmDialog
        open={rebuildOpen}
        onOpenChange={setRebuildOpen}
        title="推倒重建人设档案？"
        description="将清空当前全部人设标签，重新逐篇分析并归纳成「核心DNA/内容立场/创作模式/禁区」四层，产出为新一批待确认建议（需你审核确认）。旧档案请确保已备份。"
        confirmText="推倒重建"
        destructive
        loading={rebuilding}
        onConfirm={rebuildPersona}
      />
      <ConfirmDialog open={rejectAllOpen} onOpenChange={setRejectAllOpen} title="一键拒绝全部建议？" description={`共 ${suggested.length} 条待确认建议将被拒绝`} confirmText="全部拒绝" destructive onConfirm={rejectAll} />
      <ConfirmDialog open={batchOpen} onOpenChange={setBatchOpen} title={`删除所选 ${selected.size} 项人设？`} confirmText="删除" destructive onConfirm={batchDelete} />

      {/* 对齐提示 */}
      <motion.p variants={itemVariants} className="flex items-start gap-1.5 text-xs text-muted-foreground">
        <TriangleAlert className="mt-0.5 h-3.5 w-3.5 shrink-0" />
        以上（含禁用词、风格画像、金句锚点）都是生成时的运行时上下文，由本页维护、动态注入，不在「AI 提示词」正文里——想改风格请改这里
      </motion.p>
    </motion.div>
  )
}
