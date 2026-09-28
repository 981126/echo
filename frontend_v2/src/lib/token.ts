// 登录态：独立于老前端（老前端用 echo_token），互不干扰
const TOKEN_KEY = 'echo_v2_token'

export function getToken(): string {
  return localStorage.getItem(TOKEN_KEY) || ''
}

export function setToken(t: string) {
  localStorage.setItem(TOKEN_KEY, t)
}

export function clearToken() {
  localStorage.removeItem(TOKEN_KEY)
}
