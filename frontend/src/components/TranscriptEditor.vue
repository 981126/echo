<template>
  <div style="display: contents">
    <div v-if="transcriptText" class="form-item full">
      <label class="form-label">ASR 转写（只读）</label>
      <div class="prose panel" style="margin-bottom: 0; background: var(--bg)">
        <p style="white-space: pre-wrap">{{ transcriptText }}</p>
      </div>
    </div>
    <div class="form-item full">
      <label class="form-label">原始文案（可选）</label>
      <n-input :value="sourceText" type="textarea" :rows="3" placeholder="与口播可能不一致" @update:value="$emit('update:sourceText', $event)" />
    </div>
  </div>
</template>

<script setup>
defineProps({
  transcriptText: { type: String, default: '' },
  sourceText: { type: String, default: '' }
})
defineEmits(['update:sourceText'])
</script>
