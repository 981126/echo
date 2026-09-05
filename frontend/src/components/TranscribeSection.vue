<template>
  <div class="form-item full">
    <label class="form-label">语音转文字（阿里云 ASR）</label>
    <div class="row" style="gap: 8px; align-items: center; flex-wrap: wrap">
      <n-button v-if="!transcriptText" secondary :loading="transcribing" @click="$emit('start')">
        {{ transcribing ? '识别中…' : '开始转写' }}
      </n-button>
      <n-tag v-if="transcriptText" size="small" type="success" :bordered="false" round>已转写</n-tag>
      <span v-if="transcribing" class="muted">后台识别中，完成后会提醒并自动展示在下方</span>
      <span v-else-if="!transcriptText" class="muted">上传视频不会自动转写，点按钮把语音转成文字</span>
    </div>
  </div>
</template>

<script setup>
defineProps({
  transcriptText: { type: String, default: '' },
  transcribing: { type: Boolean, default: false }
})
defineEmits(['start'])
</script>
