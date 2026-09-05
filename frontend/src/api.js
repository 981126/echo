const TOKEN_KEY = 'echo_token'

export function getToken() {
  return localStorage.getItem(TOKEN_KEY) || ''
}
export function setToken(t) {
  localStorage.setItem(TOKEN_KEY, t)
}
export function clearToken() {
  localStorage.removeItem(TOKEN_KEY)
}

export async function api(path, options = {}) {
  const headers = { 'Content-Type': 'application/json', ...(options.headers || {}) }
  const token = getToken()
  if (token) headers['X-Access-Token'] = token
  const resp = await fetch(path, { ...options, headers })
  if (resp.status === 401) {
    clearToken()
    if (!location.hash.startsWith('#/login')) location.hash = '#/login'
    throw new Error('未登录或令牌失效')
  }
  if (!resp.ok) {
    let detail = resp.statusText
    try {
      const j = await resp.json()
      detail = j.detail || detail
    } catch { /* ignore */ }
    throw new Error(detail)
  }
  if (resp.status === 204) return null
  return resp.json()
}

async function uploadFile(path, file) {
  const fd = new FormData()
  fd.append('file', file)
  const headers = {}
  const token = getToken()
  if (token) headers['X-Access-Token'] = token
  const resp = await fetch(path, { method: 'POST', headers, body: fd })
  if (!resp.ok) {
    let detail = resp.statusText
    try {
      const j = await resp.json()
      detail = j.detail || detail
    } catch { /* ignore */ }
    throw new Error(detail)
  }
  return resp.json()
}

export function uploadVideo(file) {
  return uploadFile('/api/videos/upload', file)
}

export function uploadVideoFile(videoId, file) {
  return uploadFile(`/api/videos/${videoId}/video`, file)
}

export function uploadCover(videoId, file) {
  return uploadFile(`/api/videos/${videoId}/cover`, file)
}

export function uploadImage(file) {
  return uploadFile('/api/uploads/image', file)
}
