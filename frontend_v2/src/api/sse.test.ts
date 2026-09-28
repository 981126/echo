import { describe, it, expect } from 'vitest'
import { parseSseBlock } from './sse'

describe('parseSseBlock', () => {
  it('解析 data: 帧为事件对象', () => {
    const block = 'data: {"type":"task.update","data":{"id":1,"status":"done"}}'
    const ev = parseSseBlock(block)
    expect(ev?.type).toBe('task.update')
    expect((ev?.data as { id: number }).id).toBe(1)
  })

  it('忽略非 data 行与坏帧', () => {
    expect(parseSseBlock(': comment')).toBeNull()
    expect(parseSseBlock('data: {bad json')).toBeNull()
    expect(parseSseBlock('event: ping')).toBeNull()
  })
})
