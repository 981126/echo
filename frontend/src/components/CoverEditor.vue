<template>
  <div class="row" style="gap: 18px; align-items: flex-start">
    <div class="cover-edit" @click="inputEl && inputEl.click()">
      <img v-if="coverUrl" :src="coverUrl" alt="封面" />
      <span v-else>上传封面</span>
    </div>
    <input ref="inputEl" type="file" accept="image/jpeg,image/png" class="file-hidden" @change="onPick" />
    <div class="grow muted" style="font-size: 12px">
      <div style="margin-top: 4px">jpg / png，点击图片上传或替换</div>
      <n-button v-if="coverUrl" size="tiny" quaternary type="error" style="margin-top: 8px" @click="$emit('remove')">移除封面</n-button>
    </div>
  </div>
</template>

<script setup>
import { ref } from 'vue'

defineProps({
  coverUrl: { type: String, default: null }
})
const emit = defineEmits(['change', 'remove'])
const inputEl = ref(null)

function onPick(e) {
  const f = e.target.files[0]
  if (inputEl.value) inputEl.value.value = ''
  if (f) emit('change', f)
}
</script>
