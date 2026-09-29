import axios from 'axios'

// ===== HTTP错误中文友好化（无后端detail时改写error.message）=====
// 各模块 catch 里 e.response?.data?.detail || e.message 自动生效
export function friendlyHttpMessage(error) {
  if (error.response?.data?.detail) return error  // 后端已给中文说明，不动
  const status = error.response?.status
  const MAP = {
    400: '请求参数有误',
    403: '无权执行此操作',
    404: '请求的内容不存在',
    413: '上传文件过大，超出服务器限制',
    500: '服务器内部错误，请稍后重试或联系管理员',
    502: '服务暂时不可用，请稍后重试',
    503: '服务暂时不可用，请稍后重试',
    504: '服务响应超时，请稍后重试',
  }
  if (!error.response) {
    error.message = '网络异常或请求超时，请检查网络后重试'
  } else if (status === 401) {
    // 401由拦截器统一跳登录，保留原样
  } else {
    error.message = MAP[status] || `请求失败（状态码 ${status}）`
  }
  return error
}

// ===== 401自动续期（v4.9.4）=====
// access_token过期后用refresh_token静默换新并重试原请求，
// 只有refresh也失败才跳登录。此前refresh机制存在但无人调用，导致30分钟必掉线。
// 单飞模式：并发401共享同一次刷新。
let _refreshPromise = null
function _tryRefreshToken() {
  if (!_refreshPromise) {
    const rt = localStorage.getItem('refresh_token')
    if (!rt) return Promise.reject(new Error('no refresh token'))
    _refreshPromise = axios.post('/api/auth/refresh', { refresh_token: rt })
      .then(res => {
        localStorage.setItem('access_token', res.data.access_token)
        localStorage.setItem('refresh_token', res.data.refresh_token)
      })
      .finally(() => { _refreshPromise = null })
  }
  return _refreshPromise
}

// 401处理器：能续期就续期重试，不能才跳登录
export async function handle401WithRefresh(error, instance) {
  const original = error.config || {}
  const url = original.url || ''
  if (error.response?.status === 401 && !original._retried
      && !url.includes('/auth/login') && !url.includes('/auth/refresh')) {
    original._retried = true
    try {
      await _tryRefreshToken()
      original.headers = original.headers || {}
      original.headers.Authorization = `Bearer ${localStorage.getItem('access_token')}`
      return instance(original)
    } catch (e) { /* 续期失败，走下面跳登录 */ }
  }
  if (error.response?.status === 401 && window.location.pathname !== '/login') {
    localStorage.removeItem('access_token')
    localStorage.removeItem('refresh_token')
    localStorage.removeItem('user_info')
    window.location.href = '/login'
  }
  return Promise.reject(friendlyHttpMessage(error))
}

const api = axios.create({
  baseURL: '/api',
  timeout: 30000,
})

// 请求拦截器：注入认证Token
api.interceptors.request.use((config) => {
  const token = localStorage.getItem('access_token')
  if (token) {
    config.headers.Authorization = `Bearer ${token}`
  }
  return config
})

// 响应拦截器：401自动续期，失败才跳登录
api.interceptors.response.use(
  (response) => response,
  (error) => handle401WithRefresh(error, api)
)

// ===== 带认证的文件下载（替代 window.open 裸开URL，后者会被401）=====
// 用法：downloadWithAuth('/disclosure/records/1/download', '交底.docx')
export async function downloadWithAuth(path, filename) {
  const resp = await api.get(path.replace(/^\/api/, ''), { responseType: 'blob' })
  const blobUrl = URL.createObjectURL(resp.data)
  const a = document.createElement('a')
  a.href = blobUrl
  a.download = filename || 'download'
  a.click()
  URL.revokeObjectURL(blobUrl)
}

const llmApi = axios.create({
  baseURL: '/api',
  timeout: 120000, // LLM调用可能较慢
})

// LLM请求也注入Token
llmApi.interceptors.request.use((config) => {
  const token = localStorage.getItem('access_token')
  if (token) {
    config.headers.Authorization = `Bearer ${token}`
  }
  return config
})

// LLM响应错误：401自动续期 + 中文友好化
llmApi.interceptors.response.use(
  (response) => response,
  (error) => handle401WithRefresh(error, llmApi)
)

