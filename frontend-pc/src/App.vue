<template>
  <router-view v-if="isLoginPage" />
  <div v-else class="app-shell">
    <!-- 侧边栏 -->
    <aside class="sidebar">
      <div class="sidebar-header">
        <img src="/sidebar-logo.png" class="sidebar-logo" />
        <span class="sidebar-title">看图兔</span>
      </div>
      <nav class="sidebar-menu">
        <div
          v-for="m in menus" :key="m.path"
          :class="['menu-item', { active: route.path === m.path }]"
          @click="router.push(m.path)"
        >
          <el-icon :size="18"><component :is="m.icon" /></el-icon>
          <span>{{ m.label }}</span>
        </div>
      </nav>
      <div class="sidebar-bottom">
        <div class="user-info">
          <span class="user-name">{{ authStore.displayName }}</span>
          <span class="user-role">{{ authStore.isSuperAdmin ? '管理员' : '成员' }}</span>
        </div>
        <div class="user-actions">
          <span class="action-item" @click="router.push('/drawing-review')">识图助手</span>
          <span class="action-item" @click="handleLogout">退出登录</span>
        </div>
      </div>
    </aside>

    <!-- 主内容区 -->
    <main class="main-content">
      <router-view v-slot="{ Component }">
        <keep-alive :max="5" :include="['DrawingReview']">
          <component :is="Component" :key="route.fullPath" />
        </keep-alive>
      </router-view>
    </main>
  </div>
</template>

<script setup>
import { computed } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { useAuthStore } from './stores/auth'

const route = useRoute()
const router = useRouter()
const authStore = useAuthStore()

const isLoginPage = computed(() => route.path === '/login')

const menus = computed(() => [
  { path: '/drawing-review', label: '识图助手', icon: 'Crop' },
  ...(authStore.isSuperAdmin
    ? [
        { path: '/admin/users', label: '用户管理', icon: 'UserFilled' },
        { path: '/admin/audit-logs', label: '日志查询', icon: 'Document' },
      ]
    : []),
])

function handleLogout() {
  localStorage.removeItem('access_token')
  localStorage.removeItem('refresh_token')
  localStorage.removeItem('user_info')
  router.push('/login')
}
</script>

<style>
* { box-sizing: border-box; }
html, body, #app { margin: 0; padding: 0; height: 100%; }
body { font-family: -apple-system, "PingFang SC", "Microsoft YaHei", sans-serif; background: #f5f7fa; }

.app-shell { display: flex; height: 100vh; overflow: hidden; }

.sidebar {
  width: 220px;
  flex-shrink: 0;
  display: flex;
  flex-direction: column;
  background: #003a6e;
  color: #fff;
}
.sidebar-header {
  display: flex;
  align-items: center;
  gap: 10px;
  padding: 18px 16px;
  border-bottom: 1px solid rgba(255,255,255,0.1);
}
.sidebar-logo { width: 28px; height: 28px; }
.sidebar-title { font-size: 18px; font-weight: 600; }
.sidebar-menu { flex: 1; padding: 12px 8px; overflow-y: auto; }
.menu-item {
  display: flex;
  align-items: center;
  gap: 10px;
  padding: 12px 14px;
  margin-bottom: 4px;
  border-radius: 8px;
  cursor: pointer;
  color: rgba(255,255,255,0.85);
  transition: background 0.2s;
}
.menu-item:hover { background: rgba(255,255,255,0.1); }
.menu-item.active { background: rgba(255,255,255,0.2); color: #fff; }
.sidebar-bottom { padding: 16px; border-top: 1px solid rgba(255,255,255,0.1); }
.user-info { display: flex; flex-direction: column; gap: 2px; margin-bottom: 12px; }
.user-name { font-weight: 600; }
.user-role { font-size: 12px; color: rgba(255,255,255,0.7); }
.user-actions { display: flex; gap: 14px; }
.action-item { font-size: 13px; color: rgba(255,255,255,0.7); cursor: pointer; }
.action-item:hover { color: #fff; }

.main-content {
  flex: 1;
  min-width: 0;
  overflow: auto;
  background: #f5f7fa;
}

/* 移动端（窄屏）侧边栏折叠 */
@media (max-width: 768px) {
  .sidebar { width: 60px; }
  .sidebar-title, .menu-item span, .user-info, .user-actions { display: none; }
  .sidebar-header { justify-content: center; padding: 14px 0; }
  .menu-item { justify-content: center; padding: 12px 0; }
}
</style>
