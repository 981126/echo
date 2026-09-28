import { useRef, useState } from 'react'
import { createPortal } from 'react-dom'
import { useQuery, useQueryClient } from '@tanstack/react-query'
import { AnimatePresence, motion } from 'framer-motion'
import MarkdownIt from 'markdown-it'
import {
  Plus,
  Send,
  LoaderCircle,
  Trash2,
  Pencil,
  MessageSquare,
  CircleCheck,
  Copy,
  Wrench,
  CheckCheck,
  X
} from 'lucide-react'
import { apiJson, apiFetch } from '@/api/client'
import { cn } from '@/lib/utils'
import { Button } from '@/components/ui/button'
import { ScrollArea } from '@/components/ui/scroll-area'
import { ConfirmDialog } from '@/components/ui/confirm-dialog'
import { toast } from '@/components/ui/toaster'

const md = new MarkdownIt({ html: false, linkify: true })

interface Conversation {
  id: number
  title: string
  created_at?: string
  updated_at?: string
}

interface ChatMessage {
  key: string
  role: 'user' | 'assistant'
  content: string
  streaming?: boolean
  steps?: { kind: 'run' | 'ok'; text: string }[]
}

interface AgentAction {
  id: number
  kind: string
  title: string
  detail?: string
  status: string
  conversation_id?: number
}

interface StepData {
  kind?: string
  tool?: string
  name?: string
  summary?: string
  detail?: string
}

function stepText(d: StepData): string {
  if (d.kind === 'result') return d.summary || d.detail || '完成'
  return d.summary || `${d.tool || d.name || '工具'}：${d.detail || ''}`
}

