<template>
  <n-modal
    :show="show"
    preset="card"
    :title="'洗稿完成 · 已存入草稿 #' + (draftId || '')"
    style="width: min(980px, 96vw)"
    @update:show="v => $emit('update:show', v)"
  >
    <div v-if="sourceTitle" class="muted" style="margin-bottom: 8px">
      来源素材：{{ sourceTitle }}<template v-if="benchmarkName"> · 对标「{{ benchmarkName }}」</template>
    </div>
    <div class="cmp-grid">
      <div class="cmp-col">
        <div class="cmp-h">原文案（红 = 被改写/删除）</div>
        <div class="diff-body"><template v-for="(seg, i) in diff.left" :key="i"><span :class="seg.type">{{ seg.text }}</span></template></div>
      </div>
      <div class="cmp-col">
        <div class="cmp-h">洗稿后（绿 = 新增/修改）</div>
        <div class="diff-body"><template v-for="(seg, i) in diff.right" :key="i"><span :class="seg.type">{{ seg.text }}</span></template></div>
      </div>
    </div>
    <div class="row" style="justify-content: flex-end; gap: 8px; margin-top: 8px">
      <n-button size="small" @click="copy">复制洗稿后</n-button>
      <n-button size="small" type="primary" @click="$emit('update:show', false)">关闭</n-button>
    </div>
  </n-modal>
</template>

<script setup>
// R-152：博主对标页与素材库共用的「原文/洗稿」对照弹窗
import { computed } from 'vue'
import { useMessage } from 'naive-ui'
import { buildDiff } from '../lib/diff'

const props = defineProps({
  show: { type: Boolean, default: false },
  scriptText: { type: String, default: '' },
  originalText: { type: String, default: '' },
  sourceTitle: { type: String, default: '' },
  benchmarkName: { type: String, default: '' },
  draftId: { type: Number, default: 0 }
})
defineEmits(['update:show'])

const message = useMessage()
const diff = computed(() => buildDiff(props.originalText, props.scriptText))

async function copy() {
  try {
    await navigator.clipboard.writeText(props.scriptText)
    message.success('已复制')
  } catch {
    message.warning('复制失败，请手动选择复制')
  }
}
</script>

<style scoped>
.diff-body { white-space: pre-wrap; word-break: break-word; background: #faf7f2; border-radius: 8px; padding: 12px; max-height: 60vh; overflow: auto; font-size: 13px; line-height: 1.7; }
.diff-body .del { background: #ffe3e3; color: #c0392b; border-radius: 3px; }
.diff-body .add { background: #dcf5dc; color: #1a7f37; border-radius: 3px; }
.cmp-grid { display: grid; grid-template-columns: 1fr 1fr; gap: 12px; }
.cmp-h { font-size: 12px; color: #a34f2c; font-weight: 600; margin-bottom: 4px; }
@media (max-width: 640px) { .cmp-grid { grid-template-columns: 1fr; } }
</style>
