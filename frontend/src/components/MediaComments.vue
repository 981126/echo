<template>
  <div class="mc-wrap">
    <div v-for="p in posts" :key="p.id" class="mc-post">
      <div class="mc-head">
        <b>{{ platformName(p.platform) }}</b>
        <n-button size="tiny" secondary :loading="loadingId === p.id" @click="refresh(p)">加载评论</n-button>
        <span v-if="(map[p.id] || []).length" class="mc-count">{{ map[p.id].length }} 条 · 按点赞排序</span>
      </div>
      <ul v-if="(map[p.id] || []).length" class="mc-list">
        <li v-for="(c, i) in map[p.id]" :key="(c.text || i) + '-' + i">
          <span class="mc-like">👍 {{ fmtNum(c.likes) }}</span>
          <span v-if="c.user_nick" class="mc-nick">{{ c.user_nick }}：</span>{{ c.text }}
        </li>
      </ul>
      <p v-else class="mc-empty">暂无本地评论，点「加载评论」实时拉取并入库（每平台点赞最高前 50 条）</p>
    </div>
  </div>
</template>

<script setup>
import { ref, watch } from 'vue'
import { useMessage } from 'naive-ui'
import { api } from '../api'
import { fmtNum } from '../lib/format'

const props = defineProps({
  posts: { type: Array, default: () => [] }
})
const message = useMessage()
const map = ref({})
const loadingId = ref(0)
const PLATFORM_NAMES = { douyin: '抖音', bilibili: 'B站', xiaohongshu: '小红书' }
const platformName = (p) => PLATFORM_NAMES[p] || p || ''

async function loadLocal(p) {
  try {
    const r = await api(`/api/platform/posts/${p.id}/comments?limit=50`)
    map.value = { ...map.value, [p.id]: r.items || [] }
  } catch (e) {
    /* 静默 */
  }
}

async function refresh(p) {
  loadingId.value = p.id
  try {
    const r = await api(`/api/platform/posts/${p.id}/comments/refresh`, { method: 'POST', body: '{}' })
    map.value = { ...map.value, [p.id]: r.items || [] }
    const n = (r.items || []).length
    message.success(r.added > 0 ? `已入库 ${r.added} 条新评论，共 ${n} 条` : `已是最新（共 ${n} 条）`)
  } catch (e) {
    message.error('评论拉取失败：' + e.message)
  } finally {
    loadingId.value = 0
  }
}

watch(
  () => props.posts,
  (val) => {
    if (!val || !val.length) return
    val.forEach(p => { if (!map.value[p.id]) loadLocal(p) })
  },
  { immediate: true }
)
</script>

<style scoped>
.mc-wrap { display: flex; flex-direction: column; gap: 8px; }
.mc-head { display: flex; gap: 6px; align-items: center; flex-wrap: wrap; }
.mc-count { color: var(--muted); }
.mc-list { margin: 6px 0 0; padding-left: 0; list-style: none; max-height: 220px; overflow-y: auto; }
.mc-list li { margin: 4px 0; font-size: 13px; line-height: 1.5; }
.mc-like { color: #a34f2c; font-size: 11px; margin-right: 6px; }
.mc-nick { color: var(--muted); }
.mc-empty { margin: 6px 0 0; font-size: 12px; color: var(--muted); }
</style>
