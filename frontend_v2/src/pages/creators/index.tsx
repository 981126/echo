import { useEffect, useMemo, useReducer, useState } from 'react'
import { useQuery, useQueryClient } from '@tanstack/react-query'
import { AnimatePresence, motion } from 'framer-motion'
import {
  Plus,
  RefreshCw,
  LoaderCircle,
  Users,
  Crown,
  Target,
  Trash2,
  Pencil,
  UserPlus,
  Wallet,
  Link2
} from 'lucide-react'
import { apiJson } from '@/api/client'
import { platformName, fmtNum } from '@/lib/format'
import { listVariants, itemVariants } from '@/lib/motion'
import { Card, CardContent } from '@/components/ui/card'
import { Button } from '@/components/ui/button'
import { Badge } from '@/components/ui/badge'
import { Input } from '@/components/ui/input'
import { Textarea } from '@/components/ui/textarea'
import { Skeleton } from '@/components/ui/skeleton'
import { Avatar, AvatarImage, AvatarFallback } from '@/components/ui/avatar'
import { Switch } from '@/components/ui/switch'
import { Select, SelectValue, SelectTrigger, SelectContent, SelectItem } from '@/components/ui/select'
import { Dialog, DialogContent, DialogHeader, DialogTitle, DialogDescription } from '@/components/ui/dialog'
import { ConfirmDialog } from '@/components/ui/confirm-dialog'
import { Tooltip, TooltipContent, TooltipTrigger } from '@/components/ui/tooltip'
import { toast } from '@/components/ui/toaster'
import type { CreatorMeta, AccountMeta, SyncJob, SyncSkipped } from './types'
import { AccountRow } from './account-row'
import { SyncProgressBar, SyncSkippedBar } from './sync-progress-bar'
import { PostsDialog } from './posts-dialog'
import { TimelineCard } from '@/components/timeline-card'

interface CreatorForm {
  id: number
  kind: 'owner' | 'benchmark'
  name: string
  parent_id: number | null
  note: string
}

interface AccountForm {
  id: number
  creator_id: number
  platform: string
  nickname: string
  home_link: string
  platform_user_id: string
  cookie: string
}

const EMPTY_CREATOR: CreatorForm = { id: 0, kind: 'owner', name: '', parent_id: null, note: '' }
const EMPTY_ACCOUNT: AccountForm = { id: 0, creator_id: 0, platform: 'douyin', nickname: '', home_link: '', platform_user_id: '', cookie: '' }

// R-219：完成/失败的同步条延迟消失——done 停留 8s、failed 停留 60s（含原因），超时淡出；
// 历史旧记录（超阈值）打开页面不误显示。后端时间是无时区尾缀的北京时间（core/timeutil），
// 浏览器不在 +08:00 时区时补偏移再比较，避免时区差导致条永不消失/立即消失。
const DONE_LINGER_MS = 8000
const FAILED_LINGER_MS = 60000

function jobAgeMs(job: SyncJob): number {
  const raw = job.finished_at || job.started_at
  if (!raw) return Number.POSITIVE_INFINITY
  const iso = raw.includes('T') ? raw : raw.replace(' ', 'T')
  const hasZone = /Z$|[+-]\d{2}:?\d{2}$/.test(iso)
  const t = new Date(hasZone ? iso : `${iso}+08:00`).getTime()
  return Number.isNaN(t) ? Number.POSITIVE_INFINITY : Date.now() - t
}

function visibleJob(job: SyncJob | null): SyncJob | null {
  if (!job) return null
  if (job.status === 'running') return job
  return jobAgeMs(job) < (job.status === 'failed' ? FAILED_LINGER_MS : DONE_LINGER_MS) ? job : null
}

