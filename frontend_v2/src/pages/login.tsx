import { useState, type FormEvent } from 'react'
import { useNavigate } from 'react-router-dom'
import { motion } from 'framer-motion'
import { Waves, ArrowRight, LoaderCircle } from 'lucide-react'
import { setToken } from '@/lib/token'
import { apiJson } from '@/api/client'
import { Button } from '@/components/ui/button'
import { EASE_OUT_EXPO } from '@/lib/motion'

export default function LoginPage() {
  const [value, setValue] = useState('')
  const [error, setError] = useState('')
  const [loading, setLoading] = useState(false)
  const navigate = useNavigate()

  async function submit(e: FormEvent) {
    e.preventDefault()
    const token = value.trim()
    if (!token || loading) return
    setLoading(true)
    setError('')
    try {
      setToken(token)
      await apiJson('/api/notifications/unread-count') // 验证 token 有效
      navigate('/home', { replace: true })
    } catch {
      setError('令牌无效，请检查后重试')
      setLoading(false)
    }
  }

  return (
    <div className="relative flex min-h-full items-center justify-center overflow-hidden bg-background">
      {/* 背景光斑（表现力：缓慢漂移） */}
      <motion.div
        aria-hidden
        className="pointer-events-none absolute -top-40 left-1/2 h-[480px] w-[720px] -translate-x-1/2 rounded-full bg-accent/15 blur-3xl"
        animate={{ y: [0, 30, 0], scale: [1, 1.06, 1] }}
        transition={{ duration: 9, repeat: Infinity, ease: 'easeInOut' }}
      />
      <motion.div
        aria-hidden
        className="pointer-events-none absolute -bottom-48 -left-32 h-[380px] w-[380px] rounded-full bg-[rgba(16,185,129,0.10)] blur-3xl"
        animate={{ y: [0, -24, 0] }}
        transition={{ duration: 11, repeat: Infinity, ease: 'easeInOut' }}
      />

      <motion.div
        initial={{ opacity: 0, y: 24, filter: 'blur(6px)' }}
        animate={{ opacity: 1, y: 0, filter: 'blur(0px)' }}
        transition={{ duration: 0.6, ease: EASE_OUT_EXPO }}
        className="relative z-10 w-[min(400px,92vw)]"
      >
        <div className="mb-8 flex flex-col items-center gap-3 text-center">
          <motion.div
            initial={{ scale: 0.6, rotate: -12 }}
            animate={{ scale: 1, rotate: 0 }}
            transition={{ type: 'spring', stiffness: 260, damping: 18, delay: 0.1 }}
            className="flex h-14 w-14 items-center justify-center rounded-2xl bg-accent text-accent-foreground shadow-lg"
          >
            <Waves className="h-7 w-7" />
          </motion.div>
          <motion.h1
            initial={{ opacity: 0, y: 8 }}
            animate={{ opacity: 1, y: 0 }}
            transition={{ delay: 0.22, duration: 0.5, ease: EASE_OUT_EXPO }}
            className="text-2xl font-semibold tracking-tight"
          >
            echo 回声
          </motion.h1>
          <motion.p
            initial={{ opacity: 0 }}
            animate={{ opacity: 1 }}
            transition={{ delay: 0.34, duration: 0.5 }}
            className="text-sm text-muted-foreground"
          >
            让 AI 越来越懂你的人设
          </motion.p>
        </div>

        <motion.form
          onSubmit={submit}
          initial={{ opacity: 0, y: 12 }}
          animate={{ opacity: 1, y: 0 }}
          transition={{ delay: 0.4, duration: 0.5, ease: EASE_OUT_EXPO }}
          className="rounded-xl border border-border bg-card/80 p-5 shadow-[var(--shadow-card)] backdrop-blur"
        >
          <label className="mb-2 block text-xs font-medium text-muted-foreground">访问令牌</label>
          <input
            type="password"
            value={value}
            onChange={(e) => setValue(e.target.value)}
            placeholder="输入 ECHO_ACCESS_TOKEN"
            autoFocus
            className="h-10 w-full rounded-md border border-input bg-background px-3 text-sm outline-none transition-shadow placeholder:text-muted-foreground/60 focus-visible:ring-2 focus-visible:ring-[var(--ring)]"
          />
          {error && (
            <motion.p
              initial={{ opacity: 0, y: -4 }}
              animate={{ opacity: 1, y: 0 }}
              className="mt-2 text-xs text-destructive"
            >
              {error}
            </motion.p>
          )}
          <Button type="submit" className="mt-4 w-full" size="lg" disabled={!value.trim() || loading}>
            {loading ? <LoaderCircle className="h-4 w-4 animate-spin" /> : <ArrowRight className="h-4 w-4" />}
            {loading ? '验证中…' : '进入工作台'}
          </Button>
        </motion.form>

        <motion.p
          initial={{ opacity: 0 }}
          animate={{ opacity: 1 }}
          transition={{ delay: 0.6 }}
          className="mt-6 text-center text-xs text-muted-foreground/70"
        >
          echo v2 · 全新界面预览
        </motion.p>
      </motion.div>
    </div>
  )
}
