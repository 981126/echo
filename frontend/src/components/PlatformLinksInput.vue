<template>
  <div class="form-item">
    <label class="form-label">平台链接（用于同步数据，可手动填写）</label>
    <div style="display: flex; flex-direction: column; gap: 8px">
      <div v-for="p in order" :key="p" class="row" style="gap: 8px; align-items: center">
        <span class="plat-tag">{{ platformName(p) }}</span>
        <n-input :value="links[p]" :placeholder="'粘贴' + platformName(p) + '作品链接'" clearable @update:value="setVal(p, $event)" />
      </div>
    </div>
    <span class="muted" style="font-size: 12px">填了哪个平台就同步哪个；已绑定的会自动带出。保存后点「同步数据」拉取最新数据</span>
  </div>
</template>

<script setup>
import { platformName } from '../lib/format'

const props = defineProps({
  links: { type: Object, default: () => ({ douyin: '', bilibili: '', xiaohongshu: '' }) }
})
const emit = defineEmits(['update:links'])
const order = ['douyin', 'bilibili', 'xiaohongshu']

function setVal(p, v) {
  emit('update:links', { ...props.links, [p]: v })
}
</script>

<style scoped>
.plat-tag {
  flex: 0 0 58px;
  text-align: center;
  padding: 3px 0;
  border-radius: 6px;
  color: #a34f2c;
  font-size: 12px;
  font-weight: 600;
  background: rgba(163, 79, 44, 0.08);
}
</style>
