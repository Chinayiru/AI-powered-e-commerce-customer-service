<script setup>
import { computed } from 'vue'
import { RouterLink, RouterView, useRoute } from 'vue-router'
import { session } from './store'

const route = useRoute()
const onAgent = computed(() => route.path.startsWith('/agent'))
</script>

<template>
  <div class="app-shell">
    <header class="topbar">
      <RouterLink class="brand" to="/">
        <span class="brand-mark" aria-hidden="true">售</span>
        <span class="brand-text">
          <strong>售后助手</strong>
          <small>After-sale Copilot</small>
        </span>
      </RouterLink>

      <nav class="nav" aria-label="主导航">
        <RouterLink class="nav-link" :class="{ 'is-active': !onAgent && route.path !== '/about' }" to="/">
          客户入口
        </RouterLink>
        <RouterLink class="nav-link" :class="{ 'is-active': onAgent }" to="/agent">
          坐席工作台
        </RouterLink>
        <RouterLink class="nav-link" :class="{ 'is-active': route.path === '/about' }" to="/about">
          演示说明
        </RouterLink>
      </nav>

      <div class="topbar-right">
        <span class="env-badge"><span class="dot"></span>演示环境 · 未真实退款</span>
        <span class="user-chip">{{ onAgent ? '坐席演示' : session.userId }}</span>
      </div>
    </header>

    <main class="app-main">
      <RouterView />
    </main>

    <footer class="app-footer">
      <span>售后辅助处理 Agent · Java 裁决 / Python 只读 / 人工确认</span>
      <span class="footer-mono">SIMULATED</span>
    </footer>
  </div>
</template>
