import { useEffect, useMemo, useRef, useState } from 'react'
import { useQuery, useQueryClient } from '@tanstack/react-query'
import { motion } from 'framer-motion'
import {
  Save,
  LoaderCircle,
  RefreshCw,
  Sparkles,
  Cpu,
  CircleCheck,
  CircleX,
  Wand2,
  FlaskConical
} from 'lucide-react'
import { apiJson } from '@/api/client'
import { startTask } from '@/api/task'
import { useActiveWork } from '@/hooks/use-active-work'
import { listVariants, itemVariants, softIn } from '@/lib/motion'
import { Card, CardContent, CardHeader, CardTitle, CardDescription } from '@/components/ui/card'
import { Button } from '@/components/ui/button'
import { Badge } from '@/components/ui/badge'
import { Input } from '@/components/ui/input'
import { Textarea } from '@/components/ui/textarea'
import { Skeleton } from '@/components/ui/skeleton'
import { Tabs, TabsList, TabsTrigger, TabsContent } from '@/components/ui/tabs'
import { Select, SelectValue, SelectTrigger, SelectContent, SelectItem } from '@/components/ui/select'
import { ScrollArea } from '@/components/ui/scroll-area'
import { ConfirmDialog } from '@/components/ui/confirm-dialog'
import { toast } from '@/components/ui/toaster'

interface VendorMeta {
  label: string
  models: string[]
  default_model: string
  key_hint: string
  has_env_key: boolean
}

interface ModelSlot {
  vendor: string
  model: string
  key: string
  base_url: string
  key_present: boolean
  key_from_env: boolean
  vendor_label: string
  key_hint: string
}

interface BudgetItem {
  label: string
  default: number
  value: number
  floor: number
  ceiling: number
  custom: boolean
  desc: string
}

interface SelfCheckProbe {
  label: string
  ok: boolean
}

interface SelfCheck {
  ok: boolean
  checked_at?: string
  warnings?: string[]
  slots?: Record<string, { label: string; probes: Record<string, SelfCheckProbe> }>
}

interface ModelsPayload {
  model1: ModelSlot
  model2: ModelSlot
  gen_role: string
  referee_role: string
  asr: { mode: string; model: string; options: Record<string, string>; siliconflow_models: string[]; tencent_models: string[] }
  debate_rounds: number
  topics_count: number
  vendors: Record<string, VendorMeta>
  warnings: string[]
  selfcheck?: SelfCheck | null
  budgets: Record<string, BudgetItem>
  /** R-232：功能级模型路由（组键见后端 FEATURE_GROUPS） */
  feature_routes: Record<string, FeatureRouteInfo>
}

/** R-232：一组功能的主用槽位路由（value=原始值 gen/model1/model2，resolved=展开后的实际模型） */
interface FeatureRouteInfo {
  label: string
  value: string
  resolved: string
  options: { v: string; label: string }[]
}

interface PromptVersion {
  id: number
  version: number
  content: string
  status: string
  note: string
  created_at: string
}

interface EvalInfo {
  supported: boolean
  candidate_score?: number
  base_score?: number
  reason?: string
  detail?: { candidate?: { format_rate?: number; redline_rate?: number; style_rate?: number; probes?: number } }
}

interface PromptItem {
  key: string
  label: string
  group: string
  enabled_version: number
  content: string
  has_candidate: boolean
  candidate_version: number
  candidate_content: string
  candidate_note: string
  eval?: EvalInfo | null
  effect?: { version: number; drafts: number; rated: number; avg_rating?: number | null; used: number; mixed_persona?: boolean; persona_versions?: number[] }[]
  versions: PromptVersion[]
}

const ROLE_OPTS = [
  { v: 'model1', label: '模型1' },
  { v: 'model2', label: '模型2' }
]

