<template>
  <div class="page">
    <h1 class="page-title">数据看板</h1>

    <div v-if="compare.length" class="panel">
      <div class="section-title" style="margin-top: 0">我 vs 对标</div>
      <div class="cmp-grid">
        <div v-for="c in compare" :key="c.creator.id" class="cmp-cell" :class="{ me: c.creator.kind === 'owner' && c.creator.is_current }">
          <div class="row" style="gap: 6px; align-items: center">
            <b>{{ c.creator.name }}</b>
            <n-tag size="tiny" :bordered="false" round :type="c.creator.kind === 'owner' ? 'primary' : 'info'">{{ c.creator.kind === 'owner' ? '我' : '对标' }}</n-tag>
          </div>
          <div class="cmp-num">{{ fmtNum(c.totals.followers) }}<span>总粉丝</span></div>
          <div class="cmp-sub">{{ fmtNum(c.totals.posts) }} 作品 · 播放 {{ fmtNum(c.totals.plays) }}</div>
          <div class="row wrap" style="gap: 6px; margin-top: 6px">
            <div v-for="ac in c.accounts" :key="ac.platform" class="cmp-acct">
              <b>{{ platformName(ac.platform) }}</b>
              <span>粉 {{ fmtNum(ac.followers) }}</span>
              <span>中位播 {{ fmtNum(ac.median_plays) }}</span>
            </div>
          </div>
        </div>
      </div>
    </div>

    <div class="panel">
      <div class="section-title" style="margin-top: 0">指标录入</div>
      <div class="form-grid">
        <div class="form-item">
          <label class="form-label">视频</label>
          <n-select v-model:value="m.video_id" :options="videoOptions" placeholder="选择视频" />
        </div>
        <div class="form-item">
          <label class="form-label">日期</label>
          <n-date-picker v-model:value="m.dateTs" type="date" style="width: 100%" />
        </div>
        <div class="form-item">
          <label class="form-label">播放</label>
          <n-input-number v-model:value="m.plays" style="width: 100%" :min="0" />
        </div>
        <div class="form-item">
          <label class="form-label">赞</label>
          <n-input-number v-model:value="m.likes" style="width: 100%" :min="0" />
        </div>
        <div class="form-item">
          <label class="form-label">藏</label>
          <n-input-number v-model:value="m.favorites" style="width: 100%" :min="0" />
        </div>
        <div class="form-item">
          <label class="form-label">评</label>
          <n-input-number v-model:value="m.comments" style="width: 100%" :min="0" />
        </div>
      </div>
      <div class="row">
        <n-button type="primary" @click="addMetric">录入</n-button>
      </div>
      <details class="fold">
        <summary>批量导入（JSON）</summary>
        <n-input
          v-model:value="importText"
          type="textarea"
          :rows="4"
          style="margin: 8px 0"
          placeholder='[{"video_id":1,"snapshot_date":"2026-08-28","plays":1000,"likes":80,"favorites":20,"comments":5}]'
        />
        <n-button secondary size="small" @click="importMetrics">导入</n-button>
      </details>
    </div>

    <div class="panel">
      <div class="section-title" style="margin-top: 0">赛道雷达</div>
      <div v-if="!radar.length" class="empty">暂无指标数据</div>
      <div v-for="r in radar" :key="r.topic" class="bar-row">
        <span class="bar-label">{{ r.topic }}</span>
        <div class="bar-track"><div class="bar-fill" :style="{ width: barWidth(r.engagement) + '%' }" /></div>
        <span class="bar-meta">{{ r.videos }} 条 · 互动 {{ r.engagement }}%</span>
      </div>
    </div>

    <div class="panel">
      <div class="row" style="justify-content: space-between; margin-bottom: 4px">
        <span class="section-title" style="margin: 0">复盘报告</span>
        <n-button type="primary" size="small" :loading="generating" @click="generate">生成复盘</n-button>
      </div>
      <div v-if="!report" class="empty">暂无复盘报告，点「生成复盘」</div>
      <template v-else>
        <p class="muted">报告日期：{{ report.run_date }}</p>
        <div class="section-title">A · 各赛道汇总</div>
        <table class="table">
          <thead>
            <tr><th>赛道</th><th class="num">条数</th><th class="num">播放</th><th class="num">赞</th><th class="num">藏</th><th class="num">评</th></tr>
          </thead>
          <tbody>
            <tr v-for="(v, k) in report.content.A_report.by_topic" :key="k">
              <td>{{ k }}</td><td class="num">{{ v.videos }}</td><td class="num">{{ v.plays }}</td>
              <td class="num">{{ v.likes }}</td><td class="num">{{ v.favorites }}</td><td class="num">{{ v.comments }}</td>
            </tr>
          </tbody>
        </table>
        <div class="section-title">B · 归因</div>
        <ul style="margin: 0; padding-left: 1.2em">
          <li v-for="(b, i) in report.content.B_attribution" :key="i">{{ b.video }}：{{ b.why }}</li>
          <li v-if="!report.content.B_attribution.length" class="muted">（数据不足，未生成归因）</li>
        </ul>
        <div class="section-title">C · 下一条建议</div>
        <p>{{ report.content.C_next_action || '—' }}</p>
        <div class="section-title">D · 赛道方向</div>
        <p>{{ report.content.D_topic_direction || '—' }}</p>
      </template>
    </div>

    <div class="panel">
      <div class="section-title" style="margin-top: 0">视频指标明细（最新快照）</div>
      <table class="table">
        <thead>
          <tr><th>视频</th><th class="num">播放</th><th class="num">赞</th><th class="num">藏</th><th class="num">评</th><th class="num">日期</th></tr>
        </thead>
        <tbody>
          <tr v-for="v in summary.per_video" :key="v.video_id">
            <td>{{ v.filename }}</td>
            <td class="num">{{ v.plays }}</td><td class="num">{{ v.likes }}</td>
            <td class="num">{{ v.favorites }}</td><td class="num">{{ v.comments }}</td>
            <td class="num muted">{{ v.snapshot_date }}</td>
          </tr>
        </tbody>
      </table>
      <div v-if="!summary.per_video.length" class="empty">暂无指标</div>
    </div>
  </div>
