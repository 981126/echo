// 素材/作品数据拉取统一入口（R-061-C：消除各页面重复 fetch 代码）
import { api } from '../api'

export async function fetchVideos(creatorId = 0) {
  const q = creatorId ? `&creator_id=${creatorId}` : ''
  const data = await api(`/api/videos?limit=500${q}`)
  return data.items || []
}

export async function fetchWorks(creatorId = 0) {
  const q = creatorId ? `?creator_id=${creatorId}` : ''
  const data = await api(`/api/works${q}`)
  return data.items || []
}
