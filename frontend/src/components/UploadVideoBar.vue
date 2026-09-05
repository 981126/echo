<template>
  <div class="panel row">
    <input ref="inputEl" type="file" accept="video/*" class="file-hidden" @change="onPick" />
    <n-button secondary @click="pick">选择视频文件</n-button>
    <span v-if="file" class="muted grow">{{ file.name }}</span>
    <span v-else class="muted grow">或拖入 data/inbox 自动入库</span>
    <n-button type="primary" :disabled="!file" :loading="uploading" @click="upload">
      {{ uploading ? '上传中…' : '上传' }}
    </n-button>
  </div>
</template>

<script setup>
import { ref } from 'vue'

const props = defineProps({
  uploading: { type: Boolean, default: false }
})
const emit = defineEmits(['upload'])
const file = ref(null)
const inputEl = ref(null)

function pick() {
  if (inputEl.value) inputEl.value.click()
}

function onPick(e) {
  file.value = e.target.files[0] || null
}

function upload() {
  if (!file.value) return
  const f = file.value
  file.value = null
  if (inputEl.value) inputEl.value.value = ''
  emit('upload', f)
}
</script>
