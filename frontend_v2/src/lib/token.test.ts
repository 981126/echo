import { describe, it, expect, beforeEach } from 'vitest'
import { getToken, setToken, clearToken } from './token'

describe('token 存储（独立于老前端 echo_token）', () => {
  beforeEach(() => localStorage.clear())

  it('默认空', () => {
    expect(getToken()).toBe('')
  })

  it('set/get/clear 闭环，且使用独立 key', () => {
    setToken('abc')
    expect(getToken()).toBe('abc')
    expect(localStorage.getItem('echo_v2_token')).toBe('abc')
    expect(localStorage.getItem('echo_token')).toBeNull() // 不写老前端的 key
    clearToken()
    expect(getToken()).toBe('')
  })
})
