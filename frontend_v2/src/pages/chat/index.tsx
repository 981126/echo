import { useEffect, useRef, useState, type ReactNode } from 'react'
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
import { useBackToClose } from '@/hooks/use-back-to-close'
import { useVisualViewportHeight } from '@/hooks/use-visual-viewport'
import { useCoarsePointer, useMediaQuery } from '@/hooks/use-media-query'
import { Button } from '@/components/ui/button'
import { ScrollArea } from '@/components/ui/scroll-area'
import { ConfirmDialog } from '@/components/ui/confirm-dialog'
import { toast } from '@/components/ui/toaster'

const md = new MarkdownIt({ html: false, linkify: true })

/** 距底部不超过这个像素数就认为「贴着最新」，流式输出时自动跟随（用户向上翻历史则不抢滚动条） */
const NEAR_BOTTOM_PX = 80

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

// R-167：错误消息健壮提取——后端错误帧可能是字符串/对象/数组，统一转成可读文本（修「出错了：[object Object]」）
export function errText(v: unknown): string {
  if (v == null) return ''
  if (typeof v === 'string') return v
  if (Array.isArray(v)) return v.map(errText).filter(Boolean).join('；')
  if (typeof v === 'object') {
    const o = v as Record<string, unknown>
    if (typeof o.message === 'string') return o.message
    if (typeof o.detail === 'string') return o.detail
    if (o.error != null) return errText(o.error)
    try {
      return JSON.stringify(o)
    } catch {
      return String(v)
    }
  }
  return String(v)
}

interface ConversationListProps {
  items: Conversation[]
  currentId: number | null
  onSelect: (c: Conversation) => void
  onNew: () => void
  onRename: (c: Conversation) => void
  onDelete: (c: Conversation) => void
  footer?: ReactNode
}

// R-218：会话列表抽成组件——桌面侧栏与手机「会话」Sheet 共用；手机端重命名/删除不再依赖 hover。
function ConversationList({ items, currentId, onSelect, onNew, onRename, onDelete, footer }: ConversationListProps) {
  return (
    <div className="flex h-full min-h-0 flex-col">
      <div className="border-b border-border p-2">
        <Button size="sm" className="w-full" onClick={onNew}>
          <Plus className="h-3.5 w-3.5" /> 新对话
        </Button>
      </div>
      <ScrollArea className="min-h-0 flex-1">
        <div className="space-y-0.5 p-1.5">
          {items.map((c) => (
            <div
              key={c.id}
              className={cn(
                'group flex cursor-pointer items-center gap-1 rounded-md px-2 py-1.5 text-[13px] transition-colors',
                currentId === c.id ? 'bg-accent-soft text-foreground' : 'text-muted-foreground hover:bg-muted'
              )}
              onClick={() => onSelect(c)}
            >
              <MessageSquare className="h-3.5 w-3.5 shrink-0" />
              <span className="min-w-0 flex-1 truncate">{c.title || '未命名对话'}</span>
              <button
                aria-label="重命名对话"
                className="flex h-11 w-11 shrink-0 items-center justify-center rounded-md text-muted-foreground hover:text-foreground md:h-6 md:w-6 md:opacity-0 md:group-hover:opacity-100"
                onClick={(e) => {
                  e.stopPropagation()
                  onRename(c)
                }}
              >
                <Pencil className="h-3.5 w-3.5" />
              </button>
              <button
                aria-label="删除对话"
                className="flex h-11 w-11 shrink-0 items-center justify-center rounded-md text-muted-foreground hover:text-destructive md:h-6 md:w-6 md:opacity-0 md:group-hover:opacity-100"
                onClick={(e) => {
                  e.stopPropagation()
                  onDelete(c)
                }}
              >
                <Trash2 className="h-3.5 w-3.5" />
              </button>
            </div>
          ))}
          {!items.length && <p className="px-2 py-6 text-center text-xs text-muted-foreground">还没有对话</p>}
        </div>
      </ScrollArea>
      {footer}
    </div>
  )
}

