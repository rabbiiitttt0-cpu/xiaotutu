import { createRouter, createWebHistory } from 'vue-router'

const routes = [
  {
    path: '/login',
    name: 'Login',
    component: () => import('../views/Login.vue'),
    meta: { title: '登录', requiresAuth: false },
  },
  {
    path: '/',
    redirect: '/drawing-review',
  },
  {
    path: '/drawing-review',
    name: 'DrawingReview',
    component: () => import('../views/DrawingReview.vue'),
    meta: { title: '识图助手' },
  },
  {
    path: '/admin/users',
    name: 'AdminUsers',
    component: () => import('../views/admin/UserManagement.vue'),
    meta: { title: '用户管理', requiresSuperAdmin: true },
  },
  {
    path: '/admin/audit-logs',
    name: 'AdminAuditLogs',
    component: () => import('../views/admin/AuditLogs.vue'),
    meta: { title: '日志查询', requiresSuperAdmin: true },
  },
]

const router = createRouter({
  history: createWebHistory(),
  routes,
})

// 路由守卫：未登录跳转登录页；requiresSuperAdmin 拦截越权访问
router.beforeEach((to, from, next) => {
  const token = localStorage.getItem('access_token')
  const requiresAuth = to.meta.requiresAuth !== false
  if (requiresAuth && !token) {
    next({ path: '/login', query: { redirect: to.fullPath } })
  } else if (to.path === '/login' && token) {
    next('/')
  } else if (to.meta.requiresSuperAdmin) {
    let userInfo = null
    try { userInfo = JSON.parse(localStorage.getItem('user_info') || 'null') } catch { userInfo = null }
    const isSuperAdmin = userInfo?.is_super_admin || false
    if (!isSuperAdmin) {
      next('/')
    } else {
      next()
    }
  } else {
    next()
  }
})

// 服务端重建后，长驻页面懒加载旧hash chunk会404：整页刷新自愈
router.onError((error, to) => {
  const msg = String(error?.message || '')
  if (/dynamically imported module|Importing a module script|Loading chunk|Loading CSS chunk/i.test(msg)) {
    if (!sessionStorage.getItem('chunk_reloaded')) {
      sessionStorage.setItem('chunk_reloaded', '1')
      window.location.href = to?.fullPath || window.location.href
    }
  }
})
router.afterEach(() => sessionStorage.removeItem('chunk_reloaded'))

export default router
