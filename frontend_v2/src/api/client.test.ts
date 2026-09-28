import { describe, it, expect, beforeEach, vi, afterEach } from 'vitest'
import { apiJson } from './client'
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
