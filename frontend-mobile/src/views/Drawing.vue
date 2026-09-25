<template>
  <div class="drawing-page">
    <!-- 顶部：logo 菜单 + 图幅切换 + 上传 -->
    <div class="top-bar">
      <button class="logo-btn" @click="showLogoMenu = true">
        <img src="/logo.png" alt="菜单" class="logo-img" />
      </button>
      <van-dropdown-menu v-if="sheets.length > 1">
        <van-dropdown-item :model-value="activeSheetId" :options="sheetOptions" @change="onSheetChange" />
      </van-dropdown-menu>
      <span v-else class="top-title">{{ sheets[0]?.filename || '识图助手' }}</span>
      <van-button size="small" type="primary" plain @click="openProjectPicker">项目图纸</van-button>
      <van-button size="small" type="primary" plain @click="openUploader">上传图纸</van-button>
    </div>

    <!-- 图纸预览（触摸缩放拖动 + 滑动翻页） -->
    <div class="preview-area" ref="previewRef" @touchstart.prevent="onTouchStart" @touchmove.prevent="onTouchMove" @touchend="onTouchEnd">
      <img v-if="displaySrc" :src="displaySrc" class="preview-img" :style="imgStyle" />
      <div v-else class="preview-empty" @click="openUploader">
        <van-icon name="plus" size="48" color="#c8c9cc" />
        <p>上传图纸开始识别</p>
      </div>
      <div v-if="displaySrc" class="zoom-hint">{{ Math.round(scale * 100) }}%</div>
      <!-- 框选截图区域 -->
      <div v-if="snipRect" class="snip-rect" :style="snipRectStyle" />
      <!-- 多页指示器 + 翻页按钮 -->
      <div v-if="displaySrc && previewUrls.length > 1" class="page-indicator">
        <button class="page-btn" :disabled="pageIdx === 0" @click.stop="prevPage">‹</button>
        <span class="page-text">{{ pageIdx + 1 }} / {{ previewUrls.length }}</span>
        <button class="page-btn" :disabled="pageIdx >= previewUrls.length - 1" @click.stop="nextPage">›</button>
      </div>
    </div>

    <!-- 底部：功能 tab -->
    <div class="bottom-panel" :class="{ 'upload-open': showUploader }">
      <van-tabs v-model:active="activeTab" shrink>
        <van-tab title="问答" name="chat">
          <div class="chat-panel">
            <div class="chat-messages" ref="chatRef">
              <div v-if="!messages.length" class="chat-empty">上传图纸后，这里可以提问</div>
              <div v-for="(msg, i) in messages" :key="i" :class="['msg', msg.role]">
                <img v-if="msg.snip" :src="msg.snip" class="msg-snip" />
                <div class="msg-bubble">{{ msg.content }}</div>
                <div v-if="msg.referenced?.length" class="msg-ref">
                  参考图幅：{{ msg.referenced.map(r => r.filename).join('、') }}
                </div>
              </div>
              <div v-if="chatLoading" class="msg assistant"><div class="msg-bubble">分析中…</div></div>
            </div>
            <!-- 内联上传区（不遮挡问答输入框） -->
            <div v-if="showUploader" class="upload-inline">
              <div class="upload-inline-head">
                <span class="upload-inline-title">上传图纸</span>
                <van-icon name="cross" size="18" color="#969799" @click="showUploader = false" />
              </div>
              <van-uploader :after-read="onFileRead" multiple accept=".dxf,.dwg,.pdf" />
              <p class="uploader-tip">支持 .dxf / .dwg / .pdf，可多选组成图纸集</p>
              <div v-if="fileList.length" class="file-list">
                <div v-for="(f, i) in fileList" :key="i" class="file-item">
                  <span>{{ f.name }}</span>
                  <van-icon name="close" @click="fileList.splice(i, 1)" />
                </div>
              </div>
              <van-button type="primary" block round size="small" :loading="uploading" @click="doUpload" style="margin-top: 8px">
                {{ uploading ? '解析中…' : '解析图纸' }}
              </van-button>
            </div>
            <div v-if="snipBlobUrl" class="snip-chip">
              <img :src="snipBlobUrl" alt="框选截图" />
              <span>已框选局部截图，提问将针对该区域</span>
              <van-icon name="close" @click="snipBlobUrl = ''" />
            </div>
            <div class="chat-input">
              <van-button
                size="small" type="primary" :plain="!snipMode"
                @click="snipMode ? (snipMode = false) : enterSnipMode()"
              >{{ snipMode ? '取消框选' : '截图' }}</van-button>
              <van-field
                v-model="question"
                placeholder="输入问题，或点🎤语音"
                :border="false"
                @keyup.enter="sendQuestion"
              />
              <van-button size="small" :type="recognizing ? 'danger' : 'primary'"
                icon="service-o" :loading="voiceUploading" @click="toggleVoice" />
              <van-button size="small" type="primary" :loading="chatLoading" @click="sendQuestion">发送</van-button>
            </div>
          </div>
        </van-tab>

        <van-tab title="材料" name="materials">
          <div class="sub-panel">
            <van-button size="small" type="primary" plain @click="extractMaterials" :loading="materialsLoading">
              {{ materials.length ? '重新提取' : '提取材料表' }}
            </van-button>
            <van-empty v-if="!materials.length" description="点击上方提取材料" />
            <div v-else class="materials-list">
              <div v-for="(m, i) in materials" :key="i" class="material-item">
                <div class="m-name">{{ m.name }}</div>
                <div class="m-spec">{{ m.spec || '—' }} · {{ m.unit || '' }}</div>
              </div>
            </div>
          </div>
        </van-tab>

        <van-tab title="交底" name="briefing">
          <div class="sub-panel">
            <van-field v-model="briefingProjectName" label="项目名称" placeholder="可选" />
            <van-button size="small" type="primary" plain @click="generateBriefing" :loading="briefingLoading">
              {{ briefingContent ? '重新生成' : '生成交底文件' }}
            </van-button>
            <div v-if="briefingContent" class="briefing-content">{{ briefingContent }}</div>
          </div>
        </van-tab>
      </van-tabs>
    </div>

    <!-- logo 菜单：切换端 / 账号信息 / 修改密码 / 退出登录 -->
    <van-action-sheet
      v-model:show="showLogoMenu"
      :actions="logoMenuActions"
      cancel-text="取消"
      close-on-click-action
      @select="onLogoMenuSelect"
    />

    <!-- 账号信息弹窗 -->
    <van-popup v-model:show="showAccountInfo" position="bottom" round>
      <div class="uploader-panel">
        <h4>账号信息</h4>
        <div class="account-info">
          <p><strong>用户名：</strong>{{ authStore.displayName || authStore.username }}</p>
          <p><strong>角色：</strong>{{ authStore.isSuperAdmin ? '管理员' : '成员' }}</p>
        </div>
        <van-button block round style="margin-top: 16px" @click="showAccountInfo = false">关闭</van-button>
      </div>
    </van-popup>

    <!-- 修改密码弹窗 -->
    <van-popup v-model:show="showPwdPopup" position="bottom" round>
      <div class="uploader-panel">
        <h4>修改密码</h4>
        <van-field
          v-model="pwdForm.old_password"
          type="password"
          label="原密码"
          placeholder="请输入当前密码"
        />
        <van-field
          v-model="pwdForm.new_password"
          type="password"
          label="新密码"
          placeholder="至少 6 位"
        />
        <van-field
          v-model="pwdForm.confirm_password"
          type="password"
          label="确认新密码"
          placeholder="再次输入新密码"
        />
        <van-button
          type="primary" block round style="margin-top: 12px"
          :loading="pwdSubmitting" @click="submitChangePassword"
        >
          确定修改
        </van-button>
      </div>
    </van-popup>


    <!-- 项目图纸弹窗（预处理秒开 + 图纸集 + 5天会话） -->
    <van-popup v-model:show="showProjectPicker" position="bottom" round :style="{ maxHeight: '75%' }">
      <div class="uploader-panel">
        <h4>项目图纸</h4>
        <van-dropdown-menu v-if="myProjects.length">
          <van-dropdown-item
            :model-value="activeProjectId" :options="projectOptions"
            @change="onProjectChange"
          />
        </van-dropdown-menu>
        <van-empty v-else description="您还未加入任何项目，请联系管理员" image-size="60" />

        <template v-if="activeProjectId">
          <!-- 5天内会话 -->
          <template v-if="projSessions.length">
            <p class="uploader-tip" style="margin-bottom: 4px">最近会话（5天内，含上下文）</p>
            <div
              v-for="s in projSessions" :key="s.id" class="file-item"
              @click="restoreSession(s)"
            >
              <span>{{ s.title || '未命名会话' }} · {{ s.message_count }}条</span>
              <span style="color: #c8c9cc; font-size: 12px">至{{ s.expires_at.slice(5, 10) }}</span>
            </div>
          </template>

          <!-- 选图纸 / 图纸集 切换 -->
          <div class="pick-toggle">
            <button :class="['pick-toggle-btn', { active: projPickMode === 'browse' }]" @click="projPickMode = 'browse'">选图纸</button>
            <button :class="['pick-toggle-btn', { active: projPickMode === 'sets' }]" @click="projPickMode = 'sets'">图纸集</button>
          </div>

          <!-- 图纸集模式：点一个整组载入（管理员预设） -->
          <template v-if="projPickMode === 'sets'">
            <van-empty
              v-if="!projSets.length" image-size="40"
              description="暂无图纸集，请联系管理员在项目管理中预设"
            />
            <div
              v-for="s in projSets" :key="s.id" class="file-item"
              @click="selectedDrawingIds = [...s.drawing_ids]; applyProjectDrawings()"
            >
              <span>📁 {{ s.name }}</span>
              <span style="color: #c8c9cc; font-size: 12px">{{ s.drawing_ids.length }}张</span>
            </div>
          </template>

          <!-- 选图纸模式：按压缩包目录结构分组折叠 -->
          <template v-else>
            <div style="display: flex; justify-content: space-between; align-items: center">
              <p class="uploader-tip" style="margin: 4px 0">图纸（{{ showAll ? '全部' : '近期常用' }}）</p>
              <van-switch :model-value="showAll" size="20px" @update:model-value="showAll = $event" />
            </div>
            <div style="max-height: 200px; overflow-y: auto">
              <van-checkbox-group v-model="selectedDrawingIds">
                <template v-for="g in drawingGroups" :key="g.key">
                  <div class="dg-head" @click="toggleGroup(g)">
                    <span style="font-weight: 600">{{ g.name }}</span>
                    <span style="color: #969799; font-size: 12px">（{{ g.files.length }} 张）</span>
                    <van-icon :name="collapsedGroups[g.key] ? 'arrow-down' : 'arrow-up'" size="14" color="#969799" style="margin-left: auto" />
                  </div>
                  <template v-if="!collapsedGroups[g.key]">
                    <van-checkbox
                      v-for="f in g.files" :key="f.id" :name="f.id"
                      style="padding: 6px 4px 6px 16px"
                    >
                      {{ f.filename }}
                      <van-tag v-if="f.is_frequent" type="warning" size="medium">常用</van-tag>
                    </van-checkbox>
                  </template>
                </template>
                <van-empty
                  v-if="!drawingGroups.length" image-size="40"
                  :description="showAll ? '项目暂无已处理图纸' : '暂无常用图纸，打开开关看全部'"
                />
              </van-checkbox-group>
            </div>
          </template>

          <van-button
            type="primary" block round style="margin-top: 12px"
            :disabled="!selectedDrawingIds.length" :loading="projApplying"
            @click="applyProjectDrawings"
          >
            开始问答（已选 {{ selectedDrawingIds.length }} 张）
          </van-button>
        </template>
      </div>
    </van-popup>
  </div>