// R-171：CreatorBlock 必须定义在组件外部——定义在 CreatorsPage 内部会因每次渲染都是新组件类型，
// 导致 jobs 轮询更新时整块卡片被 remount，进度条反复播放进入动画（视觉上「消失又出现」）。
interface CreatorBlockHandlers {
  onSyncAll: () => void
  onSync: (body: Record<string, unknown>, msg?: string) => void
  onSwitch: (c: CreatorMeta) => void
  onBenchmarkToggle: (c: CreatorMeta, on: boolean) => void
  onDeleteCreator: (c: CreatorMeta) => void
  onEditCreator: (c: CreatorMeta) => void
  onAddAccount: (c: CreatorMeta) => void
  onAddBenchmark: (c: CreatorMeta) => void
  onEditAccount: (c: CreatorMeta, a: AccountMeta) => void
  onRemoveAccount: (a: AccountMeta) => void
  onPosts: (a: AccountMeta) => void
  onToggleEnabled: (a: AccountMeta, on: boolean) => void
}

function CreatorBlock({
  c,
  benchmark = false,
  job,
  running,
  syncingAll,
  skipped,
  hasBenchmarks,
  h
}: {
  c: CreatorMeta
  benchmark?: boolean
  job: SyncJob | null
  running: boolean
  syncingAll: boolean
  skipped: SyncSkipped | null
  hasBenchmarks: boolean
  h: CreatorBlockHandlers
}) {
  return (
    <motion.div variants={itemVariants} className="space-y-2">
      <div className="flex flex-wrap items-center gap-2.5">
        <Avatar className="h-10 w-10">
          {c.avatar ? <AvatarImage src={c.avatar} alt={c.name} /> : null}
          <AvatarFallback>{c.name.slice(0, 1) || '博'}</AvatarFallback>
        </Avatar>
        <div className="min-w-0">
          <div className="flex items-center gap-1.5">
            <span className="text-[15px] font-semibold">{c.name}</span>
            {benchmark ? (
              <Badge variant="secondary"><Target className="h-3 w-3" /> 对标</Badge>
            ) : c.is_current ? (
              <Badge><Crown className="h-3 w-3" /> 当前主博主</Badge>
            ) : (
              <Badge variant="secondary">主博主</Badge>
            )}
          </div>
          <div className="tnum text-[11px] text-muted-foreground">
            全网粉丝 {fmtNum(c.followers_total)} · {c.account_count} 个账号
            {c.note ? ` · ${c.note}` : ''}
          </div>
        </div>
        <span className="flex-1" />
        <div className="flex flex-wrap items-center gap-1.5">
          {!benchmark && c.is_current && (
            <Button size="sm" variant="secondary" onClick={h.onSyncAll} disabled={syncingAll}>
              {syncingAll ? <LoaderCircle className="h-3.5 w-3.5 animate-spin" /> : <RefreshCw className="h-3.5 w-3.5" />}
              同步所有博主前15条
            </Button>
          )}
          <Button size="sm" variant="outline" disabled={running} onClick={() => h.onSync({ scope: 'daily', creator_id: c.id })}>
            {running ? <LoaderCircle className="h-3.5 w-3.5 animate-spin" /> : <RefreshCw className="h-3.5 w-3.5" />}
            同步
          </Button>
          <Button size="sm" variant="outline" disabled={running} onClick={() => h.onSync({ scope: 'initial', creator_id: c.id }, '已入队全量同步')}>
            全量同步
          </Button>
          {!benchmark && !c.is_current && (
            <Button size="sm" variant="secondary" onClick={() => h.onSwitch(c)}>切换</Button>
          )}
          <Button size="sm" variant="ghost" onClick={() => h.onEditCreator(c)}>
            <Pencil className="h-3.5 w-3.5" />
          </Button>
          <Button size="sm" variant="ghost" onClick={() => h.onAddAccount(c)}>
            <Plus className="h-3.5 w-3.5" /> 账号
          </Button>
          {!benchmark && hasBenchmarks && (
            <Button size="sm" variant="ghost" onClick={() => h.onAddBenchmark(c)}>
              <UserPlus className="h-3.5 w-3.5" /> 对标
            </Button>
          )}
          <Button size="sm" variant="ghost" className="text-destructive" onClick={() => h.onDeleteCreator(c)}>
            <Trash2 className="h-3.5 w-3.5" />
          </Button>
        </div>
      </div>

      {/* 对标开关 */}
      <div className="flex items-center justify-end gap-2">
        <span className="text-xs text-muted-foreground">{benchmark ? '恢复为独立主博主' : '对标博主'}</span>
        <Switch checked={benchmark} onCheckedChange={(v) => h.onBenchmarkToggle(c, v)} />
      </div>

      <AnimatePresence>{job && <SyncProgressBar job={job} />}</AnimatePresence>
      <AnimatePresence>{!job && skipped && <SyncSkippedBar reason={skipped.reason} />}</AnimatePresence>

      <div className="space-y-2">
        {c.accounts.map((a) => (
          <AccountRow
            key={a.id}
            account={a}
            syncing={running || a.sync_status === 'running'}
            onSync={(acc) => h.onSync({ scope: 'daily', account_id: acc.id, creator_id: c.id })}
            onPosts={h.onPosts}
            onEdit={(acc) => h.onEditAccount(c, acc)}
            onRemove={h.onRemoveAccount}
            onToggleEnabled={h.onToggleEnabled}
          />
        ))}
        {!c.accounts.length && (
          <div className="rounded-lg border border-dashed border-border px-3 py-4 text-center text-xs text-muted-foreground">
            还没有账号，点「+ 账号」配置抖音/小红书/B站主页链接
          </div>
        )}
      </div>
    </motion.div>
  )
}