export default function PromptsPage() {
  const qc = useQueryClient()
  const [section, setSection] = useState<'basic' | 'advanced'>('basic')
  const [promptKey, setPromptKey] = useState('')
  const [savingModels, setSavingModels] = useState(false)
  const [optimizingKey, setOptimizingKey] = useState('')
  const [ruleOptimizing, setRuleOptimizing] = useState(false)
  const [evalBusy, setEvalBusy] = useState('')
  const [rejectKey, setRejectKey] = useState('')

  // 模型设置表单态
  const [m1, setM1] = useState({ vendor: '', model: '', key: '' })
  const [m2, setM2] = useState({ vendor: '', model: '', key: '' })
  const [genRole, setGenRole] = useState('model1')
  const [refereeRole, setRefereeRole] = useState('model2')
  const [asrMode, setAsrMode] = useState('aliyun')
  const [asrModel, setAsrModel] = useState('')
  const [topicsCount, setTopicsCount] = useState(3)
  const [debateRounds, setDebateRounds] = useState(5)
  const [budgetEdits, setBudgetEdits] = useState<Record<string, number>>({})
  /** R-232：功能路由表单态（组 → 选择的槽位值） */
  const [featureRoutes, setFeatureRoutes] = useState<Record<string, string>>({})
  const [editing, setEditing] = useState<Record<string, string>>({})

  const modelsQ = useQuery({ queryKey: ['settings', 'models'], queryFn: () => apiJson<ModelsPayload>('/api/settings/models') })
  const keysQ = useQuery({ queryKey: ['prompts', 'keys'], queryFn: () => apiJson<PromptItem[]>('/api/prompts/keys') })

  // R-202：进行中状态以服务端任务为准（切页/刷新回来仍在跑 → 仍显示动画）
  const { tasks: activeTasks } = useActiveWork()
  const promptActive = activeTasks.filter((t) =>
    ['prompt_optimize', 'prompt_eval', 'prompt_rule_optimize', 'model_selfcheck'].includes(t.kind)
  )
  const prevPromptIds = useRef<Set<number>>(new Set())
  useEffect(() => {
    const ids = new Set(promptActive.map((t) => t.id))
    let lost = false
    for (const id of prevPromptIds.current) if (!ids.has(id)) lost = true
    if (lost) qc.invalidateQueries({ queryKey: ['prompts', 'keys'] })
    prevPromptIds.current = ids
  }, [promptActive, qc])

  const ruleOptimizingActive = ruleOptimizing || promptActive.some((t) => t.kind === 'prompt_rule_optimize')
  const optimizingActive = (key: string) =>
    optimizingKey === key ||
    promptActive.some((t) => t.kind === 'prompt_optimize' && String(t.payload.key || '') === key)
  const evalActive = (key: string) =>
    evalBusy === key || promptActive.some((t) => t.kind === 'prompt_eval' && String(t.payload.key || '') === key)

  const models = modelsQ.data

  useEffect(() => {
    if (!models) return
    setM1({ vendor: models.model1.vendor, model: models.model1.model, key: models.model1.key || '' })
    setM2({ vendor: models.model2.vendor, model: models.model2.model, key: models.model2.key || '' })
    setGenRole(models.gen_role)
    setRefereeRole(models.referee_role)
    setAsrMode(models.asr.mode)
    setAsrModel(models.asr.model)
    setTopicsCount(models.topics_count)
    setDebateRounds(models.debate_rounds)
    const edits: Record<string, number> = {}
    for (const [k, b] of Object.entries(models.budgets || {})) edits[k] = b.value
    setBudgetEdits(edits)
    const routes: Record<string, string> = {}
    for (const [g, fr] of Object.entries(models.feature_routes || {})) routes[g] = fr.value
    setFeatureRoutes(routes)
  }, [models])

  useEffect(() => {
    if (!keysQ.data) return
    const e: Record<string, string> = {}
    for (const item of keysQ.data) e[item.key] = item.content
    setEditing(e)
  }, [keysQ.data])

  const items = useMemo(() => keysQ.data ?? [], [keysQ.data])
  const currentItem = items.find((i) => i.key === promptKey) || null
  const item = currentItem

  useEffect(() => {
    if (!promptKey && items.length) setPromptKey(items[0].key)
  }, [items, promptKey])

  function changeAsrMode(mode: string) {
    setAsrMode(mode)
    const defaults: Record<string, string> = {
      siliconflow: models?.asr.siliconflow_models[0] || '',
      tencent: models?.asr.tencent_models[0] || '',
      aliyun: '',
      mock: ''
    }
    setAsrModel(defaults[mode] ?? '')
  }

  async function saveModels() {
    setSavingModels(true)
    try {
      const body: Record<string, unknown> = {
        model1: { vendor: m1.vendor, model: m1.model, key: m1.key },
        model2: { vendor: m2.vendor, model: m2.model, key: m2.key },
        gen_role: genRole,
        referee_role: refereeRole,
        asr_mode: asrMode,
        asr_model: asrModel,
        topics_count: Number(topicsCount),
        debate_rounds: Number(debateRounds),
        budgets: budgetEdits,
        feature_routes: featureRoutes
      }
      await apiJson('/api/settings/models', { method: 'PUT', body: JSON.stringify(body) })
      toast.success('已保存并生效，双模型兼容性自检已入队')
      qc.invalidateQueries({ queryKey: ['settings', 'models'] })
    } catch (e) {
      toast.error((e as Error).message)
    } finally {
      setSavingModels(false)
    }
  }

  async function savePrompt(item: PromptItem) {
    try {
      await apiJson(`/api/prompts/${item.key}/save`, { method: 'POST', body: JSON.stringify({ content: editing[item.key] ?? item.content }) })
      toast.success('已保存为新版本并启用')
      qc.invalidateQueries({ queryKey: ['prompts', 'keys'] })
    } catch (e) {
      toast.error((e as Error).message)
    }
  }

  async function optimize(item: PromptItem) {
    setOptimizingKey(item.key)
    try {
      await startTask(`/api/prompts/${item.key}/optimize`, { material: '' })
      toast.info('优化进行中，完成后自动刷新（失败见通知）')
    } catch (e) {
      toast.error((e as Error).message)
    } finally {
      setOptimizingKey('')
    }
  }

  async function enable(item: PromptItem, version: number) {
    try {
      await apiJson(`/api/prompts/${item.key}/enable`, { method: 'POST', body: JSON.stringify({ version }) })
      toast.success(`已启用 v${version}`)
      qc.invalidateQueries({ queryKey: ['prompts', 'keys'] })
    } catch (e) {
      toast.error((e as Error).message)
    }
  }

  async function rejectCandidate() {
    const item = items.find((x) => x.key === rejectKey)
    if (!item) return
    try {
      await apiJson(`/api/prompts/${item.key}/candidates/${item.candidate_version}/reject`, { method: 'POST', body: '{}' })
      toast.success('已拒绝候选')
      setRejectKey('')
      qc.invalidateQueries({ queryKey: ['prompts', 'keys'] })
    } catch (e) {
      toast.error((e as Error).message)
    }
  }

  async function rerunEval(item: PromptItem) {
    setEvalBusy(item.key)
    try {
      await apiJson(`/api/prompts/${item.key}/eval/rerun`, { method: 'POST', body: JSON.stringify({ version: item.candidate_version }) })
      toast.success('评测已入队，稍后刷新查看')
      setTimeout(() => qc.invalidateQueries({ queryKey: ['prompts', 'keys'] }), 5000)
    } catch (e) {
      toast.error((e as Error).message)
    } finally {
      setEvalBusy('')
    }
  }

  async function optimizeRules() {
    setRuleOptimizing(true)
    try {
      await apiJson('/api/prompts/optimize-rules', { method: 'POST', body: '{}' })
      toast.success('规则型提示词优化已入队')
    } catch (e) {
      toast.error((e as Error).message)
    } finally {
      setRuleOptimizing(false)
    }
  }

  const pct = (v?: number) => (v == null ? '—' : `${Math.round(v * 100)}%`)
  const sc = models?.selfcheck

  return (
    <motion.div variants={listVariants} initial="initial" animate="animate" className="space-y-4">
      <motion.p variants={itemVariants} className="text-xs text-muted-foreground">
        「基础」放日常要用的（模型 / Key / ASR / 每日篇数 / 讨论轮次），保存即生效；「高级」放推理预算、提示词与版本评测（默认不建议改）。「像不像作者」主要由人设页的运行时上下文决定。
      </motion.p>

      <motion.div variants={itemVariants}>
        <Tabs value={section} onValueChange={(v) => setSection(v as 'basic' | 'advanced')}>
          <TabsList className="h-auto w-full flex-wrap justify-start">
            <TabsTrigger value="basic">
              <Cpu className="h-3.5 w-3.5" /> 基础
            </TabsTrigger>
            <TabsTrigger value="advanced">
              <Wand2 className="h-3.5 w-3.5" /> 高级
              {items.some((it) => it.has_candidate) && <span className="h-1.5 w-1.5 rounded-full bg-warning" />}
            </TabsTrigger>
          </TabsList>

          {/* 基础 */}
          <TabsContent value="basic">
            {modelsQ.isLoading || !models ? (
              <Skeleton className="h-64 w-full" />
            ) : (
              <div className="space-y-4">
                {models.warnings.map((w, i) => (
                  <div key={i} className="rounded-lg border border-warning/40 bg-[rgba(245,158,11,0.08)] px-3 py-2 text-xs text-warning">{w}</div>
                ))}

                <Card>
                  <CardHeader>
                    <CardTitle>模型槽位</CardTitle>
                    <CardDescription>可分别配厂家 / 模型 / API Key（留空则用 .env）</CardDescription>
                  </CardHeader>
                  <CardContent className="space-y-4">
                    {([['model1', m1, setM1, models.model1], ['model2', m2, setM2, models.model2]] as const).map(([slot, st, setSt, meta]) => (
                      <div key={slot} className="rounded-lg border border-border p-3">
                        <div className="flex flex-wrap items-center gap-2">
                          <b className="w-12 text-[13px]">{slot === 'model1' ? '模型1' : '模型2'}</b>
                          <Select value={st.vendor} onValueChange={(v) => setSt({ ...st, vendor: v, model: models.vendors[v]?.default_model || '' })}>
                            <SelectTrigger className="h-9 w-36"><SelectValue /></SelectTrigger>
                            <SelectContent>
                              {Object.entries(models.vendors).map(([vid, vm]) => (
                                <SelectItem key={vid} value={vid}>{vm.label}</SelectItem>
                              ))}
                            </SelectContent>
                          </Select>
                          <Select value={st.model} onValueChange={(v) => setSt({ ...st, model: v })}>
                            <SelectTrigger className="h-9 w-56"><SelectValue placeholder="模型 ID" /></SelectTrigger>
                            <SelectContent>
                              {(models.vendors[st.vendor]?.models || []).map((m) => (
                                <SelectItem key={m} value={m}>{m}</SelectItem>
                              ))}
                            </SelectContent>
                          </Select>
                          <Input
                            type="password"
                            value={st.key}
                            onChange={(e) => setSt({ ...st, key: e.target.value })}
                            placeholder={meta.key_hint || 'API Key（留空则用 .env）'}
                            className="h-9 w-64"
                          />
                          {meta.key_present ? (
                            <Badge variant="success">已配置{meta.key_from_env ? '（来自 .env）' : ''}</Badge>
                          ) : (
                            <Badge variant="destructive">缺少 Key</Badge>
                          )}
                        </div>
                        <p className="mt-1.5 text-xs text-muted-foreground">{meta.vendor_label} · {meta.base_url}</p>
                      </div>
                    ))}

                    <div className="flex flex-wrap items-center gap-2">
                      <span className="text-xs text-muted-foreground">脚本生成 · 生成方：</span>
                      <Select value={genRole} onValueChange={setGenRole}>
                        <SelectTrigger className="h-9 w-32"><SelectValue /></SelectTrigger>
                        <SelectContent>
                          {ROLE_OPTS.map((r) => <SelectItem key={r.v} value={r.v}>{r.label}</SelectItem>)}
                        </SelectContent>
                      </Select>
                      <span className="text-xs text-muted-foreground">评审方：</span>
                      <Select value={refereeRole} onValueChange={setRefereeRole}>
                        <SelectTrigger className="h-9 w-32"><SelectValue /></SelectTrigger>
                        <SelectContent>
                          {ROLE_OPTS.map((r) => <SelectItem key={r.v} value={r.v}>{r.label}</SelectItem>)}
                        </SelectContent>
                      </Select>
                      <span className="text-xs text-muted-foreground">两方可以选同一个模型</span>
                    </div>

                    {/* R-232：功能路由——各功能主用槽位；选项内嵌各槽位当前实际模型名 */}
                    <div className="rounded-lg border border-border p-3">
                      <p className="mb-2 text-xs text-muted-foreground">
                        功能路由——各功能主用哪个槽位（选中槽位失败时自动兜底另一槽位并通知）
                      </p>
                      <div className="grid grid-cols-1 gap-2 lg:grid-cols-2">
                        {Object.entries(models.feature_routes || {}).map(([group, fr]) => (
                          <div key={group} className="flex items-center gap-2">
                            <span className="w-28 shrink-0 text-xs text-muted-foreground">{fr.label}</span>
                            <Select
                              value={featureRoutes[group] ?? fr.value}
                              onValueChange={(v) => setFeatureRoutes((s) => ({ ...s, [group]: v }))}
                            >
                              <SelectTrigger className="h-8 w-64 text-xs"><SelectValue /></SelectTrigger>
                              <SelectContent>
                                {fr.options.map((o) => (
                                  <SelectItem key={o.v} value={o.v}>{o.label}</SelectItem>
                                ))}
                              </SelectContent>
                            </Select>
                          </div>
                        ))}
                      </div>
                    </div>

                    <div className="flex flex-wrap items-center gap-2">
                      <span className="text-xs text-muted-foreground">ASR 服务商：</span>
                      <Select value={asrMode} onValueChange={changeAsrMode}>
                        <SelectTrigger className="h-9 w-44"><SelectValue /></SelectTrigger>
                        <SelectContent>
                          {Object.entries(models.asr.options || {}).map(([o, label]) => (
                            <SelectItem key={o} value={o}>{label}</SelectItem>
                          ))}
                        </SelectContent>
                      </Select>
                      {(asrMode === 'siliconflow' || asrMode === 'tencent') && (
                        <motion.span
                          key={asrMode}
                          initial={{ opacity: 0.85, x: 6 }}
                          animate={{ opacity: 1, x: 0 }}
                          transition={softIn}
                          className="flex flex-wrap items-center gap-2"
                        >
                          <span className="text-xs text-muted-foreground">ASR 模型：</span>
                          <Select value={asrModel} onValueChange={setAsrModel}>
                            <SelectTrigger className="h-9 w-64"><SelectValue /></SelectTrigger>
                            <SelectContent>
                              {(asrMode === 'tencent' ? models.asr.tencent_models : models.asr.siliconflow_models).map((m) => (
                                <SelectItem key={m} value={m}>{m}</SelectItem>
                              ))}
                            </SelectContent>
                          </Select>
                        </motion.span>
                      )}
                      <span className="text-xs text-muted-foreground">每日自动生成篇数：</span>
                      <Input type="number" min={1} max={10} className="h-9 w-20 text-xs" value={topicsCount} onChange={(e) => setTopicsCount(Number(e.target.value))} />
                      <span className="text-xs text-muted-foreground">讨论轮次：</span>
                      <Input type="number" min={1} max={10} className="h-9 w-20 text-xs" value={debateRounds} onChange={(e) => setDebateRounds(Number(e.target.value))} />
                    </div>
                  </CardContent>
                </Card>

                <div className="flex items-center gap-2">
                  <Button onClick={saveModels} disabled={savingModels}>
                    {savingModels ? <LoaderCircle className="h-4 w-4 animate-spin" /> : <Save className="h-4 w-4" />}
                    保存（立即生效）
                  </Button>
                  <Button variant="outline" onClick={() => qc.invalidateQueries({ queryKey: ['settings', 'models'] })}>
                    <RefreshCw className="h-4 w-4" /> 重新读取
                  </Button>
                </div>
              </div>
            )}
          </TabsContent>

          {/* 高级 */}
          <TabsContent value="advanced" className="space-y-4">
            {modelsQ.isLoading || !models ? (
              <Skeleton className="h-64 w-full" />
            ) : (
              <div className="space-y-4">
                {/* 推理预算 */}
                <Card>
                  <CardHeader className="flex-row items-center gap-2">
                    <CardTitle>推理预算（高级）</CardTitle>
                    <CardDescription>max_tokens 是上限不是消费额；低于厂家下限 {Object.values(models.budgets)[0]?.floor ?? ''} 会被自动抬升</CardDescription>
                    <span className="flex-1" />
                    <Button variant="ghost" size="sm" onClick={() => {
                      const edits: Record<string, number> = {}
                      for (const [k, b] of Object.entries(models.budgets)) edits[k] = b.default
                      setBudgetEdits(edits)
                    }}>
                      全部恢复默认
                    </Button>
                  </CardHeader>
                  <CardContent>
                    <div className="grid gap-3 sm:grid-cols-2">
                      {Object.entries(models.budgets).map(([key, b]) => (
                        <div key={key} className="rounded-lg border border-border p-3">
                          <div className="flex items-center gap-2">
                            <span className="min-w-0 flex-1 truncate text-[13px] font-medium">{b.label}</span>
                            <Input
                              type="number"
                              min={256}
                              max={b.ceiling}
                              className="h-8 w-28 text-xs tnum"
                              value={budgetEdits[key] ?? b.value}
                              onChange={(e) => setBudgetEdits({ ...budgetEdits, [key]: Number(e.target.value) })}
                            />
                          </div>
                          <p className="mt-1 text-[11px] text-muted-foreground">
                            默认 {b.default}{b.value !== b.default ? ` · 生效 ${b.value}` : ''}{b.custom ? ' · 已改' : ''} · {b.desc}
                          </p>
                        </div>
                      ))}
                    </div>
                  </CardContent>
                </Card>

                <div className="flex items-center gap-2">
                  <Button onClick={saveModels} disabled={savingModels}>
                    {savingModels ? <LoaderCircle className="h-4 w-4 animate-spin" /> : <Save className="h-4 w-4" />}
                    保存（立即生效）
                  </Button>
                  <Button variant="outline" onClick={() => qc.invalidateQueries({ queryKey: ['settings', 'models'] })}>
                    <RefreshCw className="h-4 w-4" /> 重新读取
                  </Button>
                </div>

                {sc && (
                  <Card>
                    <CardHeader className="flex-row items-center gap-2">
                      <FlaskConical className="h-4 w-4 text-accent" />
                      <CardTitle>双模型兼容性自检</CardTitle>
                      <Badge variant={sc.ok ? 'success' : 'destructive'}>{sc.ok ? '模型1/2 均兼容' : '发现问题'}</Badge>
                      <span className="text-xs text-muted-foreground">{sc.checked_at}</span>
                    </CardHeader>
                    <CardContent className="space-y-2">
                      {sc.slots && Object.entries(sc.slots).map(([slot, info]) => (
                        <div key={slot} className="flex flex-wrap items-center gap-1.5 text-xs">
                          <span className="text-muted-foreground">{info.label}：</span>
                          {Object.entries(info.probes || {}).map(([pk, p]) => (
                            <Badge key={pk} variant={p.ok ? 'success' : 'destructive'}>
                              {p.ok ? <CircleCheck className="h-3 w-3" /> : <CircleX className="h-3 w-3" />}
                              {p.label || pk}
                            </Badge>
                          ))}
                        </div>
                      ))}
                      {!!sc.warnings?.length && (
                        <ul className="list-inside list-disc text-xs text-warning">
                          {sc.warnings.map((w, i) => <li key={i}>{w}</li>)}
                        </ul>
                      )}
                    </CardContent>
                  </Card>
                )}
              </div>
            )}

            <Card>
              <CardHeader className="flex-row flex-wrap items-center gap-2">
                <CardTitle>功能提示词</CardTitle>
                <CardDescription>默认不建议改；改动会影响对应功能的产出质量（「AI 基于真实样本优化」会自动做金样本评测）</CardDescription>
                <span className="flex-1" />
                <Button variant="outline" size="sm" onClick={optimizeRules} disabled={ruleOptimizingActive}>
                  {ruleOptimizingActive ? <LoaderCircle className="h-3.5 w-3.5 animate-spin" /> : <Wand2 className="h-3.5 w-3.5" />}
                  一键优化规则型
                </Button>
              </CardHeader>
              <CardContent>
                <Select value={promptKey} onValueChange={setPromptKey}>
                  <SelectTrigger className="h-9 w-full sm:w-80"><SelectValue placeholder="选择提示词" /></SelectTrigger>
                  <SelectContent>
                    {items.map((it) => (
                      <SelectItem key={it.key} value={it.key}>
                        {it.label}{it.group === 'persona_engine' ? '（人设引擎）' : ''}{it.has_candidate ? ' · 有候选' : ''}
                      </SelectItem>
                    ))}
                  </SelectContent>
                </Select>
              </CardContent>
            </Card>

            {item && (
              <>
              <Card>
                <CardHeader className="flex-row flex-wrap items-center gap-2">
                  <CardTitle>当前启用 · v{item.enabled_version}</CardTitle>
                  {item.group === 'persona_engine' && <Badge variant="secondary">改这里会影响人设提取质量</Badge>}
                  {item.has_candidate && <Badge variant="warning">有候选 v{item.candidate_version} 待启用</Badge>}
                </CardHeader>
                <CardContent className="space-y-3">
                  <Textarea
                    rows={14}
                    className="font-mono text-xs leading-relaxed"
                    value={editing[item.key] ?? item.content}
                    onChange={(e) => setEditing({ ...editing, [item.key]: e.target.value })}
                  />
                  <div className="flex flex-wrap gap-2">
                    <Button size="sm" onClick={() => savePrompt(item)}>
                      <Save className="h-3.5 w-3.5" /> 保存为新版本并启用
                    </Button>
                    <Button variant="secondary" size="sm" onClick={() => optimize(item)} disabled={optimizingActive(item.key)}>
                      {optimizingActive(item.key) ? <LoaderCircle className="h-3.5 w-3.5 animate-spin" /> : <Sparkles className="h-3.5 w-3.5" />}
                      AI 基于真实样本优化（候选）
                    </Button>
                  </div>
                </CardContent>
              </Card>

              {item.has_candidate && (
                <Card className="border-l-2 border-l-warning">
                  <CardHeader className="flex-row flex-wrap items-center gap-2">
                    <CardTitle>候选版 v{item.candidate_version}</CardTitle>
                    {item.eval?.supported ? (
                      <Badge variant={(item.eval.candidate_score ?? 0) >= (item.eval.base_score ?? 0) ? 'success' : 'warning'}>
                        候选 {item.eval.candidate_score} vs 当前 {item.eval.base_score}
                      </Badge>
                    ) : item.eval ? (
                      <Badge variant="secondary">未评测：{item.eval.reason}</Badge>
                    ) : (
                      <Badge variant="secondary">{evalActive(item.key) ? '评测中…' : '暂无评测'}</Badge>
                    )}
                    {!!item.eval?.detail?.candidate && (
                      <span className="text-xs text-muted-foreground">
                        格式 {pct(item.eval.detail.candidate.format_rate)} · 红线命中 {pct(item.eval.detail.candidate.redline_rate)}
                      </span>
                    )}
                    <span className="flex-1" />
                    <Button variant="outline" size="sm" onClick={() => rerunEval(item)} disabled={evalActive(item.key)}>
                      {evalActive(item.key) ? <LoaderCircle className="h-3.5 w-3.5 animate-spin" /> : <FlaskConical className="h-3.5 w-3.5" />}
                      {item.eval ? '重跑评测' : '跑评测'}
                    </Button>
                    <Button size="sm" onClick={() => enable(item, item.candidate_version)}>启用此版本</Button>
                    <Button variant="outline" size="sm" className="text-destructive" onClick={() => setRejectKey(item.key)}>拒绝候选</Button>
                  </CardHeader>
                  {item.candidate_note && (
                    <CardContent className="pt-0">
                      <p className="whitespace-pre-wrap text-xs text-muted-foreground">{item.candidate_note}</p>
                    </CardContent>
                  )}
                  <CardContent className="pt-0">
                    <ScrollArea className="max-h-72 rounded-lg border border-border bg-muted/40">
                      <pre className="whitespace-pre-wrap p-3 font-mono text-[11px] leading-relaxed">{item.candidate_content}</pre>
                    </ScrollArea>
                  </CardContent>
                </Card>
              )}

              {!!item.effect?.length && (
                <Card>
                  <CardHeader>
                    <CardTitle>版本效果对比（按草稿反馈）</CardTitle>
                  </CardHeader>
                  <CardContent className="space-y-1.5">
                    {item.effect.map((e) => (
                      <div key={e.version} className="tnum flex flex-wrap items-center gap-2 text-[13px]">
                        <b>v{e.version}</b>
                        <span className="text-muted-foreground">
                          草稿 {e.drafts} 篇 · 已评分 {e.rated} · 均分 {e.avg_rating == null ? '—' : e.avg_rating} · 采用 {e.used}
                        </span>
                        {e.mixed_persona && <Badge variant="warning">跨 {(e.persona_versions || []).length} 个人设版本</Badge>}
                      </div>
                    ))}
                  </CardContent>
                </Card>
              )}

              <Card>
                <CardHeader>
                  <CardTitle>历史版本</CardTitle>
                </CardHeader>
                <CardContent className="space-y-2">
                  {!item.versions.length ? (
                    <p className="py-4 text-center text-sm text-muted-foreground">暂无历史</p>
                  ) : (
                    item.versions.map((v) => (
                      <details key={v.id} className="rounded-lg border border-border px-3 py-2">
                        <summary className="flex cursor-pointer flex-wrap items-center gap-2 text-[13px]">
                          <b>v{v.version}</b>
                          {v.status === 'enabled' ? (
                            <Badge variant="success">启用中</Badge>
                          ) : v.status === 'candidate' ? (
                            <Badge variant="warning">候选</Badge>
                          ) : (
                            <Badge variant="secondary">历史</Badge>
                          )}
                          <span className="text-xs text-muted-foreground">{v.note} · {String(v.created_at).slice(0, 10)}</span>
                        </summary>
                        <ScrollArea className="mt-2 max-h-56 rounded-md bg-muted/40">
                          <pre className="whitespace-pre-wrap p-3 font-mono text-[11px] leading-relaxed">{v.content}</pre>
                        </ScrollArea>
                        {v.status !== 'enabled' && (
                          <Button variant="outline" size="sm" className="mt-2" onClick={() => enable(item, v.version)}>
                            启用 v{v.version}
                          </Button>
                        )}
                      </details>
                    ))
                  )}
                </CardContent>
              </Card>
              </>
            )}
          </TabsContent>
        </Tabs>
      </motion.div>

      <ConfirmDialog
        open={rejectKey !== ''}
        onOpenChange={(v) => !v && setRejectKey('')}
        title={`拒绝候选 v${items.find((x) => x.key === rejectKey)?.candidate_version}？`}
        confirmText="拒绝"
        destructive
        onConfirm={rejectCandidate}
      />
    </motion.div>
  )
}