export default function ChatPage() {
  const qc = useQueryClient()
  const [currentId, setCurrentId] = useState<number | null>(null)
  const [messages, setMessages] = useState<ChatMessage[]>([])
  const [input, setInput] = useState('')
  const [sending, setSending] = useState(false)
  const [mode, setMode] = useState('ops')
  const [actions, setActions] = useState<AgentAction[]>([])
  const [deleteConv, setDeleteConv] = useState<Conversation | null>(null)
  const [renaming, setRenaming] = useState<Conversation | null>(null)
  const [renameText, setRenameText] = useState('')
  const [historyOpen, setHistoryOpen] = useState(false)
  const isMobile = useMediaQuery('(max-width: 767px)')
  const coarse = useCoarsePointer()
  const vvHeight = useVisualViewportHeight()
  const boxRef = useRef<HTMLDivElement>(null)
  const keySeq = useRef(0)
  const loadSeq = useRef(0) // R-243：会话加载序号，快速切换时丢弃过期响应
  const scrollRaf = useRef(0) // R-243：scroll() 每帧最多一次
  const flushRaf = useRef(0) // R-243：流式 chunk 合并到每帧最多一次 setState
  const stickToBottom = useRef(true)

  const convsQ = useQuery({
    queryKey: ['chat', 'conversations'],
    queryFn: () => apiJson<Conversation[]>('/api/chat/conversations')
  })

  /** R-243：滚动合并到「每帧最多一次」，且仅在接近底部时跟随最新（向上翻历史不被拽回）。 */
  const scroll = (force = false) => {
    if (force) stickToBottom.current = true
    if (scrollRaf.current) return
    scrollRaf.current = requestAnimationFrame(() => {
      scrollRaf.current = 0
      const el = boxRef.current
      if (!el || !stickToBottom.current) return
      el.scrollTop = el.scrollHeight
    })
  }

  const onMessagesScroll = () => {
    const el = boxRef.current
    if (!el) return
    stickToBottom.current = el.scrollHeight - el.scrollTop - el.clientHeight <= NEAR_BOTTOM_PX
  }

  useEffect(
    () => () => {
      if (scrollRaf.current) cancelAnimationFrame(scrollRaf.current)
      if (flushRaf.current) cancelAnimationFrame(flushRaf.current)
    },
    []
  )

  async function loadHistory(id: number) {
    const seq = ++loadSeq.current
    try {
      // R-243：history 与 actions 无数据依赖 → 并行请求；快速切会话时用序号守卫丢弃过期响应，
      // 不在响应回来前清空旧消息（避免视觉跳变/串会话）。
      const [rows, acts] = await Promise.all([
        apiJson<{ role: string; content: string }[]>(`/api/chat/history?conversation_id=${id}&limit=200`),
        apiJson<AgentAction[]>(`/api/chat/actions?conversation_id=${id}`)
      ])
      if (seq !== loadSeq.current) return // 过期响应：保留当前会话的内容
      setMessages(rows.map((r) => ({ key: 'h' + (++keySeq.current), role: r.role as 'user' | 'assistant', content: r.content })))
      setActions(acts)
    } catch (e) {
      if (seq !== loadSeq.current) return
      toast.error((e as Error).message)
    }
    scroll(true)
  }

  async function selectConv(c: Conversation) {
    setCurrentId(c.id)
    stickToBottom.current = true
    await loadHistory(c.id)
  }

  async function newConversation() {
    const c = await apiJson<Conversation>('/api/chat/conversations', { method: 'POST', body: '{}' })
    qc.invalidateQueries({ queryKey: ['chat', 'conversations'] })
    loadSeq.current += 1 // 丢弃可能还在飞的旧会话加载
    stickToBottom.current = true
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
      loadSeq.current += 1 // 丢弃可能还在飞的旧会话加载
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
    stickToBottom.current = true
    scroll(true)
    // R-243：后端 ~66 chunk/s；累积 delta/steps 后用 rAF 合并成「每帧最多一次 setState」，
    // 最终文本逐字一致（流结束前会同步 flush 一次再落 streaming=false）。
    let dirty = false
    const flushPending = () => {
      if (flushRaf.current) {
        cancelAnimationFrame(flushRaf.current)
        flushRaf.current = 0
      }
      if (!dirty) return
      dirty = false
      setMessages((prev) => prev.map((m) => (m.key === asst.key ? { ...asst, steps: [...(asst.steps || [])] } : m)))
      scroll()
    }
    const scheduleFlush = () => {
      dirty = true
      if (flushRaf.current) return
      flushRaf.current = requestAnimationFrame(() => {
        flushRaf.current = 0
        if (!dirty) return
        dirty = false
        setMessages((prev) => prev.map((m) => (m.key === asst.key ? { ...asst, steps: [...(asst.steps || [])] } : m)))
        scroll()
      })
    }
    try {
      const resp = await apiFetch('/api/chat/stream', {
        method: 'POST',
        // R-176：必须显式声明 JSON，否则 fetch 默认 text/plain，FastAPI 解析不出 body → 422
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ conversation_id: currentId, message: q, mode })
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
            // event: error 帧才是致命错误；普通帧里的 error 字段不误判
            if (evName === 'error' || data.error) {
              throw new Error(errText(data.message) || errText(data.error) || '未知错误')
            }
            if (evName === 'step') {
              const kind = data.kind === 'result' ? 'ok' : 'run'
              asst.steps!.push({ kind, text: stepText(data as StepData) })
            } else if (data.delta) {
              asst.content += data.delta as string
            }
            scheduleFlush()
          }
        }
      }
      flushPending()
      asst.streaming = false
      setMessages((prev) => prev.map((m) => (m.key === asst.key ? { ...asst } : m)))
      if (currentId) {
        const acts = await apiJson<AgentAction[]>(`/api/chat/actions?conversation_id=${currentId}`)
        setActions(acts)
      }
      qc.invalidateQueries({ queryKey: ['chat', 'conversations'] })
    } catch (e) {
      flushPending() // 清掉未落地的 rAF，错误文本直接走终态 setState
      asst.content = '出错了：' + (e as Error).message
      asst.streaming = false
      setMessages((prev) => prev.map((m) => (m.key === asst.key ? { ...asst } : m)))
    } finally {
      setSending(false)
      scroll()
    }
  }

  const pendingActions = actions.filter((a) => a.status === 'pending')
  const currentTitle = (convsQ.data ?? []).find((c) => c.id === currentId)?.title
  // R-218：移动端用 visualViewport 高度兜底键盘；桌面维持原 100vh 计算不变。
  // 移动端：减去 header 56 + 页面 py 48 + 底部 Tab 56 + 手机会话入口约 52 + 安全余量
  const mobileHeight = Math.max(280, vvHeight - 56 - 48 - 56 - 52 - 8)
  const heightStyle = isMobile ? { height: mobileHeight } : undefined

  return (
    <div className="flex min-h-0 flex-col">
      {/* R-218：移动端会话入口（桌面侧栏在手机上隐藏） */}
      <div className="mb-2 flex items-center gap-2 md:hidden">
        <Button variant="secondary" size="sm" onClick={() => setHistoryOpen(true)} aria-label="打开历史会话">
          <MessageSquare className="h-4 w-4" /> 会话
        </Button>
        <span className="min-w-0 flex-1 truncate text-xs text-muted-foreground">{currentTitle || '未选择会话'}</span>
        <Button size="sm" onClick={newConversation}>
          <Plus className="h-4 w-4" /> 新对话
        </Button>
      </div>

      <div className="flex gap-3 md:min-h-0 md:flex-1 md:h-[calc(100vh-8.5rem)]" style={heightStyle}>
      {/* 会话列表（桌面侧栏；移动端收进「会话」Sheet） */}
      <aside className="hidden w-56 shrink-0 flex-col overflow-hidden rounded-lg border border-border bg-card md:flex">
        <ConversationList
          items={convsQ.data ?? []}
          currentId={currentId}
          onSelect={selectConv}
          onNew={newConversation}
          onRename={(c) => {
            setRenaming(c)
            setRenameText(c.title || '')
          }}
          onDelete={setDeleteConv}
        />
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
                  <Button size="sm" className="h-6 px-2 text-xs md:text-[11px]" onClick={() => actOn(a, 'confirm')}>
                    <CheckCheck className="h-3 w-3" /> 确认
                  </Button>
                  <Button variant="ghost" size="sm" className="h-6 px-2 text-xs md:text-[11px]" onClick={() => actOn(a, 'cancel')}>
                    <X className="h-3 w-3" /> 取消
                  </Button>
                </div>
              ))}
            </motion.div>
          )}
        </AnimatePresence>

        <div ref={boxRef} onScroll={onMessagesScroll} className="min-h-0 flex-1 overflow-y-auto px-4 py-4">
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
                          <div key={i} className="flex items-center gap-1.5 text-xs md:text-[11px] text-muted-foreground">
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
                            className="mt-1 flex items-center gap-1 text-xs md:text-[10px] text-muted-foreground hover:text-foreground"
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
          <div className="mb-2 flex items-center gap-1.5">
            <span className="text-xs text-muted-foreground">对话模式</span>
            {[
              { key: 'ops', label: '运营分析' },
              { key: 'create', label: '创作共创' }
            ].map((m) => (
              <button
                key={m.key}
                onClick={() => setMode(m.key)}
                className={
                  'cursor-pointer rounded-md border px-2 py-0.5 text-xs transition-colors ' +
                  (mode === m.key ? 'border-accent bg-accent-soft text-accent' : 'border-border text-muted-foreground hover:text-foreground')
                }
              >
                {m.label}
              </button>
            ))}
          </div>
          <div className="flex items-end gap-2">
            <textarea
              value={input}
              onChange={(e) => setInput(e.target.value)}
              onKeyDown={(e) => {
                // R-218：触屏上回车=换行（手机键盘不要误发送），发送用按钮；桌面保持回车发送。
                if (e.key === 'Enter' && !e.shiftKey && !coarse) {
                  e.preventDefault()
                  void send()
                }
              }}
              placeholder={currentId == null ? '先选一个会话' : coarse ? '输入消息，点右侧按钮发送' : '输入消息，Enter 发送 / Shift+Enter 换行'}
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
      </div>

      <MobileHistorySheet open={historyOpen} onOpenChange={setHistoryOpen}>
        <ConversationList
          items={convsQ.data ?? []}
          currentId={currentId}
          onSelect={(c) => {
            selectConv(c)
            setHistoryOpen(false)
          }}
          onNew={() => {
            newConversation()
            setHistoryOpen(false)
          }}
          onRename={(c) => {
            setHistoryOpen(false)
            setRenaming(c)
            setRenameText(c.title || '')
          }}
          onDelete={(c) => {
            setHistoryOpen(false)
            setDeleteConv(c)
          }}
        />
      </MobileHistorySheet>

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

