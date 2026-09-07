<template>
  <div class="page">
    <div class="row wrap" style="justify-content: space-between; align-items: center; gap: 10px">
      <h1 class="page-title">博主对标</h1>
      <div class="row" style="gap: 10px; align-items: center">
        <span v-if="rerunning" class="muted mini">{{ rerunNote }} {{ rerunPct > 0 && rerunPct < 100 ? rerunPct + '%' : '' }}</span>
        <n-button size="small" type="primary" :loading="rerunning" :disabled="!benchmarks.length" @click="rerunAll">重新对标</n-button>
      </div>
    </div>
    <div v-if="loading" class="panel empty">加载中…</div>
    <div v-else-if="!benchmarks.length" class="panel empty">
      还没有对标博主。去「博主管理」为当前主博主添加对标账号后，这里会自动展示其最新 10 条里数据最好的前 3 条。
    </div>
    <div v-else class="bm-list">
      <div v-for="b in benchmarks" :key="b.benchmark_id" class="panel" style="margin-bottom: 16px">
        <div class="row wrap" style="justify-content: space-between; gap: 8px">
          <div>
            <b>{{ b.name }}</b>
            <span v-if="b.note" class="muted" style="margin-left: 8px">{{ b.note }}</span>
          </div>
          <div class="row" style="gap: 8px">
            <n-button size="small" secondary :loading="preparingId === b.benchmark_id" @click="prepare(b)">
              转写补齐Top3（无文案自动顺延）
            </n-button>
          </div>
        </div>
        <div v-if="!b.items.length" class="muted" style="padding: 10px 0">暂无作品，先同步该对标账号</div>
        <div v-for="(it, idx) in b.items" :key="it.key" class="bm-item">
          <div class="bm-rank">{{ idx + 1 }}</div>
          <div class="grow" style="min-width: 0">
            <div class="row wrap" style="gap: 6px">
              <b>{{ it.title }}</b>
              <n-tag v-for="p in it.platforms" :key="p" size="tiny" :bordered="false" round>{{ platformName(p) }}</n-tag>
              <n-tag v-if="it.has_text" size="tiny" type="success" :bordered="false" round>有文案</n-tag>
              <n-tag v-else size="tiny" type="warning" :bordered="false" round>暂无文案</n-tag>
            </div>
            <div class="muted" style="font-size: 12px; margin: 4px 0">
              赞 {{ it.likes }} · 藏 {{ it.favorites }} · 评 {{ it.comments }} · 播放 {{ it.plays }} · 互动分 {{ it.score }}
            </div>
            <div v-if="it.desc" class="muted bm-desc">{{ it.desc }}</div>
          </div>
          <div class="row" style="gap: 6px; flex-wrap: wrap">
            <n-button size="tiny" secondary :loading="analyzingKey === it.key" @click="analyze(b, it)">AI分析</n-button>
            <template v-if="analysisMap[it.key]">
              <div class="talk-result">
                <span :class="analysisMap[it.key].can ? 'can' : 'no'">{{ analysisMap[it.key].can ? '✅ 能讲' : '❌ 不建议' }}</span>
                <span class="muted">{{ analysisMap[it.key].reason }}</span>
              </div>
              <n-button v-if="analysisMap[it.key].can" size="tiny" type="primary" :loading="rewritingKey === it.key" @click="rewrite(b, it)">洗稿</n-button>
            </template>
          </div>
        </div>
      </div>
    </div>

    <n-modal v-model:show="showScript" preset="card" :title="'洗稿完成 · 已存入草稿 #' + (draftId || '')" style="width: min(720px, 96vw)">
      <pre class="script-pre">{{ scriptText }}</pre>
      <div class="row" style="justify-content: flex-end; gap: 8px; margin-top: 8px">
        <n-button size="small" @click="copyScript">复制</n-button>
        <n-button size="small" type="primary" @click="showScript = false">关闭</n-button>
      </div>
    </n-modal>
  </div>
</template>

<script setup>
import { ref, reactive, toRef, onMounted, onUnmounted } from 'vue'
import { useMessage } from 'naive-ui'
import { api } from '../api'
import { platformName } from '../lib/format'

const message = useMessage()