export default function ChatPage() {
  const qc = useQueryClient()
  const [currentId, setCurrentId] = useState<number | null>(null)
  const [messages, setMessages] = useState<ChatMessage[]>([])
  const [input, setInput] = useState('')
  const [sending, setSending] = useState(false)
  const [actions, setActions] = useState<AgentAction[]>([])
  const [deleteConv, setDeleteConv] = useState<Conversation | null>(null)
  const [renaming, setRenaming] = useState<Conversation | null>(null)
  const [renameText, setRenameText] = useState('')
  const boxRef = useRef<HTMLDivElement>(null)
  const keySeq = useRef(0)

  const convsQ = useQuery({
    queryKey: ['chat', 'conversations'],
    queryFn: () => apiJson<Conversation[]>('/api/chat/conversations')
  })

  const scroll = () => {
    requestAnimationFrame(() => {
      if (boxRef.current) boxRef.current.scrollTop = boxRef.current.scrollHeight
    })
  }

  async function loadHistory(id: number) {
    try {
      const rows = await apiJson<{ role: string; content: string }[]>(`/api/chat/history?conversation_id=${id}&limit=200`)
      setMessages(rows.map((r) => ({ key: 'h' + (++keySeq.current), role: r.role as 'user' | 'assistant', content: r.content })))
      const acts = await apiJson<AgentAction[]>(`/api/chat/actions?conversation_id=${id}`)
      setActions(acts)
    } catch (e) {
      toast.error((e as Error).message)
    }
    scroll()
  }

  async function selectConv(c: Conversation) {
    setCurrentId(c.id)
    await loadHistory(c.id)
  }

  async function newConversation() {
    const c = await apiJson<Conversation>('/api/chat/conversations', { method: 'POST', body: '{}' })
    qc.invalidateQueries({ queryKey: ['chat', 'conversations'] })
    setCurrentId(c.id)
    setMessages([])
    setActions([])
  }

  async function doRename() {
    if (!renaming) return
    await apiJson(`/api/chat/conversations/${renaming.id}`, { method: 'PATCH', body: JSON.stringify({ title: renameText }) })
    toast.success('已重命名')
    setRenaming(null)
    qc.invalidateQueries({ queryKey: ['chat', 'conversations'] })
  }

  async function doDeleteConv() {
    if (!deleteConv) return
    await apiJson(`/api/chat/conversations/${deleteConv.id}`, { method: 'DELETE' })
    toast.success('已删除')
    if (currentId === deleteConv.id) {
      setCurrentId(null)
      setMessages([])
    }
    setDeleteConv(null)
    qc.invalidateQueries({ queryKey: ['chat', 'conversations'] })
  }

  async function actOn(a: AgentAction, action: 'confirm' | 'cancel') {
    try {
      await apiJson(`/api/chat/actions/${a.id}/${action}`, { method: 'POST', body: '{}' })
      toast.success(action === 'confirm' ? '已确认执行' : '已取消')
      if (currentId) {
        const acts = await apiJson<AgentAction[]>(`/api/chat/actions?conversation_id=${currentId}`)
        setActions(acts)
      }
    } catch (e) {
      toast.error((e as Error).message)
    }
  }

  async function send() {
    const q = input.trim()
    if (!q || sending || currentId == null) return
    setInput('')
    setSending(true)
    const userMsg: ChatMessage = { key: 'u' + (++keySeq.current), role: 'user', content: q }
    const asst: ChatMessage = { key: 'a' + (++keySeq.current), role: 'assistant', content: '', streaming: true, steps: [] }
    setMessages((prev) => [...prev, userMsg, asst])
    scroll()
    try {
      const resp = await apiFetch('/api/chat/stream', {
        method: 'POST',
        body: JSON.stringify({ conversation_id: currentId, message: q })
      })
      if (!resp.body) throw new Error('连接失败')
      const reader = resp.body.getReader()
      const decoder = new TextDecoder()
      let buf = ''
      for (;;) {
        const { done, value } = await reader.read()
        if (done) break
        buf += decoder.decode(value, { stream: true })
        let idx
        while ((idx = buf.indexOf('\n\n')) >= 0) {
          const block = buf.slice(0, idx)
          buf = buf.slice(idx + 2)
          const evName = (block.split('\n').find((l) => l.startsWith('event:')) || '').slice(6).trim()
          for (const line of block.split('\n')) {
            if (!line.startsWith('data:')) continue
            let data: Record<string, unknown>
            try {
              data = JSON.parse(line.slice(5).trim())
            } catch {
              continue
            }
            if (data.error) throw new Error((data.message as string) || (data.error as string))
            if (evName === 'step') {
              const kind = data.kind === 'result' ? 'ok' : 'run'
              asst.steps!.push({ kind, text: stepText(data as StepData) })
            } else if (data.delta) {
              asst.content += data.delta as string
            }
            setMessages((prev) => prev.map((m) => (m.key === asst.key ? { ...asst, steps: [...asst.steps!] } : m)))
            scroll()
          }
        }
      }
      asst.streaming = false
      setMessages((prev) => prev.map((m) => (m.key === asst.key ? { ...asst } : m)))
      if (currentId) {
        const acts = await apiJson<AgentAction[]>(`/api/chat/actions?conversation_id=${currentId}`)
        setActions(acts)
      }
      qc.invalidateQueries({ queryKey: ['chat', 'conversations'] })
    } catch (e) {
      asst.content = '出错了：' + (e as Error).message
      asst.streaming = false
      setMessages((prev) => prev.map((m) => (m.key === asst.key ? { ...asst } : m)))
    } finally {
      setSending(false)
      scroll()
    }
  }

  const pendingActions = actions.filter((a) => a.status === 'pending')

  return (
    <div className="flex h-[calc(100vh-8.5rem)] gap-3">
      {/* 会话列表 */}
      <aside className="hidden w-56 shrink-0 flex-col rounded-lg border border-border bg-card md:flex">
        <div className="border-b border-border p-2">
          <Button size="sm" className="w-full" onClick={newConversation}>
            <Plus className="h-3.5 w-3.5" /> 新对话
          </Button>
        </div>
        <ScrollArea className="flex-1">
          <div className="space-y-0.5 p-1.5">
            {(convsQ.data ?? []).map((c) => (
              <div
                key={c.id}
                className={cn(
                  'group flex cursor-pointer items-center gap-1 rounded-md px-2 py-1.5 text-[13px] transition-colors',
                  currentId === c.id ? 'bg-accent-soft text-foreground' : 'text-muted-foreground hover:bg-muted'
                )}
                onClick={() => selectConv(c)}
              >
                <MessageSquare className="h-3.5 w-3.5 shrink-0" />
                <span className="min-w-0 flex-1 truncate">{c.title || '未命名对话'}</span>
                <button
                  className="hidden shrink-0 text-muted-foreground hover:text-foreground group-hover:block"
                  onClick={(e) => {
                    e.stopPropagation()
                    setRenaming(c)
                    setRenameText(c.title || '')
                  }}
                >
                  <Pencil className="h-3 w-3" />
                </button>
                <button
                  className="hidden shrink-0 text-muted-foreground hover:text-destructive group-hover:block"
                  onClick={(e) => {
                    e.stopPropagation()
                    setDeleteConv(c)
                  }}
                >
                  <Trash2 className="h-3 w-3" />
                </button>
              </div>
            ))}
            {!(convsQ.data ?? []).length && (
              <p className="px-2 py-6 text-center text-xs text-muted-foreground">还没有对话</p>
            )}
          </div>
        </ScrollArea>
      </aside>

      {/* 主聊天区 */}
      <div className="flex min-w-0 flex-1 flex-col rounded-lg border border-border bg-card">
        {/* 待确认写操作 */}
        <AnimatePresence>
          {!!pendingActions.length && (
            <motion.div
              initial={{ opacity: 0, height: 0 }}
              animate={{ opacity: 1, height: 'auto' }}
              exit={{ opacity: 0, height: 0 }}
              className="space-y-1.5 overflow-hidden border-b border-warning/40 bg-[rgba(245,158,11,0.08)] px-3 py-2"
            >
              {pendingActions.map((a) => (
                <div key={a.id} className="flex items-center gap-2 text-xs">
                  <Wrench className="h-3.5 w-3.5 text-warning" />
                  <span className="min-w-0 flex-1 truncate">
                    AI 提议：<b>{a.title}</b>
                    {a.detail ? `（${a.detail}）` : ''}
                  </span>
                  <Button size="sm" className="h-6 px-2 text-[11px]" onClick={() => actOn(a, 'confirm')}>
                    <CheckCheck className="h-3 w-3" /> 确认
                  </Button>
                  <Button variant="ghost" size="sm" className="h-6 px-2 text-[11px]" onClick={() => actOn(a, 'cancel')}>
                    <X className="h-3 w-3" /> 取消
                  </Button>
                </div>
              ))}
            </motion.div>
          )}
        </AnimatePresence>

        <div ref={boxRef} className="min-h-0 flex-1 overflow-y-auto px-4 py-4">
          {currentId == null ? (
            <div className="flex h-full flex-col items-center justify-center gap-3 text-sm text-muted-foreground">
              <motion.div
                animate={{ y: [0, -6, 0] }}
                transition={{ duration: 2.4, repeat: Infinity, ease: 'easeInOut' }}
                className="flex h-14 w-14 items-center justify-center rounded-2xl bg-accent-soft text-accent"
              >
                <MessageSquare className="h-6 w-6" />
              </motion.div>
              选择左侧会话，或点「新对话」开始 —— 我可以查数据、写脚本、改配置（写操作会先征求确认）
              <Button size="sm" variant="secondary" onClick={newConversation} className="md:hidden">
                <Plus className="h-3.5 w-3.5" /> 新对话
              </Button>
            </div>
          ) : !messages.length ? (
            <div className="flex h-full items-center justify-center text-sm text-muted-foreground">
              说点什么，比如「今天有什么热点适合我？」
            </div>
          ) : (
            <div className="space-y-4">
              {messages.map((m) => (
                <motion.div
                  key={m.key}
                  initial={{ opacity: 0, y: 10 }}
                  animate={{ opacity: 1, y: 0 }}
                  className={cn('flex', m.role === 'user' ? 'justify-end' : 'justify-start')}
                >
                  <div
                    className={cn(
                      'max-w-[82%] rounded-2xl px-3.5 py-2.5 text-sm leading-relaxed',
                      m.role === 'user' ? 'bg-accent text-accent-foreground' : 'border border-border bg-muted/50'
                    )}
                  >
                    {!!m.steps?.length && (
                      <div className="mb-2 space-y-1 border-b border-border/60 pb-2">
                        {m.steps.map((s, i) => (
                          <div key={i} className="flex items-center gap-1.5 text-[11px] text-muted-foreground">
                            {s.kind === 'ok' ? (
                              <CircleCheck className="h-3 w-3 shrink-0 text-success" />
                            ) : (
                              <LoaderCircle className="h-3 w-3 shrink-0 animate-spin text-accent" />
                            )}
                            <span className="truncate">{s.text}</span>
                          </div>
                        ))}
                      </div>
                    )}
                    {m.role === 'assistant' ? (
                      <>
                        <div className="prose-echo text-[13px]" dangerouslySetInnerHTML={{ __html: md.render(m.content || (m.streaming ? '…' : '')) }} />
                        {!!m.content && !m.streaming && (
                          <button
                            onClick={() => {
                              navigator.clipboard.writeText(m.content)
                              toast.success('已复制')
                            }}
                            className="mt-1 flex items-center gap-1 text-[10px] text-muted-foreground hover:text-foreground"
                          >
                            <Copy className="h-2.5 w-2.5" /> 复制
                          </button>
                        )}
                      </>
                    ) : (
                      <p className="whitespace-pre-wrap">{m.content}</p>
                    )}
                    {m.streaming && !m.content && !m.steps?.length && (
                      <LoaderCircle className="h-4 w-4 animate-spin text-accent" />
                    )}
                  </div>
                </motion.div>
              ))}
            </div>
          )}
        </div>

        <div className="border-t border-border p-3">
          <div className="flex items-end gap-2">
            <textarea
              value={input}
              onChange={(e) => setInput(e.target.value)}
              onKeyDown={(e) => {
                if (e.key === 'Enter' && !e.shiftKey) {
                  e.preventDefault()
                  void send()
                }
              }}
              placeholder={currentId == null ? '先选一个会话' : '输入消息，Enter 发送 / Shift+Enter 换行'}
              disabled={currentId == null || sending}
              rows={2}
              className="min-h-11 flex-1 resize-none rounded-lg border border-input bg-background px-3 py-2.5 text-sm outline-none placeholder:text-muted-foreground/60 focus-visible:ring-2 focus-visible:ring-[var(--ring)] disabled:opacity-60"
            />
            <Button onClick={send} disabled={!input.trim() || sending || currentId == null} className="h-11 w-11 shrink-0">
              {sending ? <LoaderCircle className="h-4 w-4 animate-spin" /> : <Send className="h-4 w-4" />}
            </Button>
          </div>
        </div>
      </div>

      <ConfirmDialog
        open={deleteConv !== null}
        onOpenChange={(v) => !v && setDeleteConv(null)}
        title={`删除对话「${deleteConv?.title || '未命名'}」？`}
        confirmText="删除"
        destructive
        onConfirm={doDeleteConv}
      />
      {renaming && createPortal(
        <div className="fixed inset-0 z-[60] flex items-center justify-center bg-black/45" onClick={() => setRenaming(null)}>
          <div className="w-72 rounded-lg border border-border bg-card p-4 shadow-xl" onClick={(e) => e.stopPropagation()}>
            <p className="mb-2 text-sm font-semibold">重命名对话</p>
            <input
              autoFocus
              value={renameText}
              onChange={(e) => setRenameText(e.target.value)}
              onKeyDown={(e) => e.key === 'Enter' && doRename()}
              className="h-9 w-full rounded-md border border-input bg-background px-3 text-sm outline-none focus-visible:ring-2 focus-visible:ring-[var(--ring)]"
            />
            <div className="mt-3 flex justify-end gap-2">
              <Button variant="ghost" size="sm" onClick={() => setRenaming(null)}>取消</Button>
              <Button size="sm" onClick={doRename}>保存</Button>
            </div>
          </div>
        </div>,
        document.body
      )}
    </div>
  )
}
