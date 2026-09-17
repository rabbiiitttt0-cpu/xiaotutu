/**
 * 用户认证 Store
 */
import { defineStore } from 'pinia'
import { auth } from '../api/auth'

export const useAuthStore = defineStore('auth', {
  state: () => ({
    user: JSON.parse(localStorage.getItem('user_info') || 'null'),
    accessToken: localStorage.getItem('access_token') || '',
    refreshToken: localStorage.getItem('refresh_token') || '',
  }),

  getters: {
    isLoggedIn: (state) => !!state.accessToken,
    isSuperAdmin: (state) => state.user?.is_super_admin || false,
    userId: (state) => state.user?.id || null,
    username: (state) => state.user?.username || '',
    displayName: (state) => state.user?.display_name || state.user?.username || '',

    // 功能模块权限
  },

  actions: {
    // 登录
    async login(username, password) {
      const res = await auth.login({ username, password })
      const data = res.data
      this.accessToken = data.access_token
      this.refreshToken = data.refresh_token
      localStorage.setItem('access_token', data.access_token)
      localStorage.setItem('refresh_token', data.refresh_token)

      // 获取用户信息
      await this.fetchUser()
      return data
    },

    // 注册
    async register(userData) {
      const res = await auth.register(userData)
      return res.data
    },

    // 获取当前用户信息
    async fetchUser() {
      try {
        const res = await auth.getMe()
        this.user = res.data
        localStorage.setItem('user_info', JSON.stringify(res.data))
        return res.data
      } catch (e) {
        this.logout()
        throw e
      }
    },

    // 刷新Token
    async refreshAccessToken() {
      try {
        const res = await auth.refresh(this.refreshToken)
        const data = res.data
        this.accessToken = data.access_token
        this.refreshToken = data.refresh_token
        localStorage.setItem('access_token', data.access_token)
        localStorage.setItem('refresh_token', data.refresh_token)
        return data
      } catch (e) {
        this.logout()
        throw e
      }
    },

    // 退出登录
    logout() {
      this.user = null
      this.accessToken = ''
      this.refreshToken = ''
      localStorage.removeItem('access_token')
      localStorage.removeItem('refresh_token')
      localStorage.removeItem('user_info')
    },
  },
})
