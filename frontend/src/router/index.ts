import { createRouter, createWebHistory } from 'vue-router'

const router = createRouter({
  history: createWebHistory(),
  routes: [
    { path: '/', redirect: '/app' },
    {
      path: '/app/:phase?',
      name: 'workspace',
      component: () => import('../features/workspace/WorkspaceView.vue'),
      beforeEnter: (to) => (to.params.phase === 'video' ? { path: '/app/suite' } : true),
    },
    {
      path: '/admin/:section?',
      name: 'admin',
      component: () => import('../features/admin/AdminView.vue'),
    },
  ],
})

export default router