</template>

<script setup>
import { ref, computed, onMounted } from 'vue'
import { showToast, showSuccessToast } from 'vant'
import { drawing as drawingApi, projects as projectsApi } from '../api'
import { WavRecorder } from '../utils/wavRecorder'
import { auth as authApi } from '../api/auth'
import { useAuthStore } from '../stores/auth'

const authStore = useAuthStore()

// 上传
const showUploader = ref(false)
const fileList = ref([])

// 打开内联上传区：切到问答 tab 并展开，保持输入框可见
function openUploader() {
  activeTab.value = 'chat'
  showUploader.value = true
}
const uploading = ref(false)

// logo 菜单 + 修改密码
const showLogoMenu = ref(false)
const showAccountInfo = ref(false)
const showPwdPopup = ref(false)
const pwdSubmitting = ref(false)
const pwdForm = ref({ old_password: '', new_password: '', confirm_password: '' })
const logoMenuActions = [
  { name: '切换为电脑端', key: 'switch-pc' },
  { name: '账号信息', key: 'account-info' },
  { name: '修改密码', key: 'change-pwd' },
  { name: '退出登录', key: 'logout', color: '#ee0a24' },
]

function onLogoMenuSelect(action) {
  if (action.key === 'switch-pc') {
    window.location.href = '/pc'
  } else if (action.key === 'account-info') {
    showAccountInfo.value = true
  } else if (action.key === 'change-pwd') {
    pwdForm.value = { old_password: '', new_password: '', confirm_password: '' }
    showPwdPopup.value = true
  } else if (action.key === 'logout') {
    localStorage.removeItem('access_token')
    localStorage.removeItem('refresh_token')
    localStorage.removeItem('user_info')
    window.location.href = '/login'
  }
}

