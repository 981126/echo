import { describe, it, expect } from 'vitest'
import { buildCards, applyFiltersTo, DEFAULT_FILTERS, type VideoItem, type WorkItem } from './types'

const video = (over: Partial<VideoItem> = {}): VideoItem => ({
  id: 1,
  filename: 'a.mp4',
  title: '本地素材',
  platforms: ['douyin'],
  status: 'published',
  is_ad: false,
  main_topics: ['求职'],
  tags: ['简历'],
  tags_confirmed: true,
  created_at: '2026-09-01T00:00:00',
  published_at: '2026-09-10T00:00:00',
  ...over
})

const work = (over: Partial<WorkItem> = {}): WorkItem => ({
  id: 7,
  type: 'work',
  title: '云端合并',
  cover: '/covers/x.jpg',
  platforms: ['douyin', 'bilibili'],
  posts: [
    { id: 71, platform: 'douyin', publish_time: '2026-09-12T00:00:00', latest_stat: { likes: 500 } },
    { id: 72, platform: 'bilibili', publish_time: '2026-09-12T00:00:00' }
  ],
  ...over
})

describe('buildCards', () => {
  it('本地 + 云端合一，按日期倒序；占位文件不算有视频', () => {
    const cards = buildCards([video()], [work()])
    expect(cards.map((c) => c.key)).toEqual(['w7', 'v1']) // 云端 9-12 在前
    const local = cards.find((c) => c.kind === 'local')!
    expect(local.hasVideo).toBe(true)
    const cloud = cards.find((c) => c.kind === 'cloud')!
    expect(cloud.merged).toBe(2)
    expect(cloud.hasVideo).toBe(false)
  })

  it('云端已绑定本地的素材不重复展示本地卡', () => {
    const w = work()
    w.posts![0].local_video_id = 1
    const cards = buildCards([video()], [w])
    expect(cards).toHaveLength(1)
    expect(cards[0].kind).toBe('cloud')
    expect(cards[0].local_video_id).toBe(1)
  })
})

describe('applyFiltersTo', () => {
  const cards = buildCards([video(), video({ id: 2, title: '广告片', is_ad: true, filename: '' })], [work()])

  it('关键词/广告/点赞区间过滤', () => {
    expect(applyFiltersTo(cards, { ...DEFAULT_FILTERS, kw: '广告' })).toHaveLength(1)
    expect(applyFiltersTo(cards, { ...DEFAULT_FILTERS, ad: 'ad' })).toHaveLength(1)
    // 云端作品 likes=500；本地无云端帖不计
    expect(applyFiltersTo(cards, { ...DEFAULT_FILTERS, likesMin: 100 })).toHaveLength(1)
    expect(applyFiltersTo(cards, { ...DEFAULT_FILTERS, likesMax: 100 })).toHaveLength(0)
  })

  it('视频有无/平台过滤', () => {
    expect(applyFiltersTo(cards, { ...DEFAULT_FILTERS, video: 'no' })).toHaveLength(2) // id2 无文件 + 云端无视频
    expect(applyFiltersTo(cards, { ...DEFAULT_FILTERS, platforms: ['bilibili'] })).toHaveLength(1)
  })
})
