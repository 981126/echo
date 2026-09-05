<template>
  <div class="row" style="gap: 8px">
    <input ref="inputEl" type="file" accept="video/*" class="file-hidden" @change="onPick" />
    <n-button secondary @click="inputEl && inputEl.click()">选择视频文件</n-button>
    <span v-if="fileName" class="muted grow">{{ fileName }}</span>
  </div>
</template>

<script setup>
import { ref } from 'vue'

defineProps({
  fileName: { type: String, default: '' }
})
const emit = defineEmits(['file'])
const inputEl = ref(null)

function onPick(e) {
  const f = e.target.files[0]
  if (inputEl.value) inputEl.value.value = ''
  emit('file', f || null)
}
</script>
