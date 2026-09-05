<template>
  <div class="form-item">
    <label class="form-label">本地视频文件</label>
    <div class="row" style="gap: 8px; flex-wrap: wrap">
      <input ref="inputEl" type="file" accept="video/*" class="file-hidden" @change="pick" />
      <n-button size="tiny" secondary :disabled="uploading" @click="inputEl && inputEl.click()">
        {{ hasFile ? '替换视频' : '上传视频' }}
      </n-button>
      <span v-if="hasFile" class="muted grow" style="font-size: 12px">{{ fileName }}</span>
      <span v-else class="muted grow" style="font-size: 12px">未上传（可在此上传后再「语音转文字」）</span>
      <n-button v-if="hasFile" size="tiny" quaternary type="error" :loading="uploading" @click="$emit('remove')">删除视频文件</n-button>
    </div>
  </div>
</template>

<script setup>
import { ref } from 'vue'

defineProps({
  hasFile: { type: Boolean, default: false },
  fileName: { type: String, default: '' },
  uploading: { type: Boolean, default: false }
})
const emit = defineEmits(['upload', 'remove'])
const inputEl = ref(null)

function pick(e) {
  const f = e.target.files[0]
  if (inputEl.value) inputEl.value.value = ''
  if (f) emit('upload', f)
}
</script>
