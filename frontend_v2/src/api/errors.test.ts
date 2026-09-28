import { describe, it, expect } from 'vitest'
import { detailText } from './client'
import { errText } from '@/pages/chat'

describe('R-167 错误消息提取（修「出错了：[object Object]」）', () => {
  it('字符串原样返回', () => {
    expect(detailText('会话不存在', 'x')).toBe('会话不存在')
    expect(errText('没有拿到回答')).toBe('没有拿到回答')
  })

  it('对象/嵌套/数组转可读文本', () => {
    expect(detailText({ detail: '无效' }, 'x')).toBe('无效')
    expect(errText({ message: '模型超时' })).toBe('模型超时')
    expect(errText({ error: { message: '嵌套错误' } })).toBe('嵌套错误')
    // FastAPI 422：detail 为对象数组
    expect(detailText([{ msg: '字段必填' }, { msg: '类型错误' }], 'x')).toBe('字段必填；类型错误')
    // 未知对象兜底 JSON 而不是 [object Object]
    expect(errText({ code: 500 })).toBe('{"code":500}')
    expect(errText({ code: 500 })).not.toContain('[object Object]')
  })

  it('空值兜底', () => {
    expect(detailText(null, 'fallback')).toBe('fallback')
    expect(errText(undefined)).toBe('')
  })
})
