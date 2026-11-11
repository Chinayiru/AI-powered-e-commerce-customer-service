<script setup>
defineProps({
  title: { type: String, default: '暂无内容' },
  description: { type: String, default: '' }
})
</script>

<template>
  <div class="empty">
    <div class="empty-mark" aria-hidden="true">·</div>
    <strong>{{ title }}</strong>
    <p v-if="description">{{ description }}</p>
    <slot />
  </div>
</template>
