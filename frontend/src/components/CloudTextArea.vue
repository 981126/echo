<template>
  <div class="form-item">
    <label class="form-label">文案 / 原始文字（可选）</label>
    <n-input :value="modelValue" type="textarea" :rows="5" placeholder="粘贴你的口播文案或字幕，转本地素材后可用于 AI 学习" @update:value="$emit('update:modelValue', $event)" />
  </div>
</template>

<script setup>
defineProps({ modelValue: { type: String, default: '' } })
defineEmits(['update:modelValue'])
</script>
