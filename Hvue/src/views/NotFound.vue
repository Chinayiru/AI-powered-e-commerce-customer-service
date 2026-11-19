<script setup>
// 404 兜底页。
</script>

<template>
  <div class="page page--narrow">
    <div class="page-head">
      <div>
        <div class="eyebrow">404</div>
        <h1 class="title">页面不存在</h1>
        <p class="subtitle">地址可能已经变化，请回到客户入口或坐席工作台。</p>
      </div>
    </div>
    <div class="panel">
      <div class="panel-body">
        <RouterLink class="btn btn--primary" to="/">回到客户入口</RouterLink>
      </div>
    </div>
  </div>
</template>