async function submitChangePassword() {
  const { old_password, new_password, confirm_password } = pwdForm.value
  if (!old_password) return showToast('请输入原密码')
  if (!new_password || new_password.length < 6) return showToast('新密码至少 6 位')
  if (new_password !== confirm_password) return showToast('两次输入的密码不一致')
  pwdSubmitting.value = true
  try {
    await authApi.changePassword({ old_password, new_password })
    showSuccessToast('密码修改成功')
    showPwdPopup.value = false
  } catch (e) {
    showToast(e.response?.data?.detail || e.message || '修改失败')
  } finally {
    pwdSubmitting.value = false
  }
}

// 图纸集
const setId = ref('')
const sheets = ref([])
const activeSheetId = ref('')

// 预览
const previewRef = ref(null)
const previewUrls = ref([])
const pageIdx = ref(0)
const scale = ref(1)
const pan = ref({ x: 0, y: 0 })
const displaySrc = computed(() => previewUrls.value[pageIdx.value])

const imgStyle = computed(() => ({
  transform: `translate(calc(-50% + ${pan.value.x}px), calc(-50% + ${pan.value.y}px)) scale(${scale.value})`,
}))

// 问答
const activeTab = ref('chat')
const messages = ref([])
const question = ref('')
const chatLoading = ref(false)
const chatRef = ref(null)

