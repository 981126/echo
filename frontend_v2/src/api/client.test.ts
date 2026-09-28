import { describe, it, expect, beforeEach, vi, afterEach } from 'vitest'
import { apiFetch, apiJson } from './client'
import { setToken, getToken } from '@/lib/token'

const mockFetch = vi.fn()
vi.stubGlobal('fetch', mockFetch)

function jsonResponse(status: number, body: unknown) {
  return new Response(JSON.stringify(body), {
    status,
    headers: { 'Content-Type': 'application/json' }
  })
}

describe('apiJson', () => {
  beforeEach(() => {
    localStorage.clear()
    mockFetch.mockReset()
    location.hash = ''
  })
  afterEach(() => vi.clearAllMocks())

  it('带鉴权头发起请求并解析 JSON', async () => {
    setToken('t-123')
    mockFetch.mockResolvedValueOnce(jsonResponse(200, { ok: true }))
    const data = await apiJson<{ ok: boolean }>('/api/x')
    expect(data.ok).toBe(true)
    const req = mockFetch.mock.calls[0][1] as RequestInit
    expect((req.headers as Headers).get('X-Access-Token')).toBe('t-123')
  })

  it('非 2xx 抛出后端 detail 消息', async () => {
    mockFetch.mockResolvedValueOnce(jsonResponse(400, { detail: '请先创建主博主' }))
    await expect(apiJson('/api/x')).rejects.toThrow('请先创建主博主')
  })

  it('401 清除 token 并跳转登录', async () => {
    setToken('expired')
    mockFetch.mockResolvedValueOnce(jsonResponse(401, { detail: 'unauthorized' }))
    await expect(apiJson('/api/x')).rejects.toThrow('未登录或令牌失效')
    expect(getToken()).toBe('')
    expect(location.hash).toBe('#/login')
  })
})

// R-176：AI 对话报 422「Input should be a valid dictionary or object to extract fields from」的根因是
// 字符串 body 没带 JSON Content-Type（fetch 默认 text/plain）。以下两条锁死这条规则。
describe('apiFetch Content-Type', () => {
  beforeEach(() => {
    localStorage.clear()
    mockFetch.mockReset()
    location.hash = ''
  })
  afterEach(() => vi.clearAllMocks())

  function sentHeaders() {
    return (mockFetch.mock.calls[0][1] as RequestInit).headers as Headers
  }

  it('字符串 body 兜底为 application/json（后端能解析出 dict）', async () => {
    mockFetch.mockResolvedValueOnce(jsonResponse(200, {}))
    await apiFetch('/api/chat/stream', { method: 'POST', body: JSON.stringify({ message: 'hi' }) })
    expect(sentHeaders().get('Content-Type')).toBe('application/json')
  })

  it('调用方显式指定的 Content-Type 不被覆盖', async () => {
    mockFetch.mockResolvedValueOnce(jsonResponse(200, {}))
    await apiFetch('/api/x', { method: 'POST', headers: { 'Content-Type': 'text/plain' }, body: 'plain' })
    expect(sentHeaders().get('Content-Type')).toBe('text/plain')
  })

  it('FormData body 不设 Content-Type（浏览器自带 boundary）', async () => {
    mockFetch.mockResolvedValueOnce(jsonResponse(200, {}))
    await apiFetch('/api/uploads', { method: 'POST', body: new FormData() })
    expect(sentHeaders().has('Content-Type')).toBe(false)
  })
})