interface MobileHistorySheetProps {
  open: boolean
  onOpenChange: (open: boolean) => void
  children: ReactNode
}

// R-218：手机会话 Sheet（受控 animate + 延迟卸载，保证退出动画；返回键先关）
function MobileHistorySheet({ open, onOpenChange, children }: MobileHistorySheetProps) {
  const [mounted, setMounted] = useState(open)
  const close = () => onOpenChange(false)
  useBackToClose(open, close)
  useEffect(() => {
    if (open) {
      setMounted(true)
      return
    }
    if (!mounted) return
    const timer = window.setTimeout(() => setMounted(false), 320)
    return () => window.clearTimeout(timer)
  }, [open, mounted])
  useEffect(() => {
    if (!open) return
    const onKey = (e: KeyboardEvent) => {
      if (e.key === 'Escape') close()
    }
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  }, [open])
  if (!mounted) return null
  return createPortal(
    <>
      <motion.div
        initial={{ opacity: 0 }}
        animate={{ opacity: open ? 1 : 0 }}
        transition={{ duration: 0.2 }}
        style={{ pointerEvents: open ? 'auto' : 'none' }}
        className="fixed inset-0 z-50 bg-black/45 md:hidden"
        onClick={close}
      />
      <motion.div
        role="dialog"
        aria-modal="true"
        aria-label="历史会话"
        initial={{ y: '100%' }}
        animate={{ y: open ? 0 : '100%' }}
        transition={{ type: 'spring', stiffness: 360, damping: 36 }}
        style={{ pointerEvents: open ? 'auto' : 'none' }}
        className="fixed inset-x-0 bottom-0 z-50 flex h-[75dvh] flex-col rounded-t-2xl border-t border-border bg-card shadow-2xl md:hidden"
      >
        <div className="mx-auto mt-2 h-1 w-10 rounded-full bg-border" aria-hidden />
        <div className="flex items-center justify-between px-4 pb-2 pt-3">
          <h2 className="text-sm font-semibold">历史会话</h2>
          <button
            type="button"
            onClick={close}
            aria-label="关闭"
            className="flex h-11 w-11 items-center justify-center rounded-md text-muted-foreground hover:bg-muted"
          >
            <X className="h-4 w-4" />
          </button>
        </div>
        <div className="flex min-h-0 flex-1 flex-col overflow-hidden pb-[env(safe-area-inset-bottom)]">{children}</div>
      </motion.div>
    </>
    ,
    document.body
  )
}