// 材料/交底
const materials = ref([])
const materialsLoading = ref(false)
const briefingProjectName = ref('')
const briefingContent = ref('')
const briefingLoading = ref(false)

const sheetOptions = computed(() => sheets.value.map(s => ({ text: s.filename, value: s.file_id })))

function onFileRead(file) {
  fileList.value.push(file.file)
}

async function doUpload() {
  if (!fileList.value.length) { showToast('请先选择图纸'); return }
  uploading.value = true
  activeProjectId.value = 0  // 本地上传：退出项目图纸模式
  projSessionId.value = 0
  try {
    const results = await Promise.allSettled(fileList.value.map(f => drawingApi.upload(f)))
    const fileIds = []
    results.forEach((r, i) => {
      if (r.status === 'fulfilled') { fileIds.push(r.value.data.file_id) }
    })
    if (fileIds.length) {
      const { data } = await drawingApi.createSet({ file_ids: fileIds, set_id: setId.value || '' })
      setId.value = data.set_id
      sheets.value = data.sheets
      activeSheetId.value = sheets.value[0]?.file_id
      await selectSheet(activeSheetId.value)
      fileList.value = []
      showUploader.value = false
      showSuccessToast(`图纸集已就绪（${sheets.value.length} 张）`)
      await autoSummarize()
    }
  } catch (e) {
    showToast('上传失败: ' + (e.response?.data?.detail || e.message))
  } finally {
    uploading.value = false
  }
}

function onSheetChange(fid) {
  activeSheetId.value = fid
  selectSheet(fid)
}

const totalPages = ref(1)

let sheetReqToken = 0  // 快速连续切图时，丢弃过期请求的结果
async function selectSheet(fid) {
  const token = ++sheetReqToken
  // 释放旧预览的 blob URL，避免反复切图泄漏内存
  previewUrls.value.forEach(u => { try { URL.revokeObjectURL(u) } catch { /* 忽略 */ } })
  previewUrls.value = []
  pageIdx.value = 0
  scale.value = 1
  pan.value = { x: 0, y: 0 }
  totalPages.value = 1
  snipBlobUrl.value = ''
  snipRect.value = null
  try {
    // 获取图纸信息（含总页数）
    try {
      const infoRes = await projectsApi.drawingInfo(activeProjectId.value, fid)
      if (token !== sheetReqToken) return
      totalPages.value = infoRes.data.image_count || 1
    } catch { totalPages.value = 1 }

    // 加载第一页
    const { data } = await drawingApi.image(fid)
    if (token !== sheetReqToken) return
    previewUrls.value.push(URL.createObjectURL(data))

    // 按总页数加载所有页面
    for (let n = 2; n <= totalPages.value; n++) {
      try {
        const r = await drawingApi.imageN(fid, n)
        if (token !== sheetReqToken) return
        previewUrls.value.push(URL.createObjectURL(r.data))
      } catch { break }
    }
  } catch {
    if (token === sheetReqToken) previewUrls.value = []
  }
}

function aiPayload(extra) {
  const base = setId.value ? { set_id: setId.value } : { file_id: activeSheetId.value }
  // 项目图纸模式：带 project_id/session_id（脱敏 + 5天会话上下文）
  if (activeProjectId.value) {
    base.project_id = activeProjectId.value
    base.session_id = projSessionId.value || 0
    base.drawing_ids = selectedDrawingIds.value
  }
  return { ...base, ...extra }
}

// ===== 项目图纸模式 =====
const showProjectPicker = ref(false)
const myProjects = ref([])
const activeProjectId = ref(0)
const projTree = ref([])
const projSets = ref([])
const projSessions = ref([])
const selectedDrawingIds = ref([])
const projPickMode = ref('browse')   // browse 选图纸 | sets 图纸集
const collapsedGroups = ref({})      // 折叠的分组 key → true
const showAll = ref(false)           // 常用（默认）| 全部
const projApplying = ref(false)
const projSessionId = ref(0)

const projectOptions = computed(() => myProjects.value.map(p => ({ text: p.name, value: p.id })))

// 目录树拍平为分组：根目录文件 + 各文件夹（含多级路径名）一组，保持压缩包结构
const drawingGroups = computed(() => {
  const groups = []
  const rootFiles = []
  const keep = (f) => showAll.value || f.is_frequent
  const walk = (nodes, path) => {
    for (const n of nodes || []) {
      if (n.type === 'dir') {
        walk(n.children, path ? `${path}/${n.name}` : n.name)
      } else if (!keep(n)) {
        continue
      } else if (!path) {
        rootFiles.push(n)
      } else {
        let g = groups.find(x => x.key === path)
        if (!g) { g = { key: path, name: path, files: [] }; groups.push(g) }
        g.files.push(n)
      }
    }
  }
  walk(projTree.value, '')
  const result = []
  if (rootFiles.length) result.push({ key: '__root__', name: '根目录', files: rootFiles })
  return result.concat(groups)
})

