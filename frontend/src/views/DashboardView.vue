<template>
  <div>
    <h1 class="page-title">看板 · 指标与复盘</h1>

    <div class="card">
      <h3>指标录入</h3>
      <div class="row">
        <label class="field">视频
          <select v-model="m.video_id"><option value="">选择视频</option><option v-for="v in videos" :key="v.id" :value="v.id">{{ v.filename }}</option></select>
        </label>
        <label class="field">日期<input type="date" v-model="m.snapshot_date" /></label>
        <label class="field">播放<input type="number" v-model.number="m.plays" /></label>
        <label class="field">赞<input type="number" v-model.number="m.likes" /></label>
        <label class="field">藏<input type="number" v-model.number="m.favorites" /></label>
        <label class="field">评<input type="number" v-model.number="m.comments" /></label>
        <button class="secondary" @click="addMetric">录入</button>
      </div>
      <details style="margin-top: 8px">
        <summary class="muted">批量导入（JSON，或从平台导出后转成此格式）</summary>
        <textarea v-model="importText" style="min-height: 90px; margin-top: 6px"
          placeholder='[{"video_id":1,"snapshot_date":"2026-08-28","plays":1000,"likes":80,"favorites":20,"comments":5}]'></textarea>
        <button class="secondary" @click="importMetrics">导入</button>
      </details>
    </div>

    <div class="card">
      <h3>赛道雷达</h3>
      <div v-if="!radar.length" class="empty">暂无指标数据</div>
      <div v-for="r in radar" :key="r.topic" style="margin-bottom: 8px">
        <div class="row">
          <strong style="width: 80px">{{ r.topic }}</strong>
          <div style="flex:1;background:#eef1f5;border-radius:6px;height:18px;overflow:hidden">
            <div :style="{ width: barWidth(r.engagement) + '%', background: '#3b82f6', height: '100%' }"></div>
          </div>
          <span class="muted" style="width: 130px; text-align:right">{{ r.videos }} 条 · 互动 {{ r.engagement }}%</span>
        </div>
      </div>
    </div>

    <div class="card">
      <div class="row">
        <h3 class="grow">复盘报告</h3>
        <button :disabled="generating" @click="generate">{{ generating ? '生成中…' : '生成复盘' }}</button>
      </div>
      <div v-if="!report" class="empty">暂无复盘报告，点"生成复盘"</div>
      <template v-else>
        <p class="muted">生成时间：{{ report.run_date }}</p>
        <h4>A · 各赛道汇总</h4>
        <table style="width:100%;border-collapse:collapse">
          <thead><tr class="muted"><th style="text-align:left">赛道</th><th style="text-align:right">条数</th><th style="text-align:right">播放</th><th style="text-align:right">赞</th><th style="text-align:right">藏</th><th style="text-align:right">评</th></tr></thead>
          <tbody>
            <tr v-for="(v, k) in report.content.A_report.by_topic" :key="k" style="border-top:1px solid var(--border)">
              <td>{{ k }}</td><td style="text-align:right">{{ v.videos }}</td><td style="text-align:right">{{ v.plays }}</td>
              <td style="text-align:right">{{ v.likes }}</td><td style="text-align:right">{{ v.favorites }}</td><td style="text-align:right">{{ v.comments }}</td>
            </tr>
          </tbody>
        </table>
        <h4>B · 归因</h4>
        <ul>
          <li v-for="(b, i) in report.content.B_attribution" :key="i">{{ b.video }}：{{ b.why }}</li>
          <li v-if="!report.content.B_attribution.length" class="muted">（数据不足，未生成归因）</li>
        </ul>
        <h4>C · 下一条建议</h4>
        <p>{{ report.content.C_next_action || '—' }}</p>
        <h4>D · 赛道方向</h4>
        <p>{{ report.content.D_topic_direction || '—' }}</p>
      </template>
    </div>

    <div class="card">
      <h3>视频指标明细（最新快照）</h3>
      <div v-if="!summary.per_video.length" class="empty">暂无指标</div>
      <table style="width:100%;border-collapse:collapse">
        <thead><tr class="muted"><th style="text-align:left">视频</th><th style="text-align:right">播放</th><th style="text-align:right">赞</th><th style="text-align:right">藏</th><th style="text-align:right">评</th><th style="text-align:right">日期</th></tr></thead>
        <tbody>
          <tr v-for="v in summary.per_video" :key="v.video_id" style="border-top:1px solid var(--border)">
            <td>{{ v.filename }} <span class="badge">{{ v.main_topic }}</span></td>
            <td style="text-align:right">{{ v.plays }}</td><td style="text-align:right">{{ v.likes }}</td>
            <td style="text-align:right">{{ v.favorites }}</td><td style="text-align:right">{{ v.comments }}</td>
            <td style="text-align:right" class="muted">{{ v.snapshot_date }}</td>
          </tr>
        </tbody>
      </table>
    </div>
  </div>
</template>

<script setup>
import { ref, onMounted } from 'vue'
import { api } from '../api'

const videos = ref([])
const summary = ref({ per_video: [], by_topic: {}, by_platform: {} })
const radar = ref([])
const report = ref(null)
const generating = ref(false)
const importText = ref('')
const msg = ref('')
const m = ref({ video_id: '', snapshot_date: new Date().toISOString().slice(0, 10), plays: 0, likes: 0, favorites: 0, comments: 0 })

function barWidth(e) { return Math.min(100, Math.max(3, e * 10)) }

async function load() {
  const [v, s, r, rep] = await Promise.all([
    api('/api/videos?limit=500'),
    api('/api/metrics/summary'),
    api('/api/review/radar'),
    api('/api/review/report')
  ])
  videos.value = v.items
  summary.value = s
  radar.value = r.radar
  report.value = rep
}

async function addMetric() {
  if (!m.value.video_id) { alert('请选择视频'); return }
  await api('/api/metrics', { method: 'POST', body: JSON.stringify(m.value) })
  alert('已录入')
  load()
}

async function importMetrics() {
  try {
    const rows = JSON.parse(importText.value)
    const r = await api('/api/metrics/import', { method: 'POST', body: JSON.stringify({ rows }) })
    alert(`导入 ${r.imported} 条`)
    load()
  } catch (e) { alert('导入失败：' + e.message) }
}

async function generate() {
  generating.value = true
  try {
    await api('/api/review/generate', { method: 'POST', body: '{}' })
    load()
  } catch (e) { alert(e.message) } finally { generating.value = false }
}

onMounted(load)
</script>
