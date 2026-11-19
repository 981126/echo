import { useState } from 'react'
import { AnimatePresence, motion } from 'framer-motion'
import { CircleAlert, ExternalLink, FileText, Lightbulb, ShieldCheck } from 'lucide-react'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { softIn } from '@/lib/motion'

export interface GenerationAngle {
  angle_id: string
  title: string
  audience?: string
  promise?: string
  hook?: string
  reasoning?: string[]
  total_score?: number
  reject_reasons?: string[]
}

export interface GenerationAsset {
  id: number
  kind: string
  content: string
  evidence_refs?: { video_id?: number; quote?: string }[]
  score?: number
}

export interface GenerationReview {
  executed?: boolean
  logic_passed?: boolean
  attraction_score?: number
  author_score?: number
  hard_issues?: { quote?: string; problem?: string; fix?: string }[]
  issues?: { dimension?: string; quote?: string; problem?: string; fix?: string }[]
}

export interface GenerationRun {
  run_id: number
  draft_id: number
  status: 'queued' | 'running' | 'needs_input' | 'needs_review' | 'succeeded' | 'failed' | 'legacy' | string
  stage: string
  topic: string
  selected_angle?: GenerationAngle
  angles?: GenerationAngle[]
  blueprint?: {
    goal?: unknown
    audience?: unknown
    core_promise?: unknown
    hook?: { text?: string; payoff?: string }
    reasoning_steps?: { claim?: string; inference?: string; limitations?: string }[]
    actions?: { precondition?: string; action?: string; expected_result?: string }[]
    ending?: string
  }
  evidence?: {
    author_assets?: GenerationAsset[]
    online_sources?: { id: string; title?: string; url?: string; site?: string; summary?: string }[]
    questions?: string[]
  }
  review?: GenerationReview
  quality_passed: boolean
  legacy_unverified?: boolean
  error?: string
}

const KIND_LABELS: Record<string, string> = {
  fact: '事实',
  viewpoint: '观点',
  experience: '经历',
  structure: '结构',
  expression: '表达'
}

function formatValue(value: unknown): string {
  if (value == null || value === '') return '-'
  if (typeof value === 'string' || typeof value === 'number' || typeof value === 'boolean') return String(value)
  if (Array.isArray(value)) return value.map(formatValue).join('；')
  if (typeof value === 'object') return Object.entries(value as Record<string, unknown>).map(([key, item]) => `${key}：${formatValue(item)}`).join('；')
  return String(value)
}

function Section({ title, icon, children }: { title: string; icon: React.ReactNode; children: React.ReactNode }) {
  const [open, setOpen] = useState(false)
  return (
    <details open={open} onToggle={(event) => setOpen(event.currentTarget.open)} className="group rounded-lg border border-border bg-muted/20 px-3 py-2.5">
      <summary className="flex cursor-pointer list-none items-center gap-2 text-xs font-medium">
        {icon}
        {title}
        <span className="ml-auto text-muted-foreground transition-transform group-open:rotate-90">›</span>
      </summary>
      <AnimatePresence>
        <motion.div key={String(open)} initial={{ opacity: 0.85, y: 4 }} animate={{ opacity: 1, y: 0 }} transition={softIn} className="mt-3 space-y-3 text-xs leading-relaxed">
          {children}
        </motion.div>
      </AnimatePresence>
    </details>
  )
}