function toggleGroup(g) {
  collapsedGroups.value[g.key] = !collapsedGroups.value[g.key]
}

async function openProjectPicker() {
  showProjectPicker.value = true
  try {
    const { data } = await projectsApi.mine()
    myProjects.value = data
    if (data.length && !activeProjectId.value) activeProjectId.value = data[0].id
    if (activeProjectId.value) loadProjDrawings()
  } catch { /* 静默 */ }
}

function onProjectChange(pid) {
  activeProjectId.value = pid
  selectedDrawingIds.value = []
  projSessionId.value = 0
  loadProjDrawings()
}

async function loadProjDrawings() {
  if (!activeProjectId.value) return
  try {
    const [t, s, sess] = await Promise.all([
      projectsApi.drawingsTree(activeProjectId.value),
      projectsApi.sets(activeProjectId.value),
      projectsApi.sessions(activeProjectId.value),
    ])
    projTree.value = t.data
    projSets.value = s.data
    projSessions.value = sess.data
  } catch { /* 静默 */ }
}

async function applyProjectDrawings() {
  if (!selectedDrawingIds.value.length) return
  projApplying.value = true
  try {
    messages.value = []
    projSessionId.value = 0
    const { data } = await drawingApi.projectSet({
      project_id: activeProjectId.value,
      drawing_ids: selectedDrawingIds.value,
    })
    setId.value = data.set_id
    sheets.value = data.sheets
    activeSheetId.value = sheets.value[0]?.file_id
    await selectSheet(activeSheetId.value)
    showProjectPicker.value = false
    showSuccessToast(`图纸已就绪（${sheets.value.length} 张）`)
    await autoSummarize()
  } catch (e) {
    showToast(e.response?.data?.detail || e.message)
  } finally {
    projApplying.value = false
  }
}

// 恢复 5 天内的项目会话（图纸选择 + 对话上下文）
async function restoreSession(s) {
  try {
    const { data } = await projectsApi.getSession(activeProjectId.value, s.id)
    selectedDrawingIds.value = data.drawing_ids || []
    const { data: pset } = await drawingApi.projectSet({
      project_id: activeProjectId.value,
      drawing_ids: data.drawing_ids,
    })
    setId.value = pset.set_id
    sheets.value = pset.sheets
    activeSheetId.value = sheets.value[0]?.file_id
    await selectSheet(activeSheetId.value)
    projSessionId.value = data.id
    messages.value = data.messages || []
    showProjectPicker.value = false
    showSuccessToast(`已恢复会话（保留至 ${data.expires_at.slice(0, 10)}）`)
  } catch (e) {
    showToast(e.response?.data?.detail || '恢复会话失败')
  }
}

async function autoSummarize() {
  chatLoading.value = true
  try {
    const { data } = await drawingApi.chat(aiPayload({ question: '请综观这套图纸，简要概括图纸内容和各图幅关系' }))
    if (data.session_id) projSessionId.value = data.session_id
    messages.value.push({ role: 'assistant', content: data.answer, referenced: data.referenced })
  } catch { /* 静默 */ } finally {
    chatLoading.value = false
  }
}

async function sendQuestion() {
  if (!question.value.trim() || !activeSheetId.value) return
  const snip = snipBlobUrl.value
  messages.value.push({ role: 'user', content: question.value, snip })
  const q = question.value
  question.value = ''
  chatLoading.value = true
  try {
    const { data } = await drawingApi.chat(aiPayload({ question: q, snip_image: snip || '' }))
    if (data.session_id) projSessionId.value = data.session_id
    messages.value.push({ role: 'assistant', content: data.answer, referenced: data.referenced })
  } catch (e) {
    messages.value.push({ role: 'assistant', content: '回答失败: ' + (e.response?.data?.detail || e.message) })
  } finally {
    chatLoading.value = false
    snipBlobUrl.value = ''  // 截图随本次问题消费，不残留
  }
}

async function extractMaterials() {
  if (!activeSheetId.value) { showToast('请先上传图纸'); return }
  materialsLoading.value = true
  try {
    const { data } = await drawingApi.materials(aiPayload({}))
    materials.value = data.materials || []
  } catch (e) {
    showToast('提取失败: ' + (e.response?.data?.detail || e.message))
  } finally {
    materialsLoading.value = false
  }
}

