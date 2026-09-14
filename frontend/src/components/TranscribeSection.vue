<template>
  <div class="form-item full">
    <label class="form-label" :title="asrLabel">{{ asrLabel }}</label>
    <div class="row" style="gap: 8px; align-items: center; flex-wrap: wrap">
      <n-button v-if="!transcriptText" secondary :loading="transcribing" @click="$emit('start')">
        {{ transcribing ? '识别中…' : '开始转写' }}
      </n-button>
      <n-tag v-if="transcriptText" size="small" type="success" :bordered="false" round>已转写</n-tag>
      <n-button
        v-if="transcriptText && canRewrite"
        size="tiny"
        type="primary"
        secondary
        :loading="rewriting"
        @click="$emit('rewrite')"
      >洗稿</n-button>
      <span v-if="transcribing" class="muted">后台识别中，完成后会提醒并自动展示在下方</span>
      <span v-else-if="!transcriptText" class="muted">上传视频不会自动转写，点按钮把语音转成文字</span>
    </div>
  </div>
</template>

<script setup>
import { ref, computed, onMounted } from 'vue'
import { api } from '../api'

const props = defineProps({
  transcriptText: { type: String, default: '' },
  transcribing: { type: Boolean, default: false },
  asrProvider: { type: String, default: '' },
  asrModel: { type: String, default: '' },
  canRewrite: { type: Boolean, default: false },
  rewriting: { type: Boolean, default: false }
})
defineEmits(['start', 'rewrite'])

const currentMode = ref('')
const currentModel = ref('')
onMounted(async () => {
  try {
    const r = await api('/api/settings/asr')
    currentMode.value = r?.mode || ''
    currentModel.value = r?.model || ''
  } catch {
    /* 后端暂不可用时保持默认 */
  }
})

const asrLabel = computed(() => {
  // 已有转写稿：以该条转写记录实际来源为准；来源未知（老数据/手动粘贴）则不标服务商
  if (props.transcriptText && !props.asrProvider) return '语音转文字'
  const mode = props.asrProvider || currentMode.value
  if (mode === 'siliconflow') {
    const m = props.asrModel || currentModel.value
    return m ? `语音转文字（硅基流动 ASR · ${m}）` : '语音转文字（硅基流动 ASR）'
  }
  if (mode === 'aliyun') return '语音转文字（阿里云 ASR）'
  if (mode === 'mock') return '语音转文字（模拟）'
  return '语音转文字'
})
</script>
