<template>
  <div class="form-item full">
    <label class="form-label">标签（逗号分隔，自由填写）</label>
    <n-input :value="modelValue" placeholder="干货, 反常识, 口播, 面试, 赚钱" @update:value="$emit('update:modelValue', $event)" />
    <span class="muted" style="font-size: 12px">命中 求职/面试/赚钱/知识/其他 的词会同时进入数据统计（复盘/缺口用）</span>
  </div>
</template>

<script setup>
defineProps({ modelValue: { type: String, default: '' } })
defineEmits(['update:modelValue'])
</script>
