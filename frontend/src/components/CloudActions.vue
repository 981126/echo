<template>
  <div class="row" style="gap: 8px">
    <n-button secondary :loading="metaSaving" @click="$emit('meta')">仅保存广告设置</n-button>
    <n-button secondary :loading="saving" @click="$emit('save')">保存为本地素材</n-button>
    <n-button type="primary" :disabled="!canTranscribe" :loading="saving" @click="$emit('transcribe')">保存并语音转文字</n-button>
    <n-button secondary @click="$emit('cancel')">取消</n-button>
  </div>
</template>

<script setup>
defineProps({
  metaSaving: { type: Boolean, default: false },
  saving: { type: Boolean, default: false },
  canTranscribe: { type: Boolean, default: false }
})
defineEmits(['meta', 'save', 'transcribe', 'cancel'])
</script>
