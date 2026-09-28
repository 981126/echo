import { describe, it, expect } from 'vitest'
import { DEFAULT_FILTERS, buildLibraryQuery, coverThumb, type Filters } from './types'

// R-179：合并去重/筛选已搬到服务端（见 backend/tests/test_r179_library.py），
// 前端只负责这两件事——「筛选 → 查询串」与「封面 → 缩略图 URL」。
describe('buildLibraryQuery（筛选下推服务端）', () => {
  it('默认：只带 limit，不带空参数', () => {
    const qs = new URLSearchParams(buildLibraryQuery(DEFAULT_FILTERS, ''))
    expect(qs.get('limit')).toBe('20')
    expect([...qs.keys()].sort()).toEqual(['limit'])
  })

  it('把筛选条件全部翻译成查询参数（多选平台/标签用重复参数）', () => {
    const f: Filters = {
      ...DEFAULT_FILTERS,
      creatorId: 3,
      platforms: ['douyin', 'bilibili'],
      tags: ['求职', '面试'],
      status: 'published',
      video: 'yes',
      ad: 'no',
      kw: '  面试  ',
      likesMin: 100,
      likesMax: 900
    }
    const qs = new URLSearchParams(buildLibraryQuery(f, 'CURSOR'))
    expect(qs.getAll('platforms')).toEqual(['douyin', 'bilibili'])
    expect(qs.getAll('tags')).toEqual(['求职', '面试'])
    expect(qs.get('creator_id')).toBe('3')
    expect(qs.get('status')).toBe('published')
    expect(qs.get('video')).toBe('yes')
    expect(qs.get('ad')).toBe('no')
    expect(qs.get('kw')).toBe('面试') // 去掉首尾空格
    expect(qs.get('likes_min')).toBe('100')
    expect(qs.get('likes_max')).toBe('900')
    expect(qs.get('cursor')).toBe('CURSOR')
  })

  it('不带游标时不发 cursor（首屏）', () => {
    expect(new URLSearchParams(buildLibraryQuery(DEFAULT_FILTERS, '')).has('cursor')).toBe(false)
  })
})

describe('coverThumb（封面缩略图）', () => {
  it('本地 /covers 走缩略图参数', () => {
    expect(coverThumb('/covers/abc.jpg', 400)).toBe('/covers/abc.jpg?w=400')
    expect(coverThumb('/covers/带中文 名.jpg', 800)).toBe('/covers/带中文 名.jpg?w=800')
  })

  it('远端图/空值原样返回（不硬套参数）', () => {
    expect(coverThumb('https://cdn.example.com/a.jpg', 400)).toBe('https://cdn.example.com/a.jpg')
    expect(coverThumb('', 400)).toBe('')
    expect(coverThumb(null, 400)).toBe('')
  })
})