</template>

<script setup>
import { ref, computed, onMounted } from 'vue'
import { useMessage } from 'naive-ui'
import { api } from '../api'
import { fetchVideos } from '../composables/media'

const videos = ref([])
const summary = ref({ per_video: [], by_topic: {}, by_platform: {} })
const radar = ref([])
const report = ref(null)
const generating = ref(false)
const importText = ref('')
const compare = ref([])
const message = useMessage()
const m = ref({ video_id: null, dateTs: Date.now(), plays: 0, likes: 0, favorites: 0, comments: 0 })

const videoOptions = computed(() =>
  videos.value.map(v => ({ label: v.filename, value: v.id }))
)

function barWidth(e) {
  return Math.min(100, Math.max(3, e * 10))
}

function tsToDate(ts) {
  if (!ts) return ''
  const d = new Date(ts)
  return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, '0')}-${String(d.getDate()).padStart(2, '0')}`
}

const PLATFORM_NAMES = { douyin: '抖音', bilibili: 'B站', xiaohongshu: '小红书' }
const platformName = (p) => PLATFORM_NAMES[p] || p || ''
function fmtNum(n) {
  n = Number(n || 0)
  if (n >= 100000000) return (n / 100000000).toFixed(1) + '亿'
  if (n >= 10000) return (n / 10000).toFixed(1) + '万'
  return String(n)
}

async function load() {
  const [v, s, r, rep] = await Promise.all([
    fetchVideos(),
    api('/api/metrics/summary'),
    api('/api/review/radar'),
    api('/api/review/report')
  ])
  videos.value = v
  summary.value = s
  radar.value = r.radar
  report.value = rep
  try {
    const cs = await api('/api/platform/creator-summary')
    compare.value = cs.items || []
  } catch (e) {
    compare.value = []
  }
}

async function addMetric() {
  if (!m.value.video_id) {
    message.warning('请选择视频')
    return
  }
  await api('/api/metrics', {
    method: 'POST',
    body: JSON.stringify({
      video_id: m.value.video_id,
      snapshot_date: tsToDate(m.value.dateTs),
      plays: m.value.plays,
      likes: m.value.likes,
      favorites: m.value.favorites,
      comments: m.value.comments
    })
  })
  message.success('已录入')
  load()
}

async function importMetrics() {
  try {
    const rows = JSON.parse(importText.value)
    const r = await api('/api/metrics/import', { method: 'POST', body: JSON.stringify({ rows }) })
    message.success(`导入 ${r.imported} 条`)
    load()
  } catch (e) {
    message.error('导入失败：' + e.message)
  }
}

async function generate() {
  generating.value = true
  try {
    await api('/api/review/generate', { method: 'POST', body: '{}' })
    message.success('复盘已生成')
    load()
  } catch (e) {
    message.error(e.message)
  } finally {
    generating.value = false
  }
}

onMounted(load)
</script>

<style scoped>
.cmp-grid {
  display: flex;
  gap: 12px;
  flex-wrap: wrap;
}
.cmp-cell {
  flex: 1 1 220px;
  background: #faf7f2;
  border: 1px solid #eee5d8;
  border-radius: 10px;
  padding: 12px 14px;
}
.cmp-cell.me {
  border-color: #a34f2c55;
  background: #fdf6ef;
}
.cmp-num {
  font-size: 22px;
  font-weight: 700;
  color: #a34f2c;
  margin-top: 6px;
}
.cmp-num span {
  font-size: 12px;
  font-weight: 400;
  color: #8b8378;
  margin-left: 6px;
}
.cmp-sub {
  font-size: 12px;
  color: #8b8378;
  margin-top: 2px;
}
.cmp-acct {
  display: flex;
  flex-direction: column;
  font-size: 11px;
  color: #6f675c;
  background: #fff;
  border-radius: 6px;
  padding: 4px 8px;
}
</style>
