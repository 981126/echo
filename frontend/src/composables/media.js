// 素材/作品数据拉取统一入口（R-061-C：消除各页面重复 fetch 代码）
import { api } from '../api'

export async function fetchVideos() {
  const data = await api('/api/videos?limit=500')
  return data.items || []
}

export async function fetchWorks() {
  const data = await api('/api/works')
  return data.items || []
}