async function generateBriefing() {
  if (!activeSheetId.value) { showToast('请先上传图纸'); return }
  briefingLoading.value = true
  briefingContent.value = ''
  try {
    const { data } = await drawingApi.briefing(aiPayload({ project_name: briefingProjectName.value, extra_info: '' }))
    briefingContent.value = data.briefing
  } catch (e) {
    showToast('生成失败: ' + (e.response?.data?.detail || e.message))
  } finally {
    briefingLoading.value = false
  }
}

// 语音输入（麦克风录音 → MiMo ASR 服务端识别）
const recognizing = ref(false)
const voiceUploading = ref(false)
let wavRecorder = null
async function toggleVoice() {
  if (recognizing.value) {
    recognizing.value = false
    let blob = null
    try { blob = await wavRecorder?.stop() } catch { /* 编码失败静默 */ }
    wavRecorder = null
    if (!blob) { showToast('没有录到声音'); return }
    voiceUploading.value = true
    try {
      const { data } = await drawingApi.asr(new File([blob], 'voice.wav', { type: 'audio/wav' }))
      if (data.text) {
        question.value = question.value ? question.value + data.text : data.text
        showSuccessToast('已识别')
      } else {
        showToast('未识别到语音，请靠近麦克风重试')
      }
    } catch (e) {
      showToast(e?.response?.data?.detail || '语音识别失败')
    } finally {
      voiceUploading.value = false
    }
    return
  }
  try {
    wavRecorder = new WavRecorder(60)
    wavRecorder.onMaxReached = () => { if (recognizing.value) toggleVoice() } // 60s 自动停止
    await wavRecorder.start()
    recognizing.value = true
    showToast('录音中…再点一次结束')
  } catch {
    wavRecorder = null
    showToast('无法使用麦克风，请检查权限')
  }
}

// 触摸手势（单指拖动 + 双指捏合缩放 + 单指滑动翻页 + 框选截图）
let touchState = null

// ==================== 截图提问（框选局部 → 裁剪 → 随问题发送） ====================
const snipMode = ref(false)
const snipRect = ref(null)
const snipBlobUrl = ref('')
let snipStart = null

const snipRectStyle = computed(() => snipRect.value
  ? { left: snipRect.value.x + 'px', top: snipRect.value.y + 'px',
      width: snipRect.value.w + 'px', height: snipRect.value.h + 'px' }
  : {})

function enterSnipMode() {
  if (!displaySrc.value) { showToast('请先上传图纸'); return }
  snipMode.value = true
  showToast('在图纸上拖动框选要提问的区域')
}

function _loadImg(url) {
  return new Promise((res, rej) => {
    const i = new Image()
    i.onload = () => res(i)
    i.onerror = rej
    i.src = url
  })
}

async function doSnipCrop() {
  const rect = snipRect.value
  snipRect.value = null
  try {
    // 从 PNG 源图裁剪：容器坐标换算图像像素坐标（同 PC 端算法）
    const img = await _loadImg(previewUrls.value[pageIdx.value])
    const box = previewRef.value.getBoundingClientRect()
    const cw = box.width, ch = box.height
    const fs = Math.min(cw / img.naturalWidth, ch / img.naturalHeight) * scale.value
    const dispW = img.naturalWidth * fs, dispH = img.naturalHeight * fs
    const tlX = cw / 2 + pan.value.x - dispW / 2
    const tlY = ch / 2 + pan.value.y - dispH / 2
    const x1 = Math.max(rect.x, tlX), y1 = Math.max(rect.y, tlY)
    const x2 = Math.min(rect.x + rect.w, tlX + dispW), y2 = Math.min(rect.y + rect.h, tlY + dispH)
    if (x2 - x1 < 8 || y2 - y1 < 8) { showToast('框选区域太小'); return }
    const sx = (x1 - tlX) / fs, sy = (y1 - tlY) / fs
    const sw = (x2 - x1) / fs, sh = (y2 - y1) / fs
    const canvas = document.createElement('canvas')
    canvas.width = Math.round(sw)
    canvas.height = Math.round(sh)
    canvas.getContext('2d').drawImage(img, sx, sy, sw, sh, 0, 0, sw, sh)
    snipBlobUrl.value = canvas.toDataURL('image/png')
    showSuccessToast('已框选，输入问题后发送即可')
  } catch { /* 裁剪失败静默 */ }
}

