// R-152：素材库非主博主素材「洗稿」——按素材来源发起后台洗稿任务、轮询结果，供原文对照弹窗展示。
// 状态放模块级（切页组件卸载不丢，与 R-114/R-116 同款）；后端复用博主对标同一双模型讨论链路。
import { computed, reactive, toRef } from 'vue'
import { useMessage } from 'naive-ui'
import { api } from '../api'

const ui = reactive({
  rewritingKey: '',
  showScript: false,
  scriptText: '',
  originalText: '',
  sourceTitle: '',
  benchmarkName: '',
  draftId: 0
})

let seq = 0

export function useRewrite() {
  const message = useMessage()

  function apply(res) {
    ui.scriptText = res.script || ''
    ui.originalText = res.original_script || ''
    ui.sourceTitle = (res.source_ref && res.source_ref.source_title) || res.title || ''
    ui.benchmarkName = res.benchmark_name || (res.source_ref && res.source_ref.benchmark_name) || ''
    ui.draftId = res.draft_id || 0
  }

  async function track(taskId) {
    const my = ++seq
    for (;;) {
      await new Promise(r => setTimeout(r, 2000))
      if (seq !== my) return
      let t
      try {
        t = await api('/api/tasks/' + taskId)
      } catch (e) {
        if (seq === my) {
          ui.rewritingKey = ''
          message.error(e.message)
        }
        return
      }
      if (seq !== my) return
      if (t.status === 'done') {
        ui.rewritingKey = ''
        let res = {}
        try { res = JSON.parse(t.result || '{}') } catch { /* ignore */ }
        if (res && res.script) {
          apply(res)
          ui.showScript = true
          message.success(`洗稿完成，已存入草稿 #${ui.draftId}`)
        } else {
          message.success('洗稿完成')
        }
        return
      }
      if (t.status === 'failed') {
        ui.rewritingKey = ''
        message.error(t.error || '洗稿失败')
        return
      }
    }
  }

  // source: { video_id } | { post_id } | { work_id }（三选一）
  async function rewriteSource(source, key = '') {
    if (ui.rewritingKey) return
    ui.rewritingKey = key
    try {
      const d = await api('/api/benchmark/rewrite-source', { method: 'POST', body: JSON.stringify(source) })
      await track(d.task_id)
    } catch (e) {
      ui.rewritingKey = ''
      message.error(e.message)
    }
  }

  async function copyScript() {
    try {
      await navigator.clipboard.writeText(ui.scriptText)
      message.success('已复制')
    } catch {
      message.warning('复制失败，请手动选择复制')
    }
  }

  return {
    rewriting: computed(() => !!ui.rewritingKey),
    rewritingKey: toRef(ui, 'rewritingKey'),
    showScript: toRef(ui, 'showScript'),
    scriptText: toRef(ui, 'scriptText'),
    originalText: toRef(ui, 'originalText'),
    sourceTitle: toRef(ui, 'sourceTitle'),
    benchmarkName: toRef(ui, 'benchmarkName'),
    draftId: toRef(ui, 'draftId'),
    rewriteSource,
    copyScript
  }
}