export function GenerationRunPanels({ run, onAngle, reworking }: { run: GenerationRun; onAngle: (angleId: string) => void; reworking: boolean }) {
  const selected = run.selected_angle?.angle_id
  const alternatives = (run.angles || []).filter((angle) => angle.angle_id !== selected && !angle.reject_reasons?.length)
  const review = run.review || { executed: false }
  return (
    <div className="space-y-2" data-testid="generation-run-panels">
      {run.legacy_unverified && (
        <div className="rounded-md bg-muted px-3 py-2 text-xs text-muted-foreground">旧版留痕，未按新质量门禁验证；旧的质量结果不会作为新稿推荐依据。</div>
      )}
      {run.status === 'needs_input' && (
        <div className="rounded-md border border-amber-300/40 bg-amber-50/60 px-3 py-2 text-xs text-amber-800 dark:bg-amber-950/20 dark:text-amber-300">
          <b>待补信息：</b>{run.error || '现有信息不足以形成可靠角度'}
          {!!run.evidence?.questions?.length && <ul className="mt-1 list-inside list-disc">{run.evidence.questions.map((question) => <li key={question}>{question}</li>)}</ul>}
        </div>
      )}
      {run.status === 'needs_review' && (
        <div className="rounded-md border border-amber-300/40 bg-amber-50/60 px-3 py-2 text-xs text-amber-800 dark:bg-amber-950/20 dark:text-amber-300">
          <b>待作者修改：</b>{run.error || '仍有未解决的质量问题'}，这篇不会标为质量通过。
        </div>
      )}
      {run.status === 'failed' && <div className="rounded-md bg-destructive/10 px-3 py-2 text-xs text-destructive">生成失败：{run.error || '模型或阶段执行失败'}</div>}
      <Section title="创作思路" icon={<Lightbulb className="h-3.5 w-3.5 text-accent" />}>
        {run.selected_angle?.promise ? (
          <>
            <div><span className="text-muted-foreground">核心承诺：</span>{formatValue(run.selected_angle.promise)}</div>
            <div><span className="text-muted-foreground">推荐角度：</span>{formatValue(run.selected_angle.title)}（{run.selected_angle.total_score ?? '-'} 分）</div>
            {run.blueprint?.goal && <div><span className="text-muted-foreground">真实目标：</span>{formatValue(run.blueprint.goal)}</div>}
            {run.blueprint?.audience && <div><span className="text-muted-foreground">适用对象：</span>{formatValue(run.blueprint.audience)}</div>}
            {!!run.blueprint?.reasoning_steps?.length && (
              <ol className="list-inside list-decimal space-y-1">
                {run.blueprint.reasoning_steps.map((step, index) => <li key={index}><b>{formatValue(step.claim)}</b>：{formatValue(step.inference)}{step.limitations ? `（边界：${formatValue(step.limitations)}）` : ''}</li>)}
              </ol>
            )}
            {!!run.blueprint?.actions?.length && (
              <ul className="space-y-1">{run.blueprint.actions.map((action, index) => <li key={index}>当 {formatValue(action.precondition)} 时，{formatValue(action.action)}；预期：{formatValue(action.expected_result)}</li>)}</ul>
            )}
          </>
        ) : <p className="text-muted-foreground">角度尚未确定，或本次没有合格角度。</p>}
        {!!alternatives.length && (
          <div className="space-y-2 border-t border-border/60 pt-2">
            <span className="text-muted-foreground">备选角度（切换前会保存当前版本）</span>
            {alternatives.map((angle) => (
              <div key={angle.angle_id} className="flex items-start gap-2 rounded-md border border-border/70 p-2">
                <div className="min-w-0 flex-1"><b>{formatValue(angle.title)}</b><p className="text-muted-foreground">{formatValue(angle.promise)}</p></div>
                <Button variant="outline" size="sm" disabled={reworking} onClick={() => onAngle(angle.angle_id)}>用此角度重新生成</Button>
              </div>
            ))}
          </div>
        )}
      </Section>
      <Section title="素材依据" icon={<FileText className="h-3.5 w-3.5 text-accent" />}>
        {run.evidence?.author_assets?.length ? run.evidence.author_assets.map((asset) => (
          <div key={asset.id} className="rounded-md border border-border/60 p-2">
            <Badge variant="secondary">{KIND_LABELS[asset.kind] || asset.kind}</Badge>
            <p className="mt-1">{formatValue(asset.content)}</p>
            {(asset.evidence_refs || []).map((ref, index) => (
              <blockquote key={index} className="mt-1 border-l-2 border-accent/40 pl-2 text-muted-foreground">
                “{ref.quote}”
                {ref.video_id && <a className="ml-1 inline-flex items-center text-accent" href={`#/videos?edit=${ref.video_id}`}>原 ASR #{ref.video_id}</a>}
              </blockquote>
            ))}
          </div>
        )) : <p className="text-muted-foreground">本次没有使用作者资产；不会把外部素材冒充作者经历。</p>}
        {!!run.evidence?.online_sources?.length && (
          <div className="space-y-1 border-t border-border/60 pt-2">
            <span className="text-muted-foreground">外部来源</span>
            {run.evidence.online_sources.map((source) => (
              <a key={source.id} href={source.url} target="_blank" rel="noreferrer" className="flex items-center gap-1 text-accent hover:underline">
                <ExternalLink className="h-3 w-3" />{source.title || source.site || source.url}
              </a>
            ))}
          </div>
        )}
      </Section>
      <Section title="质量检查" icon={<ShieldCheck className="h-3.5 w-3.5 text-accent" />}>
        <div className="flex flex-wrap items-center gap-2">
          {run.quality_passed ? <Badge variant="success">质量通过</Badge> : <Badge variant="secondary">未通过</Badge>}
          {review.executed ? <Badge variant={review.logic_passed ? 'success' : 'destructive'}>逻辑与事实{review.logic_passed ? '通过' : '未通过'}</Badge> : <Badge variant="secondary">评审未执行</Badge>}
          {review.executed && <span>吸引力 {review.attraction_score ?? '-'}/5 · 作者感 {review.author_score ?? '-'}/5</span>}
        </div>
        {!!review.hard_issues?.length && <ul className="list-inside list-disc text-destructive">{review.hard_issues.map((issue, index) => <li key={index}>{formatValue(issue.problem)}（原句：{formatValue(issue.quote)}）</li>)}</ul>}
        {!!review.issues?.length && (
          <ul className="space-y-1">{review.issues.map((issue, index) => <li key={index}><b>{formatValue(issue.dimension || '问题')}：</b>{formatValue(issue.problem)}{issue.fix ? `；建议：${formatValue(issue.fix)}` : ''}</li>)}</ul>
        )}
        {!review.executed && <p className="flex items-center gap-1 text-muted-foreground"><CircleAlert className="h-3 w-3" />未执行评审不能显示质量通过。</p>}
      </Section>
    </div>
  )
}