export default function CreatorsPage() {
  const qc = useQueryClient()
  const [creatorForm, setCreatorForm] = useState<CreatorForm | null>(null)
  const [accountForm, setAccountForm] = useState<AccountForm | null>(null)
  const [parsing, setParsing] = useState(false)
  const [switchTo, setSwitchTo] = useState<CreatorMeta | null>(null)
  const [benchmarkToggle, setBenchmarkToggle] = useState<{ c: CreatorMeta; on: boolean } | null>(null)
  const [deleteCreator, setDeleteCreator] = useState<CreatorMeta | null>(null)
  const [deleteAccount, setDeleteAccount] = useState<AccountMeta | null>(null)
  const [postsAccount, setPostsAccount] = useState<AccountMeta | null>(null)
  const [showBudget, setShowBudget] = useState(false)
  const [budgetLimit, setBudgetLimit] = useState<number>(2000)
  const [syncingAll, setSyncingAll] = useState(false)
  const [skippedAll, setSkippedAll] = useState<SyncSkipped[]>([])

  const creatorsQ = useQuery({ queryKey: ['creators', 'meta'], queryFn: () => apiJson<CreatorMeta[]>('/api/creators') })
  const currentQ = useQuery({
    queryKey: ['creators', 'current'],
    queryFn: () => apiJson<{ id: number | null; name: string; avatar?: string | null; followers_total: number }>('/api/creators/current')
  })
  const budgetQ = useQuery({
    queryKey: ['platform', 'budget'],
    queryFn: () => apiJson<{ limit: number; used: number; remaining: number }>('/api/platform/budget')
  })
  // R-219：拉最近全部状态任务（不再只筛 running），done/failed 条据此延迟淡出
  const jobsQ = useQuery({
    queryKey: ['sync-jobs', 'recent'],
    queryFn: () => apiJson<{ items: SyncJob[] }>('/api/platform/jobs?limit=50'),
    refetchInterval: 4000
  })

  // 延迟淡出需要秒级重渲染：仅在存在窗口期内的 done/failed 条时开 1s 心跳，空闲零开销。
  // 每次渲染重算（不 memo）：条全部淡出后心跳自动停。
  const [, tick] = useReducer((n: number) => n + 1, 0)
  const hasLingering = (jobsQ.data?.items ?? []).some(
    (j) => j.status !== 'running' && jobAgeMs(j) < FAILED_LINGER_MS
  )
  useEffect(() => {
    if (!hasLingering) return
    const t = setInterval(tick, 1000)
    return () => clearInterval(t)
  }, [hasLingering])

  const creators = useMemo(() => creatorsQ.data ?? [], [creatorsQ.data])
  const owners = useMemo(() => creators.filter((c) => c.kind === 'owner'), [creators])
  const benchmarksOf = (c: CreatorMeta) => creators.filter((b) => b.kind === 'benchmark' && b.parent_id === c.id)
  const current = currentQ.data

  // 每 creator 取最新一条 job；done/failed 按 R-219 阈值过滤（超时 → null → 淡出）
  const jobFor = (c: CreatorMeta): SyncJob | null => {
    const jobs = (jobsQ.data?.items ?? []).filter((j) => Number(j.creator_id) === c.id)
    return visibleJob(jobs[0] ?? null)
  }
  const runningCreators = new Set(
    (jobsQ.data?.items ?? []).filter((j) => j.status === 'running').map((j) => Number(j.creator_id))
  )
  // R-219：本轮 sync-all 被跳过的博主显示灰条；该博主真跑起来（有 running job）后移除
  const skipFor = (c: CreatorMeta): SyncSkipped | null => {
    const s = skippedAll.find((x) => x.creator_id === c.id)
    return s && !runningCreators.has(c.id) ? s : null
  }

  const reload = () => {
    qc.invalidateQueries({ queryKey: ['creators'] })
    qc.invalidateQueries({ queryKey: ['platform', 'budget'] })
  }

  // ---------- 博主 CRUD ----------
  async function saveCreator() {
    if (!creatorForm) return
    try {
      const body = { kind: creatorForm.kind, parent_id: creatorForm.parent_id, name: creatorForm.name, note: creatorForm.note }
      if (creatorForm.id) {
        await apiJson(`/api/creators/${creatorForm.id}`, { method: 'PATCH', body: JSON.stringify(body) })
      } else {
        await apiJson('/api/creators', { method: 'POST', body: JSON.stringify(body) })
      }
      toast.success('已保存')
      setCreatorForm(null)
      reload()
    } catch (e) {
      toast.error((e as Error).message)
    }
  }

  async function doSwitch() {
    if (!switchTo) return
    try {
      await apiJson(`/api/creators/${switchTo.id}/activate`, { method: 'POST' })
      toast.success(`已切换到「${switchTo.name}」，整套数据随之切换`)
      setSwitchTo(null)
      setSkippedAll([]) // R-219：切换主博主后旧批次的跳过提示不再适用
      qc.invalidateQueries()
    } catch (e) {
      toast.error((e as Error).message)
    }
  }

  async function doBenchmarkToggle() {
    if (!benchmarkToggle) return
    const { c, on } = benchmarkToggle
    try {
      await apiJson(`/api/creators/${c.id}/benchmark`, { method: 'POST', body: JSON.stringify({ on }) })
      toast.success(on ? '已设为对标博主' : '已恢复为独立主博主')
      setBenchmarkToggle(null)
      reload()
    } catch (e) {
      toast.error((e as Error).message)
    }
  }

  async function doDeleteCreator() {
    if (!deleteCreator) return
    try {
      await apiJson(`/api/creators/${deleteCreator.id}`, { method: 'DELETE' })
      toast.success('已删除')
      setDeleteCreator(null)
      reload()
    } catch (e) {
      toast.error((e as Error).message)
    }
  }

  // ---------- 账号 ----------
  async function saveAccount() {
    if (!accountForm) return
    try {
      const extra_config = accountForm.cookie ? { cookie: accountForm.cookie } : {}
      const body = {
        platform: accountForm.platform,
        nickname: accountForm.nickname,
        home_link: accountForm.home_link,
        platform_user_id: accountForm.platform_user_id,
        extra_config,
        enabled: true,
        sync_frequency: 'daily'
      }
      if (accountForm.id) {
        await apiJson(`/api/creators/accounts/${accountForm.id}`, { method: 'PATCH', body: JSON.stringify(body) })
      } else {
        await apiJson(`/api/creators/${accountForm.creator_id}/accounts`, { method: 'POST', body: JSON.stringify(body) })
      }
      toast.success('账号已保存')
      setAccountForm(null)
      reload()
    } catch (e) {
      toast.error((e as Error).message)
    }
  }

  async function parseLink() {
    if (!accountForm?.home_link) return
    setParsing(true)
    try {
      const r = await apiJson<{ platform_user_id: string; nickname?: string }>('/api/creators/parse-link', {
        method: 'POST',
        body: JSON.stringify({ platform: accountForm.platform, home_link: accountForm.home_link })
      })
      setAccountForm({ ...accountForm, platform_user_id: r.platform_user_id, nickname: accountForm.nickname || r.nickname || '' })
      toast.success('解析成功')
    } catch (e) {
      toast.error((e as Error).message)
    } finally {
      setParsing(false)
    }
  }

  async function doDeleteAccount() {
    if (!deleteAccount) return
    try {
      await apiJson(`/api/creators/accounts/${deleteAccount.id}`, { method: 'DELETE' })
      toast.success('账号已删除')
      setDeleteAccount(null)
      reload()
    } catch (e) {
      toast.error((e as Error).message)
    }
  }

  async function toggleEnabled(a: AccountMeta, on: boolean) {
    try {
      await apiJson(`/api/creators/accounts/${a.id}/enabled`, { method: 'POST', body: JSON.stringify({ enabled: on }) })
      reload()
    } catch (e) {
      toast.error((e as Error).message)
    }
  }

  // ---------- 同步 ----------
  async function runSync(body: Record<string, unknown>, msg = '已入队同步任务') {
    try {
      await apiJson('/api/platform/sync', { method: 'POST', body: JSON.stringify(body) })
      toast.success(msg)
      // R-219：手动重试即清掉该博主的「本轮跳过」提示
      const cid = Number(body.creator_id)
      if (Number.isFinite(cid) && cid > 0) setSkippedAll((prev) => prev.filter((s) => s.creator_id !== cid))
      qc.invalidateQueries({ queryKey: ['sync-jobs'] })
    } catch (e) {
      toast.error((e as Error).message)
    }
  }

  async function syncAll() {
    setSyncingAll(true)
    try {
      const r = await apiJson<{ creator_count: number; skipped?: SyncSkipped[] }>('/api/platform/sync-all', { method: 'POST' })
      // R-219：跳过者落为卡片下的灰条（而不是只弹一次 toast）
      setSkippedAll(r.skipped ?? [])
      toast.success(
        `已为 ${r.creator_count} 个博主入队同步${
          r.skipped?.length ? `（跳过：${r.skipped.map((s) => `${s.name}(${s.reason})`).join('、')}）` : ''
        }`
      )
      qc.invalidateQueries({ queryKey: ['sync-jobs'] })
    } catch (e) {
      toast.error((e as Error).message)
    } finally {
      setSyncingAll(false)
    }
  }

  async function saveBudget() {
    try {
      await apiJson('/api/platform/budget', { method: 'PUT', body: JSON.stringify({ limit: Number(budgetLimit) }) })
      toast.success('预算已更新')
      setShowBudget(false)
      qc.invalidateQueries({ queryKey: ['platform', 'budget'] })
    } catch (e) {
      toast.error((e as Error).message)
    }
  }

  // ---------- 渲染 ----------
  const handlers: CreatorBlockHandlers = {
    onSyncAll: syncAll,
    onSync: runSync,
    onSwitch: setSwitchTo,
    onBenchmarkToggle: (c, on) => setBenchmarkToggle({ c, on }),
    onDeleteCreator: setDeleteCreator,
    onEditCreator: (c) => setCreatorForm({ id: c.id, kind: c.kind, name: c.name, parent_id: c.parent_id ?? null, note: c.note || '' }),
    onAddAccount: (c) => setAccountForm({ ...EMPTY_ACCOUNT, creator_id: c.id }),
    onAddBenchmark: (c) => setCreatorForm({ ...EMPTY_CREATOR, kind: 'benchmark', parent_id: c.id }),
    onEditAccount: (c, acc) =>
      setAccountForm({
        id: acc.id,
        creator_id: c.id,
        platform: acc.platform,
        nickname: acc.nickname,
        home_link: acc.home_link,
        platform_user_id: acc.platform_user_id,
        cookie: (acc.extra_config?.cookie as string) || ''
      }),
    onRemoveAccount: setDeleteAccount,
    onPosts: setPostsAccount,
    onToggleEnabled: toggleEnabled
  }

  return (
    <motion.div variants={listVariants} initial="initial" animate="animate" className="space-y-4">
      {/* 时间线（R-193：从主页移到这里的最上面） */}
      <TimelineCard />

      {/* 顶部条 */}
      <motion.div variants={itemVariants}>
        <Card>
          <CardContent className="flex flex-wrap items-center gap-3 py-3">
            <span className="text-xs text-muted-foreground">当前主博主：</span>
            {current?.id ? (
              <span className="flex items-center gap-2 rounded-full bg-accent-soft py-1 pl-1 pr-3">
                <Avatar className="h-6 w-6">
                  {current.avatar ? <AvatarImage src={current.avatar} alt="" /> : null}
                  <AvatarFallback className="text-[10px]">{current.name.slice(0, 1)}</AvatarFallback>
                </Avatar>
                <b className="text-[13px]">{current.name}</b>
                <span className="tnum text-xs text-muted-foreground">全网粉丝 {fmtNum(current.followers_total)}</span>
              </span>
            ) : (
              <Badge variant="warning">未创建</Badge>
            )}
            <Button size="sm" variant="secondary" onClick={() => setCreatorForm({ ...EMPTY_CREATOR })}>
              <Plus className="h-3.5 w-3.5" /> 新建主博主
            </Button>
            <span className="flex-1" />
            <Tooltip delayDuration={0}>
              <TooltipTrigger asChild>
                <button onClick={() => { setBudgetLimit(budgetQ.data?.limit ?? 2000); setShowBudget(true) }} className="tnum flex cursor-pointer items-center gap-1 text-xs text-muted-foreground hover:text-foreground">
                  <Wallet className="h-3.5 w-3.5" /> 预算 {budgetQ.data?.used ?? 0}/{budgetQ.data?.limit ?? '—'}
                </button>
              </TooltipTrigger>
              <TooltipContent>TikHub 每日请求预算（点击调整）</TooltipContent>
            </Tooltip>
            <Button size="sm" variant="ghost" onClick={reload}>
              <RefreshCw className="h-3.5 w-3.5" /> 刷新
            </Button>
          </CardContent>
        </Card>
      </motion.div>

      {/* 博主卡片 */}
      {creatorsQ.isLoading ? (
        <div className="space-y-3">
          {Array.from({ length: 2 }).map((_, i) => (
            <Skeleton key={i} className="h-40 w-full" />
          ))}
        </div>
      ) : !owners.length ? (
        <Card>
          <CardContent className="flex h-40 flex-col items-center justify-center gap-3 text-sm text-muted-foreground">
            <Users className="h-6 w-6" />
            还没有博主。先点「新建主博主」创建你自己的账号，再配置抖音/小红书/B站账号。
          </CardContent>
        </Card>
      ) : (
        owners.map((c) => (
          <motion.div key={c.id} variants={itemVariants}>
            <Card className={c.is_current ? 'border-accent/50' : ''}>
              <CardContent className="space-y-4 py-4">
                <CreatorBlock c={c} job={jobFor(c)} running={runningCreators.has(c.id)} syncingAll={syncingAll} skipped={skipFor(c)} hasBenchmarks={benchmarksOf(c).length > 0} h={handlers} />
                {benchmarksOf(c).map((bm) => (
                  <div key={bm.id} className="ml-4 border-l-2 border-border pl-4">
                    <CreatorBlock c={bm} benchmark job={jobFor(bm)} running={runningCreators.has(bm.id)} syncingAll={syncingAll} skipped={skipFor(bm)} hasBenchmarks={false} h={handlers} />
                  </div>
                ))}
              </CardContent>
            </Card>
          </motion.div>
        ))
      )}

      {/* 博主表单 */}
      <Dialog open={creatorForm !== null} onOpenChange={(v) => !v && setCreatorForm(null)}>
        <DialogContent>
          <DialogHeader>
            <DialogTitle>{creatorForm?.id ? '编辑博主' : creatorForm?.kind === 'benchmark' ? '新建对标博主' : '新建主博主'}</DialogTitle>
            {creatorForm?.kind === 'benchmark' && <DialogDescription>对标博主挂在主博主下，每日同步同口径</DialogDescription>}
          </DialogHeader>
          {creatorForm && (
            <div className="space-y-3">
              {creatorForm.kind === 'benchmark' && !creatorForm.parent_id && (
                <div>
                  <label className="mb-1.5 block text-xs font-medium text-muted-foreground">所属主博主</label>
                  <Select value={String(creatorForm.parent_id ?? '')} onValueChange={(v) => setCreatorForm({ ...creatorForm, parent_id: Number(v) })}>
                    <SelectTrigger><SelectValue placeholder="选择主博主" /></SelectTrigger>
                    <SelectContent>
                      {owners.map((o) => (
                        <SelectItem key={o.id} value={String(o.id)}>{o.name}</SelectItem>
                      ))}
                    </SelectContent>
                  </Select>
                </div>
              )}
              <div>
                <label className="mb-1.5 block text-xs font-medium text-muted-foreground">名称</label>
                <Input value={creatorForm.name} onChange={(e) => setCreatorForm({ ...creatorForm, name: e.target.value })} placeholder="博主名称" />
              </div>
              <div>
                <label className="mb-1.5 block text-xs font-medium text-muted-foreground">备注</label>
                <Textarea rows={3} value={creatorForm.note} onChange={(e) => setCreatorForm({ ...creatorForm, note: e.target.value })} placeholder="可选" />
              </div>
              <div className="flex justify-end gap-2">
                <Button variant="ghost" size="sm" onClick={() => setCreatorForm(null)}>取消</Button>
                <Button size="sm" onClick={saveCreator} disabled={!creatorForm.name.trim()}>保存</Button>
              </div>
            </div>
          )}
        </DialogContent>
      </Dialog>

      {/* 账号表单 */}
      <Dialog open={accountForm !== null} onOpenChange={(v) => !v && setAccountForm(null)}>
        <DialogContent>
          <DialogHeader>
            <DialogTitle>{accountForm?.id ? '编辑账号' : '配置账号'}</DialogTitle>
            <DialogDescription>填主页分享链接，点「解析」自动获取平台 ID</DialogDescription>
          </DialogHeader>
          {accountForm && (
            <div className="space-y-3">
              <div>
                <label className="mb-1.5 block text-xs font-medium text-muted-foreground">平台</label>
                <Select value={accountForm.platform} onValueChange={(v) => setAccountForm({ ...accountForm, platform: v, platform_user_id: '' })} disabled={!!accountForm.id}>
                  <SelectTrigger><SelectValue /></SelectTrigger>
                  <SelectContent>
                    {['douyin', 'xiaohongshu', 'bilibili'].map((p) => (
                      <SelectItem key={p} value={p}>{platformName(p)}</SelectItem>
                    ))}
                  </SelectContent>
                </Select>
              </div>
              <div>
                <label className="mb-1.5 block text-xs font-medium text-muted-foreground">主页链接</label>
                <div className="flex gap-2">
                  <Input value={accountForm.home_link} onChange={(e) => setAccountForm({ ...accountForm, home_link: e.target.value })} placeholder="粘贴主页分享链接" />
                  <Button variant="outline" size="sm" onClick={parseLink} disabled={parsing || !accountForm.home_link}>
                    {parsing ? <LoaderCircle className="h-3.5 w-3.5 animate-spin" /> : <Link2 className="h-3.5 w-3.5" />}
                    解析
                  </Button>
                </div>
              </div>
              <div className="grid grid-cols-2 gap-3">
                <div>
                  <label className="mb-1.5 block text-xs font-medium text-muted-foreground">昵称</label>
                  <Input value={accountForm.nickname} onChange={(e) => setAccountForm({ ...accountForm, nickname: e.target.value })} />
                </div>
                <div>
                  <label className="mb-1.5 block text-xs font-medium text-muted-foreground">平台用户 ID（可自动解析）</label>
                  <Input value={accountForm.platform_user_id} onChange={(e) => setAccountForm({ ...accountForm, platform_user_id: e.target.value })} />
                </div>
              </div>
              {accountForm.platform === 'bilibili' && (
                <div>
                  <label className="mb-1.5 block text-xs font-medium text-muted-foreground">B站 Cookie（可选，yt-dlp 兜底下载用）</label>
                  <Textarea rows={2} value={accountForm.cookie} onChange={(e) => setAccountForm({ ...accountForm, cookie: e.target.value })} />
                </div>
              )}
              <div className="flex justify-end gap-2">
                <Button variant="ghost" size="sm" onClick={() => setAccountForm(null)}>取消</Button>
                <Button size="sm" onClick={saveAccount} disabled={!accountForm.platform_user_id && !accountForm.home_link}>保存</Button>
              </div>
            </div>
          )}
        </DialogContent>
      </Dialog>

      {/* 预算 */}
      <Dialog open={showBudget} onOpenChange={setShowBudget}>
        <DialogContent className="w-[min(420px,92vw)]">
          <DialogHeader>
            <DialogTitle>TikHub 每日请求预算</DialogTitle>
            <DialogDescription>超出预算后当日同步自动停止，防止额度透支</DialogDescription>
          </DialogHeader>
          <div className="flex items-center gap-2">
            <Input type="number" min={1} value={budgetLimit} onChange={(e) => setBudgetLimit(Number(e.target.value))} />
            <Button size="sm" onClick={saveBudget}>保存</Button>
          </div>
          <p className="tnum text-xs text-muted-foreground">今日已用 {budgetQ.data?.used ?? 0} · 剩余 {budgetQ.data?.remaining ?? '—'}</p>
        </DialogContent>
      </Dialog>

      {/* 确认弹窗 */}
      <ConfirmDialog
        open={switchTo !== null}
        onOpenChange={(v) => !v && setSwitchTo(null)}
        title={`切换到「${switchTo?.name}」？`}
        description="主页/素材库/脚本/人设等整套数据都会切换到该博主"
        confirmText="切换"
        onConfirm={doSwitch}
      />
      <ConfirmDialog
        open={benchmarkToggle !== null}
        onOpenChange={(v) => !v && setBenchmarkToggle(null)}
        title={benchmarkToggle?.on ? '设为对标博主？' : '恢复为独立主博主？'}
        description={benchmarkToggle?.on ? '将挂到当前主博主下参与每日对标同步' : '将不再参与对标同步'}
        confirmText="确认"
        onConfirm={doBenchmarkToggle}
      />
      <ConfirmDialog
        open={deleteCreator !== null}
        onOpenChange={(v) => !v && setDeleteCreator(null)}
        title={`删除博主「${deleteCreator?.name}」？`}
        description="其账号与云端数据将一并删除（本地素材保留）"
        confirmText="删除"
        destructive
        onConfirm={doDeleteCreator}
      />
      <ConfirmDialog
        open={deleteAccount !== null}
        onOpenChange={(v) => !v && setDeleteAccount(null)}
        title={`删除账号「${deleteAccount?.nickname || platformName(deleteAccount?.platform || '')}」？`}
        confirmText="删除"
        destructive
        onConfirm={doDeleteAccount}
      />

      <PostsDialog account={postsAccount} open={postsAccount !== null} onOpenChange={(v) => !v && setPostsAccount(null)} />
    </motion.div>
  )
}
