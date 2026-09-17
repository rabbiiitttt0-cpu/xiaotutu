/**
 * 认证 API
 */
import axios from 'axios'
import { friendlyHttpMessage } from './index'

const authApi = axios.create({
  baseURL: '/api/auth',
  timeout: 15000,
})

// 注入Token
authApi.interceptors.request.use((config) => {
  const token = localStorage.getItem('access_token')
  if (token) {
    config.headers.Authorization = `Bearer ${token}`
  }
  return config
})

// 401自动跳转登录
authApi.interceptors.response.use(
  (response) => response,
  (error) => {
    if (error.response?.status === 401 && window.location.pathname !== '/login') {
      localStorage.removeItem('access_token')
      localStorage.removeItem('refresh_token')
      localStorage.removeItem('user_info')
      window.location.href = '/login'
    }
    return Promise.reject(friendlyHttpMessage(error))
  }
)

// ===== 认证 =====
export const auth = {
  register: (data) => authApi.post('/register', data),
  login: (data) => authApi.post('/login', data),
  refresh: (refresh_token) => authApi.post('/refresh', { refresh_token }),
  getMe: () => authApi.get('/me'),
  updateMe: (data) => authApi.put('/me', data),
  changePassword: (data) => authApi.put('/password', data),
}

// ===== 管理员：用户管理 =====
export const adminUsers = {
  list: () => authApi.get('/admin/users'),
  create: (data) => authApi.post('/admin/users', data),
  update: (id, data) => authApi.put(`/admin/users/${id}`, data),
  delete: (id) => authApi.delete(`/admin/users/${id}`),
  permanentDelete: (id) => authApi.delete(`/admin/users/${id}/permanent`),
}
