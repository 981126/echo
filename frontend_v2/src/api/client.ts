// 统一 API 客户端：openapi-fetch + 鉴权/401/错误归一
import createClient, { type Middleware } from 'openapi-fetch'
import type { paths } from './schema'
import { getToken, clearToken } from '@/lib/token'

export class ApiError extends Error {
  status: number
  constructor(status: number, message: string) {
    super(message)
    this.status = status
  }
}

// R-167：后端 detail 可能是字符串/对象/数组（如 422 校验错误），统一转可读文本
export function detailText(v: unknown, fallback: string): string {
  if (v == null) return fallback
  if (typeof v === 'string') return v
  if (Array.isArray(v)) {
    const parts = v.map((x) => detailText(x, '')).filter(Boolean)
    return parts.join('；') || fallback
  }
  if (typeof v === 'object') {
    const o = v as Record<string, unknown>
    if (typeof o.message === 'string') return o.message
    if (typeof o.msg === 'string') return o.msg
    if (typeof o.detail === 'string') return o.detail
    try {
      return JSON.stringify(o)
    } catch {
      return fallback
    }
  }
  return String(v)
}

const authMiddleware: Middleware = {
  async onRequest({ request }) {
    const token = getToken()
    if (token) request.headers.set('X-Access-Token', token)
    return request
  },
  async onResponse({ response }) {
    if (response.status === 401) {
      clearToken()
      if (!location.hash.startsWith('#/login')) location.hash = '#/login'
      throw new ApiError(401, '未登录或令牌失效')
    }
    if (!response.ok) {
      let detail = response.statusText
      try {
        const j = await response.clone().json()
        detail = detailText((j as { detail?: unknown }).detail, detail)
      } catch {
        /* ignore */
      }
      throw new ApiError(response.status, detail)
    }
    return response
  }
}

export const api = createClient<paths>({ baseUrl: '' })
api.use(authMiddleware)

// 兼容上传等手写场景：带鉴权的 fetch
export async function apiFetch(path: string, init: RequestInit = {}): Promise<Response> {
  const headers = new Headers(init.headers)
  const token = getToken()
  if (token) headers.set('X-Access-Token', token)
  // R-176 兜底：字符串 body 一律按 JSON 发送。fetch 对字符串默认 text/plain，后端（FastAPI）
  // 解析不出 JSON body 会回 422「Input should be a valid dictionary or object to extract fields from」。
  // 调用方显式指定的 Content-Type（如 text/plain）不覆盖；FormData 由浏览器自带 boundary，不动。
  if (!headers.has('Content-Type') && typeof init.body === 'string') {
    headers.set('Content-Type', 'application/json')
  }
  const resp = await fetch(path, { ...init, headers })
  if (resp.status === 401) {
    clearToken()
    if (!location.hash.startsWith('#/login')) location.hash = '#/login'
    throw new ApiError(401, '未登录或令牌失效')
  }
  if (!resp.ok) {
    let detail = resp.statusText
    try {
      const j = await resp.clone().json()
      detail = detailText((j as { detail?: unknown }).detail, detail)
    } catch {
      /* ignore */
    }
    throw new ApiError(resp.status, detail)
  }
  return resp
}

export async function apiJson<T>(path: string, init: RequestInit = {}): Promise<T> {
  const resp = await apiFetch(path, {
    ...init,
    headers: { 'Content-Type': 'application/json', ...(init.headers || {}) }
  })
  if (resp.status === 204) return null as T
  return resp.json() as Promise<T>
}

export async function uploadFile<T = Record<string, unknown>>(path: string, file: File): Promise<T> {
  const fd = new FormData()
  fd.append('file', file)
  const resp = await apiFetch(path, { method: 'POST', body: fd })
  return resp.json() as Promise<T>
}
