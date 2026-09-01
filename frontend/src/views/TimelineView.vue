<template>
  <div>
    <h1 class="page-title">内容时间线</h1>
    <div class="card row">
      <button class="secondary" @click="shift(-1)">‹ 上月</button>
      <strong class="grow">{{ year }} 年 {{ month + 1 }} 月</strong>
      <button class="secondary" @click="shift(1)">下月 ›</button>
    </div>
    <div class="card">
      <div class="calendar-grid">
        <div v-for="w in ['日','一','二','三','四','五','六']" :key="w" class="muted" style="text-align:center">{{ w }}</div>
        <div v-for="(d, i) in days" :key="i" class="cal-day" :class="{ other: d.other }">
          <div class="dnum">{{ d.day }}</div>
          <div v-for="v in d.items" :key="v.id" class="cal-item" :class="v.cls" :title="v.title">
            {{ v.title }}
          </div>
        </div>
      </div>
    </div>
    <p class="muted">绿色=已发布，蓝色=计划中。点击下方列表或编辑素材可调整计划发布时间。</p>
  </div>
</template>

<script setup>
import { ref, computed, onMounted } from 'vue'
import { api } from '../api'

const videos = ref([])
const year = ref(new Date().getFullYear())
const month = ref(new Date().getMonth())

function fmt(v) { return v ? v.replace('T', ' ').slice(0, 10) : '' }

async function load() {
  const data = await api('/api/videos?limit=500')
  videos.value = data.items
}

function shift(delta) {
  const d = new Date(year.value, month.value + delta, 1)
  year.value = d.getFullYear()
  month.value = d.getMonth()
}

function dayKey(iso) { return iso ? iso.slice(0, 10) : null }

const days = computed(() => {
  const first = new Date(year.value, month.value, 1)
  const start = new Date(first)
  start.setDate(1 - first.getDay())
  const cells = []
  const map = {}
  videos.value.forEach(v => {
    const pub = dayKey(v.published_at)
    const plan = dayKey(v.planned_publish_at)
    const key = pub || plan
    if (!key) return
    if (!map[key]) map[key] = []
    map[key].push({
      id: v.id,
      title: (v.main_topic || v.filename).slice(0, 8),
      cls: pub ? 'published' : 'planned'
    })
  })
  for (let i = 0; i < 42; i++) {
    const d = new Date(start)
    d.setDate(start.getDate() + i)
    const k = `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, '0')}-${String(d.getDate()).padStart(2, '0')}`
    cells.push({
      day: d.getDate(),
      other: d.getMonth() !== month.value,
      items: map[k] || []
    })
  }
  return cells
})

onMounted(load)
</script>
