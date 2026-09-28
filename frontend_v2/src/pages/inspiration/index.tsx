import { useMemo, useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { useQuery, useQueryClient } from '@tanstack/react-query'
import { AnimatePresence, motion } from 'framer-motion'
import { NotebookPen, Send, Sparkles, Trash2, LoaderCircle, Check } from 'lucide-react'
import { apiJson } from '@/api/client'
import { listVariants, itemVariants } from '@/lib/motion'
import { Card, CardContent, CardHeader, CardTitle, CardDescription } from '@/components/ui/card'
import { Button } from '@/components/ui/button'
import { Badge } from '@/components/ui/badge'
import { Textarea } from '@/components/ui/textarea'
import { Skeleton } from '@/components/ui/skeleton'
import { ConfirmDialog } from '@/components/ui/confirm-dialog'
import { toast } from '@/components/ui/toaster'

interface Note {
  id: number
  text: string
  image_url: string
  source: string
  status: string
  draft_id?: number | null
  created_at?: string | null
}

export default function InspirationPage() {
  const qc = useQueryClient()
  const navigate = useNavigate()
  const [text, setText] = useState('')
  const [saving, setSaving] = useState(false)
  const [busyId, setBusyId] = useState(0)
  const [del, setDel] = useState<Note | null>(null)

  const notesQ = useQuery({
    queryKey: ['inspiration'],
    queryFn: () => apiJson<Note[]>('/api/inspiration?limit=200')
  })
  const notes = useMemo(() => notesQ.data ?? [], [notesQ.data])

  async function save() {
    const body = text.trim()
    if (!body) {
      toast.warning('先写点什么')
      return
    }
    setSaving(true)
    try {
      await apiJson('/api/inspiration', { method: 'POST', body: JSON.stringify({ text: body }) })
      toast.success('已记下')
      setText('')
      qc.invalidateQueries({ queryKey: ['inspiration'] })
    } catch (e) {
      toast.error((e as Error).message)
    } finally {
      setSaving(false)
    }
  }

  async function develop(n: Note) {
    setBusyId(n.id)
    try {
      const r = await apiJson<{ draft_id: number; topic: string }>(`/api/inspiration/${n.id}/develop`, { method: 'POST' })
      toast.success(`已开始生成《${r.topic}》，去脚本工作台查看`)
      qc.invalidateQueries({ queryKey: ['inspiration'] })
      navigate(`/drafts?id=${r.draft_id}`)
    } catch (e) {
      toast.error((e as Error).message)
    } finally {
      setBusyId(0)
    }
  }

  async function doDelete() {
    if (!del) return
    try {
      await apiJson(`/api/inspiration/${del.id}`, { method: 'DELETE' })
      toast.success('已删除')
      setDel(null)
      qc.invalidateQueries({ queryKey: ['inspiration'] })
    } catch (e) {
      toast.error((e as Error).message)
    }
  }

  return (
    <motion.div variants={listVariants} initial="initial" animate="animate" className="mx-auto max-w-2xl space-y-4">
      <motion.div variants={itemVariants} className="flex items-center gap-2">
        <NotebookPen className="h-4 w-4 text-accent" />
        <span className="text-sm text-muted-foreground">刷到灵感、想到一句扎心的话、亲身经历——随手记下，一键发展成选题草稿</span>
      </motion.div>

      <motion.div variants={itemVariants}>
        <Card>
          <CardContent className="space-y-2 py-4">
            <Textarea
              value={text}
              onChange={(e) => setText(e.target.value)}
              rows={4}
              placeholder="一句话观察 / 经历 / 想吐槽的点…（例如：试用期被裁的人，简历都写得没问题，是入职前7天没做这件事）"
              className="min-h-24 resize-y text-[15px]"
            />
            <div className="flex items-center justify-between">
              <span className="text-xs text-muted-foreground">{text.trim().length} 字</span>
              <Button onClick={save} disabled={saving || !text.trim()}>
                {saving ? <LoaderCircle className="h-4 w-4 animate-spin" /> : <Send className="h-4 w-4" />}
                记下
              </Button>
            </div>
          </CardContent>
        </Card>
      </motion.div>

      <motion.div variants={itemVariants}>
        <Card>
          <CardHeader className="flex-row items-center gap-2">
            <CardTitle>原料库</CardTitle>
            <Badge variant="secondary">{notes.length}</Badge>
            <CardDescription>「生成」会先提炼成选题标题，再走双模型讨论出稿</CardDescription>
          </CardHeader>
          <CardContent className="space-y-2">
            {notesQ.isLoading ? (
              <Skeleton className="h-24 w-full" />
            ) : !notes.length ? (
              <p className="py-6 text-center text-sm text-muted-foreground">还没有随手记，上面写一条试试</p>
            ) : (
              <AnimatePresence initial={false}>
                {notes.map((n) => (
                  <motion.div
                    key={n.id}
                    layout
                    variants={itemVariants}
                    exit={{ opacity: 0, x: 12 }}
                    className="flex items-start gap-3 rounded-lg border border-border bg-card px-3.5 py-3"
                  >
                    <div className="min-w-0 flex-1">
                      <p className="whitespace-pre-wrap text-[13px] leading-relaxed">{n.text}</p>
                      <span className="mt-1 block text-[11px] text-muted-foreground">
                        {n.created_at ? String(n.created_at).replace('T', ' ').slice(0, 16) : ''}
                      </span>
                    </div>
                    {n.status === 'used' ? (
                      <Badge variant="secondary" className="shrink-0"><Check className="h-3 w-3" /> 已用</Badge>
                    ) : (
                      <Button size="sm" className="h-7 shrink-0 text-xs" onClick={() => develop(n)} disabled={busyId === n.id}>
                        {busyId === n.id ? <LoaderCircle className="h-3.5 w-3.5 animate-spin" /> : <Sparkles className="h-3.5 w-3.5" />}
                        生成
                      </Button>
                    )}
                    <Button variant="ghost" size="icon" className="h-7 w-7 shrink-0 text-destructive" onClick={() => setDel(n)}>
                      <Trash2 className="h-3.5 w-3.5" />
                    </Button>
                  </motion.div>
                ))}
              </AnimatePresence>
            )}
          </CardContent>
        </Card>
      </motion.div>

      <ConfirmDialog
        open={del !== null}
        onOpenChange={(v) => !v && setDel(null)}
        title="删除这条随手记？"
        confirmText="删除"
        destructive
        onConfirm={doDelete}
      />
    </motion.div>
  )
}