// R-114/R-116：跨页面共享的进行中状态（切页组件卸载不丢，返回后动画/结果仍在）
const ui = reactive({
  preparingId: 0,
  analyzingKey: '',
  rewritingKey: '',
  analysisMap: {},
  showScript: false,
  scriptText: '',
  draftId: 0
})

const loading = ref(true)
const benchmarks = ref([])
const preparingId = toRef(ui, 'preparingId')
const rerunning = ref(false)
const rerunPct = ref(0)
const rerunNote = ref('')
let pollAlive = false
const analyzingKey = toRef(ui, 'analyzingKey')
const rewritingKey = toRef(ui, 'rewritingKey')
const analysisMap = toRef(ui, 'analysisMap')
const showScript = toRef(ui, 'showScript')
const scriptText = toRef(ui, 'scriptText')
const draftId = toRef(ui, 'draftId')
let analyzeSeq = 0
let rewriteSeq = 0

async function load() {
  loading.value = true
  try {
    const d = await api('/api/benchmark/top')
    benchmarks.value = d.benchmarks || []
    // R-114/R-116：合并已保存的「AI分析」结果（不清空进行中状态），切页不丢
    for (const bm of benchmarks.value) {
      for (const it of bm.items || []) {
        if (it.analysis) analysisMap.value[it.key] = it.analysis
      }
    }
  } catch (e) {
    message.error(e.message)
  } finally {
    loading.value = false
  }
}

async function prepare(b) {
  preparingId.value = b.benchmark_id
  message.info(`开始为「${b.name}」补齐文案并取 Top3（需几分钟，请稍候…）`)
  try {
    const d = await api('/api/benchmark/prepare', { method: 'POST', body: JSON.stringify({ benchmark_id: b.benchmark_id }) })
    b.items = d.items || []
    message.success('Top3 文案已就绪')
    await load()
  } catch (e) {
    message.error(e.message)
  } finally {
    preparingId.value = 0
  }
}

async function rerunAll() {
  rerunning.value = true
  rerunPct.value = 0
  rerunNote.value = '准备中…'
  message.info('开始重新对标：重捞各对标最新数据并自动补齐 Top3 文案，需几分钟，请稍候…')
  try {
    const d = await api('/api/benchmark/rerun', { method: 'POST' })
    await waitTask(d.task_id)
  } catch (e) {
    message.error(e.message)
  } finally {
    rerunning.value = false
  }
}

async function waitTask(taskId) {
  pollAlive = true
  for (;;) {
    await new Promise(r => setTimeout(r, 2000))
    if (!pollAlive) return
    let t
    try {
      t = await api('/api/tasks/' + taskId)
    } catch (e) {
      if (pollAlive) message.error(e.message)
      rerunning.value = false
      return
    }
    if (!pollAlive) return
    rerunPct.value = t.progress || 0
    rerunNote.value = t.note && t.note !== '完成' ? t.note : '进行中…'
    if (t.status === 'done') {
      rerunNote.value = ''
      rerunning.value = false
      if (pollAlive) {
        message.success('重新对标完成，Top3 已刷新')
        await load()
      }
      return
    }
    if (t.status === 'failed') {
      rerunNote.value = ''
      rerunning.value = false
      if (pollAlive) message.error(t.error || '重新对标失败')
      return
    }
  }
}

async function resumeRunning() {
  // R-103：切页回来时若后台仍在“重新对标”，恢复进度显示与轮询
  try {
    const list = await api('/api/tasks?status=running&kind=benchmark_rerun&limit=5')
    const task = (list || []).find(t => t.kind === 'benchmark_rerun')
    if (task && !rerunning.value) {
      rerunning.value = true
      rerunPct.value = task.progress || 0
      rerunNote.value = task.note && task.note !== '完成' ? task.note : '进行中…'
      waitTask(task.id)
    }
  } catch (e) {
    /* 恢复失败不打扰，任务完成仍会走通知 */
  }

  // R-116：AI分析 / 洗稿 落后台任务后，切页回来恢复进行态
  try {
    const list = await api('/api/tasks?status=running&kind=benchmark_analyze,benchmark_rewrite&limit=20')
    for (const t of (list || [])) {
      let pl = {}
      try { pl = JSON.parse(t.payload || '{}') } catch { /* ignore */ }
      if (t.kind === 'benchmark_analyze' && pl.key) {
        analyzingKey.value = pl.key
        watchAnalyze(t.id, pl.key)
      } else if (t.kind === 'benchmark_rewrite' && pl.key) {
        rewritingKey.value = pl.key
        watchRewrite(t.id, pl.key)
      }
    }
  } catch (e) {
    /* 恢复失败不打扰 */
  }
}