// ===== 识图 =====
export const drawing = {
  upload: (file) => {
    const formData = new FormData()
    formData.append('file', file)
    return api.post('/drawing/upload', formData, {
      headers: { 'Content-Type': 'multipart/form-data' },
      timeout: 600000,  // 上传=同步解析（DWG转换+渲染），大图可达数分钟；
                        // 默认30s必超时误报"网络异常"（nginx 499 实锤）。对齐 nginx proxy_read_timeout 600s
    })
  },
  chat: (data) => llmApi.post('/drawing/chat', data),
  list: () => api.get('/drawing/list'),
  materials: (data) => llmApi.post('/drawing/materials', data),
  briefing: (data) => llmApi.post('/drawing/briefing', data),
  saveSession: (data) => api.post('/drawing/sessions', data),
  listSessions: () => api.get('/drawing/sessions'),
  getSession: (id) => api.get(`/drawing/sessions/${id}`),
  deleteSession: (id) => api.delete(`/drawing/sessions/${id}`),
  image: (fileId) => api.get(`/drawing/${fileId}/image`, { responseType: 'blob' }),
  imageSvg: (fileId) => api.get(`/drawing/${fileId}/image?fmt=svg`, { responseType: 'blob' }),
  imageN: (fileId, n) => api.get(`/drawing/${fileId}/image/${n}`, { responseType: 'blob' }),
  pages: (fileId) => api.get(`/drawing/${fileId}/pages`),
  usage: () => api.get('/drawing/usage'),
  createSet: (data) => api.post('/drawing/sets', data),
  getSet: (id) => api.get(`/drawing/sets/${id}`),
  removeSheet: (setId, fileId) => api.delete(`/drawing/sets/${setId}/sheets/${fileId}`),
  saveSetSummary: (id, data) => api.put(`/drawing/sets/${id}/summary`, data),
  projectSet: (data) => api.post('/drawing/project_set', data),
  asr: (file) => {
    const formData = new FormData()
    formData.append('file', file)
    return llmApi.post('/drawing/asr', formData, {
      headers: { 'Content-Type': 'multipart/form-data' },
    })
  },
}

// ===== 项目图纸管理 =====
export const projects = {
  // 超管
  list: () => api.get('/projects'),
  create: (data) => api.post('/projects', data),
  update: (id, data) => api.put(`/projects/${id}`, data),
  remove: (id) => api.delete(`/projects/${id}`),
  members: (id) => api.get(`/projects/${id}/members`),
  addMember: (id, userId) => api.post(`/projects/${id}/members`, { user_id: userId }),
  removeMember: (id, userId) => api.delete(`/projects/${id}/members/${userId}`),
  uploadZip: (id, file) => {
    const formData = new FormData()
    formData.append('file', file)
    return api.post(`/projects/${id}/drawings/zip`, formData, {
      headers: { 'Content-Type': 'multipart/form-data' },
      timeout: 600000,  // 400MB+ 整卷图纸压缩包放宽到 10 分钟（对齐 nginx 超时）
    })
  },
  patchDrawing: (id, did, data) => api.patch(`/projects/${id}/drawings/${did}`, data),
  removeDrawing: (id, did) => api.delete(`/projects/${id}/drawings/${did}`),
  // 成员
  mine: () => api.get('/projects/mine'),
  drawings: (id, scope = 'frequent') => api.get(`/projects/${id}/drawings`, { params: { scope } }),
  drawingInfo: (id, did) => api.get(`/projects/${id}/drawings/${did}/info`),
  sets: (id) => api.get(`/projects/${id}/sets`),
  createSet: (id, data) => api.post(`/projects/${id}/sets`, data),
  updateSet: (id, sid, data) => api.put(`/projects/${id}/sets/${sid}`, data),
  removeSet: (id, sid) => api.delete(`/projects/${id}/sets/${sid}`),
  sessions: (id) => api.get(`/projects/${id}/sessions`),
  getSession: (id, sid) => api.get(`/projects/${id}/sessions/${sid}`),
  removeSession: (id, sid) => api.delete(`/projects/${id}/sessions/${sid}`),
  drawingsTree: (id) => api.get(`/projects/${id}/drawings-tree`),
  relations: (id) => api.get(`/projects/${id}/relations`),
  refreshRelations: (id) => llmApi.post(`/projects/${id}/relations/refresh`),
}

// ===== 审计日志 =====
export const auth = {
  changePassword: (data) => api.put('/auth/password', data),
}

export const audit = {
  logs: (params) => api.get('/audit/logs', { params }),
  eventTypes: () => api.get('/audit/event-types'),
  llmCalls: (params) => api.get('/audit/llm-calls', { params }),
  llmStats: () => api.get('/audit/llm-stats'),
  errors: (params) => api.get('/audit/errors', { params }),
}

// 鉴权图片获取（blob → objectURL，调用方负责 revoke）
export async function fetchImageBlob(url) {
  const resp = await api.get(url.replace(/^\/api/, ''), { responseType: 'blob' })
  return URL.createObjectURL(resp.data)
}

export default api
