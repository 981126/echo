<template>
  <div class="form-grid">
    <div class="form-item">
      <label class="form-label">平台（可多选）</label>
      <n-select multiple :options="platformOptions" :value="platforms" placeholder="选择平台" @update:value="$emit('update:platforms', $event)" />
    </div>
    <div class="form-item">
      <label class="form-label">状态</label>
      <n-select :options="statusOptions" :value="status" @update:value="$emit('update:status', $event)" />
    </div>
    <div class="form-item">
      <label class="form-label">商务广告</label>
      <n-checkbox :checked="isAd" @update:checked="$emit('update:isAd', $event)">广告（不参与人设学习）</n-checkbox>
    </div>
    <div class="form-item">
      <label class="form-label">广告价格（元）</label>
      <n-input-number :value="adPrice" :min="0" placeholder="0" style="width: 100%" @update:value="$emit('update:adPrice', $event)" />
    </div>
    <div class="form-item">
      <label class="form-label">计划发布时间</label>
      <n-date-picker :value="plannedTs" type="datetime" clearable style="width: 100%" @update:value="$emit('update:plannedTs', $event)" />
    </div>
    <div class="form-item">
      <label class="form-label">实际发布时间</label>
      <n-date-picker :value="publishedTs" type="datetime" clearable style="width: 100%" @update:value="$emit('update:publishedTs', $event)" />
    </div>
  </div>
</template>

<script setup>
defineProps({
  platformOptions: { type: Array, default: () => [] },
  statusOptions: { type: Array, default: () => [] },
  platforms: { type: Array, default: () => [] },
  status: { type: String, default: 'planned' },
  isAd: { type: Boolean, default: false },
  adPrice: { type: Number, default: null },
  plannedTs: { type: Number, default: null },
  publishedTs: { type: Number, default: null }
})
defineEmits(['update:platforms', 'update:status', 'update:isAd', 'update:adPrice', 'update:plannedTs', 'update:publishedTs'])
</script>