function onTouchStart(e) {
  if (!displaySrc.value) return
  const rect = previewRef.value.getBoundingClientRect()
  if (e.touches.length === 1) {
    const t = e.touches[0]
    if (snipMode.value) {
      snipStart = { x: t.clientX - rect.left, y: t.clientY - rect.top }
      snipRect.value = null
      touchState = { mode: 'snip' }
      return
    }
    touchState = {
      mode: 'drag',
      startX: t.clientX - pan.value.x,
      startY: t.clientY - pan.value.y,
      touchStartX: t.clientX,
      touchStartY: t.clientY,
      touchStartTime: Date.now(),
    }
  } else if (e.touches.length === 2) {
    if (snipMode.value) return  // 框选中忽略双指，避免缩放打乱选框
    const [a, b] = e.touches
    const cx = (a.clientX + b.clientX) / 2 - rect.left - rect.width / 2
    const cy = (a.clientY + b.clientY) / 2 - rect.top - rect.height / 2
    touchState = {
      mode: 'pinch', cx, cy,
      dist: Math.hypot(a.clientX - b.clientX, a.clientY - b.clientY),
      startScale: scale.value, startPan: { ...pan.value },
    }
  }
}
function onTouchMove(e) {
  if (!touchState) return
  const rect = previewRef.value.getBoundingClientRect()
  if (touchState.mode === 'snip' && snipStart && e.touches.length === 1) {
    const t = e.touches[0]
    const cx = t.clientX - rect.left, cy = t.clientY - rect.top
    snipRect.value = {
      x: Math.min(snipStart.x, cx), y: Math.min(snipStart.y, cy),
      w: Math.abs(cx - snipStart.x), h: Math.abs(cy - snipStart.y),
    }
  } else if (touchState.mode === 'drag' && e.touches.length === 1) {
    const t = e.touches[0]
    pan.value = { x: t.clientX - touchState.startX, y: t.clientY - touchState.startY }
  } else if (touchState.mode === 'pinch' && e.touches.length === 2) {
    const [a, b] = e.touches
    const dist = Math.hypot(a.clientX - b.clientX, a.clientY - b.clientY)
    const factor = dist / touchState.dist
    const next = Math.min(8, Math.max(0.2, touchState.startScale * factor))
    const k = next / touchState.startScale
    pan.value = {
      x: touchState.cx - (touchState.cx - touchState.startPan.x) * k,
      y: touchState.cy - (touchState.cy - touchState.startPan.y) * k,
    }
    scale.value = next
  }
}

// 翻页函数
function nextPage() {
  if (pageIdx.value < previewUrls.value.length - 1) {
    pageIdx.value++
    scale.value = 1
    pan.value = { x: 0, y: 0 }
  }
}
function prevPage() {
  if (pageIdx.value > 0) {
    pageIdx.value--
    scale.value = 1
    pan.value = { x: 0, y: 0 }
  }
}

function onTouchEnd(e) {
  if (touchState?.mode === 'snip') {
    if (snipRect.value && snipRect.value.w > 10 && snipRect.value.h > 10) doSnipCrop()
    else snipRect.value = null
    snipMode.value = false
    snipStart = null
  } else if (touchState?.mode === 'drag' && e.changedTouches.length === 1) {
    const t = e.changedTouches[0]
    const dx = t.clientX - touchState.touchStartX
    const dy = t.clientY - touchState.touchStartY
    const dt = Date.now() - touchState.touchStartTime
    // 仅在未缩放时，水平滑动距离足够才翻页
    if (scale.value === 1 && Math.abs(dx) > 60 && Math.abs(dx) > Math.abs(dy) * 2) {
      if (dx < 0) nextPage()  // 左滑 → 下一页
      else prevPage()         // 右滑 → 上一页
    }
  }
  touchState = null
}

onMounted(() => {
  // 移动端无需额外初始化
})
</script>