async function analyze(b, it) {
  if (!it.text) {
    message.warning('该条还没有文案，请先“转写补齐Top3”')
    return
  }
  analyzingKey.value = it.key
  try {
    const d = await api('/api/benchmark/analyze', { method: 'POST', body: JSON.stringify({ title: it.title, text: it.text, key: it.key }) })
    watchAnalyze(d.task_id, it.key)
  } catch (e) {
    analyzingKey.value = ''
    message.error(e.message)
  }
}

async function watchAnalyze(taskId, key) {
  const my = ++analyzeSeq
  for (;;) {
    await new Promise(r => setTimeout(r, 2000))
    if (analyzeSeq !== my) return
    let t
    try {
      t = await api('/api/tasks/' + taskId)
    } catch (e) {
      if (analyzeSeq === my) {
        analyzingKey.value = ''
        message.error(e.message)
      }
      return
    }
    if (analyzeSeq !== my) return
    if (t.status === 'done') {
      analyzingKey.value = ''
      message.success('AI 分析完成')
      await load()
      return
    }
    if (t.status === 'failed') {
      analyzingKey.value = ''
      message.error(t.error || 'AI 分析失败')
      return
    }
  }
}

async function rewrite(b, it) {
  rewritingKey.value = it.key
  try {
    const d = await api('/api/benchmark/rewrite', { method: 'POST', body: JSON.stringify({ title: it.title, text: it.text, key: it.key }) })
    watchRewrite(d.task_id, it.key)
  } catch (e) {
    rewritingKey.value = ''
    message.error(e.message)
  }
}

async function watchRewrite(taskId, key) {
  const my = ++rewriteSeq
  for (;;) {
    await new Promise(r => setTimeout(r, 2000))
    if (rewriteSeq !== my) return
    let t
    try {
      t = await api('/api/tasks/' + taskId)
    } catch (e) {
      if (rewriteSeq === my) {
        rewritingKey.value = ''
        message.error(e.message)
      }
      return
    }
    if (rewriteSeq !== my) return
    if (t.status === 'done') {
      rewritingKey.value = ''
      let res = {}
      try { res = JSON.parse(t.result || '{}') } catch { /* ignore */ }
      if (res && res.script) {
        scriptText.value = res.script
        draftId.value = res.draft_id || 0
        showScript.value = true
        message.success(`洗稿完成，已存入草稿 #${draftId.value}`)
      } else {
        message.success('洗稿完成')
      }
      return
    }
    if (t.status === 'failed') {
      rewritingKey.value = ''
      message.error(t.error || '洗稿失败')
      return
    }
  }
}

async function copyScript() {
  try {
    await navigator.clipboard.writeText(scriptText.value)
    message.success('已复制')
  } catch {
    message.warning('复制失败，请手动选择复制')
  }
}

onMounted(async () => {
  await load()
  resumeRunning()
})
onUnmounted(() => {
  pollAlive = false
  analyzeSeq++
  rewriteSeq++
})
</script>

<style scoped>
.bm-list { display: flex; flex-direction: column; }
.bm-item { display: flex; gap: 12px; padding: 10px 0; border-top: 1px solid var(--line, #eee5d8); align-items: flex-start; }
.bm-rank { width: 22px; height: 22px; flex: none; border-radius: 6px; background: #a34f2c; color: #fff; font-size: 12px; display: flex; align-items: center; justify-content: center; margin-top: 2px; }
.bm-desc { display: -webkit-box; -webkit-line-clamp: 2; -webkit-box-orient: vertical; overflow: hidden; font-size: 12px; }
.talk-result { display: flex; flex-direction: column; gap: 2px; max-width: 280px; font-size: 12px; }
.can { color: #18a058; font-weight: 600; }
.no { color: #d03050; font-weight: 600; }
.script-pre { white-space: pre-wrap; word-break: break-word; background: #faf7f2; border-radius: 8px; padding: 12px; max-height: 60vh; overflow: auto; }
</style>
