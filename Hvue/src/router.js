import { createRouter, createWebHistory } from 'vue-router'

// 页面按需加载，首屏只加载客户入口。
const routes = [
  {
    path: '/',
    name: 'consumer-home',
    component: () => import('./views/ConsumerHome.vue'),
    meta: { title: '客户入口' }
  },
  {
    path: '/tickets/:ticketId',
    name: 'consumer-ticket',
    component: () => import('./views/ConsumerTicket.vue'),
    meta: { title: '我的工单' }
  },
  {
    path: '/agent',
    name: 'agent-inbox',
    component: () => import('./views/AgentInbox.vue'),
    meta: { title: '坐席检索' }
  },
  {
    path: '/agent/tickets/:ticketId',
    name: 'agent-ticket',
    component: () => import('./views/AgentTicket.vue'),
    meta: { title: '坐席工作台' }
  },
  {
    path: '/about',
    name: 'about',
    component: () => import('./views/AboutView.vue'),
    meta: { title: '演示说明' }
  },
  {
    path: '/:pathMatch(.*)*',
    name: 'not-found',
    component: () => import('./views/NotFound.vue'),
    meta: { title: '页面不存在' }
  }
]

const router = createRouter({
  history: createWebHistory(),
  routes,
  scrollBehavior: () => ({ top: 0 })
})

router.afterEach((to) => {
  document.title = `${to.meta.title || '售后助手'} · 售后助手`
})

export default router