<style scoped>
.drawing-page { display: flex; flex-direction: column; height: 100vh; }
.top-bar {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 8px 12px;
  background: #fff;
  border-bottom: 1px solid #ebedf0;
  flex-shrink: 0;
  min-height: 44px;
  gap: 8px;
}
.logo-btn {
  background: none;
  border: none;
  padding: 4px;
  cursor: pointer;
  flex-shrink: 0;
}
.logo-img {
  width: 28px;
  height: 28px;
  border-radius: 6px;
}
.top-title { font-size: 15px; font-weight: 600; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; flex: 1; }
.account-info {
  padding: 12px 0;
}
.account-info p {
  margin: 8px 0;
  font-size: 14px;
  color: #333;
}
.preview-area {
  flex: 1;
  min-height: 0;
  position: relative;
  background: #fff;
  overflow: hidden;
  touch-action: none;
}
.preview-img {
  position: absolute;
  top: 50%;
  left: 50%;
  width: 100%;
  height: 100%;
  object-fit: contain;
  user-select: none;
  will-change: transform;
}
.preview-empty {
  height: 100%;
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  color: #969799;
}
.zoom-hint {
  position: absolute;
  top: 8px;
  right: 10px;
  font-size: 11px;
  color: #969799;
  background: rgba(255,255,255,0.85);
  padding: 2px 8px;
  border-radius: 12px;
}
.snip-rect {
  position: absolute;
  border: 1.5px dashed #1989fa;
  background: rgba(25,137,250,0.12);
  pointer-events: none;
  z-index: 9;
}
.snip-chip {
  display: flex;
  align-items: center;
  gap: 8px;
  margin: 6px 8px 0;
  padding: 6px 10px;
  background: #f2f3f5;
  border-radius: 8px;
  font-size: 12px;
  color: #646566;
}
.snip-chip img { width: 44px; height: 44px; object-fit: cover; border-radius: 4px; }
.snip-chip span { flex: 1; }
.msg-snip {
  max-width: 60%;
  border-radius: 8px;
  margin-bottom: 4px;
}
.page-indicator {
  position: absolute;
  bottom: 12px;
  left: 50%;
  transform: translateX(-50%);
  display: flex;
  align-items: center;
  gap: 12px;
  background: rgba(0,0,0,0.55);
  border-radius: 20px;
  padding: 4px 12px;
  z-index: 10;
}
.page-btn {
  width: 32px;
  height: 32px;
  border: none;
  border-radius: 50%;
  background: rgba(255,255,255,0.2);
  color: #fff;
  font-size: 18px;
  display: flex;
  align-items: center;
  justify-content: center;
  cursor: pointer;
}
.page-btn:disabled {
  opacity: 0.3;
  cursor: default;
}
.page-btn:active:not(:disabled) {
  background: rgba(255,255,255,0.4);
}
.page-text {
  color: #fff;
  font-size: 13px;
  min-width: 40px;
  text-align: center;
}
.bottom-panel { flex-shrink: 0; background: #fff; border-top: 1px solid #ebedf0; max-height: 45vh; display: flex; flex-direction: column; }
.bottom-panel.upload-open { max-height: 62vh; }
.bottom-panel.upload-open .chat-panel { height: 57vh; }
.chat-panel { display: flex; flex-direction: column; height: 40vh; }
.chat-messages { flex: 1; overflow-y: auto; padding: 12px; }
.chat-empty { text-align: center; color: #969799; padding: 24px 0; font-size: 13px; }
.msg { margin-bottom: 10px; display: flex; flex-direction: column; }
.msg.user { align-items: flex-end; }
.msg.assistant { align-items: flex-start; }
.msg-bubble {
  max-width: 80%;
  padding: 8px 12px;
  border-radius: 12px;
  font-size: 14px;
  line-height: 1.6;
  white-space: pre-wrap;
  word-break: break-word;
}
.msg.user .msg-bubble { background: #1989fa; color: #fff; }
.msg.assistant .msg-bubble { background: #f2f3f5; color: #323233; }
.msg-ref { font-size: 11px; color: #969799; margin-top: 4px; max-width: 80%; }
.chat-input { display: flex; align-items: center; gap: 8px; padding: 8px; border-top: 1px solid #ebedf0; }
.chat-input :deep(.van-field) { background: #f2f3f5; border-radius: 18px; padding: 4px 12px; }
.sub-panel { padding: 12px; overflow-y: auto; }
.materials-list { margin-top: 12px; }
.material-item { padding: 10px; border-bottom: 1px solid #f2f3f5; }
.m-name { font-size: 14px; font-weight: 600; }
.m-spec { font-size: 12px; color: #969799; margin-top: 2px; }
.briefing-content {
  margin-top: 12px;
  font-size: 13px;
  line-height: 1.8;
  white-space: pre-wrap;
  background: #f7f8fa;
  padding: 12px;
  border-radius: 8px;
  max-height: 30vh;
  overflow-y: auto;
}
.uploader-panel { padding: 20px 16px 24px; }
.uploader-panel h4 { margin: 0 0 12px; font-size: 16px; }
.uploader-tip { font-size: 12px; color: #969799; margin-top: 8px; }
.upload-inline {
  border-top: 1px solid #ebedf0;
  background: #fafafa;
  padding: 8px 12px 10px;
  flex-shrink: 0;
  max-height: 24vh;
  overflow-y: auto;
}
.upload-inline-head {
  display: flex;
  justify-content: space-between;
  align-items: center;
  margin-bottom: 6px;
}
.upload-inline-title { font-size: 14px; font-weight: 600; color: #323233; }
.upload-inline .file-list { max-height: 9vh; }
.file-list { margin-top: 12px; max-height: 30vh; overflow-y: auto; }
.pick-toggle {
  display: flex;
  background: #f2f3f5;
  border-radius: 18px;
  padding: 3px;
  margin: 8px 0;
}
.pick-toggle-btn {
  flex: 1;
  border: none;
  background: transparent;
  padding: 7px 0;
  border-radius: 15px;
  font-size: 14px;
  color: #646566;
  cursor: pointer;
}
.pick-toggle-btn.active {
  background: #fff;
  color: #1989fa;
  font-weight: 600;
  box-shadow: 0 1px 4px rgba(0,0,0,0.08);
}
.dg-head {
  display: flex;
  align-items: center;
  gap: 6px;
  padding: 8px 4px 4px;
  border-bottom: 1px solid #f2f3f5;
  user-select: none;
}
.file-item {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 8px 0;
  border-bottom: 1px solid #f2f3f5;
  font-size: 13px;
}
</style>
