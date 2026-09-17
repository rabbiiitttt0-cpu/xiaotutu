<template>
  <div class="drawing-page">
    <!-- 顶部：图幅切换 + 上传 -->
    <div class="top-bar">
      <van-dropdown-menu v-if="sheets.length > 1">
        <van-dropdown-item :model-value="activeSheetId" :options="sheetOptions" @change="onSheetChange" />
      </van-dropdown-menu>
      <span v-else class="top-title">{{ sheets[0]?.filename || '识图助手' }}</span>
      <van-button size="small" type="primary" plain @click="openProjectPicker">项目图纸</van-button>
      <van-button size="small" type="primary" plain @click="showUploader = true">上传图纸</van-button>
      <van-button size="small" type="primary" plain icon="user-o" @click="showMyMenu = true" />
    </div>

    <!-- 图纸预览（触摸缩放拖动） -->
    <div class="preview-area" ref="previewRef" @touchstart.prevent="onTouchStart" @touchmove.prevent="onTouchMove" @touchend="onTouchEnd">
      <img v-if="displaySrc" :src="displaySrc" class="preview-img" :style="imgStyle" />
      <div v-else class="preview-empty" @click="showUploader = true">
        <van-icon name="plus" size="48" color="#c8c9cc" />
        <p>上传图纸开始识别</p>
      </div>
      <div v-if="displaySrc" class="zoom-hint">{{ Math.round(scale * 100) }}%</div>
    </div>

    <!-- 底部：功能 tab -->
    <div class="bottom-panel">
      <van-tabs v-model:active="activeTab" shrink>
        <van-tab title="问答" name="chat">
          <div class="chat-panel">
            <div class="chat-messages" ref="chatRef">
              <div v-if="!messages.length" class="chat-empty">上传图纸后，这里可以提问</div>
              <div v-for="(msg, i) in messages" :key="i" :class="['msg', msg.role]">
                <div class="msg-bubble">{{ msg.content }}</div>
                <div v-if="msg.referenced?.length" class="msg-ref">
                  参考图幅：{{ msg.referenced.map(r => r.filename).join('、') }}
                </div>
              </div>
              <div v-if="chatLoading" class="msg assistant"><div class="msg-bubble">分析中…</div></div>
            </div>
            <div class="chat-input">
              <van-field
                v-model="question"
                placeholder="输入问题，或点🎤语音"
                :border="false"
                @keyup.enter="sendQuestion"
              />
              <van-button size="small" type="primary" icon="service-o" @click="toggleVoice" />
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

    <!-- 上传弹窗 -->
    <van-popup v-model:show="showUploader" position="bottom" round>
      <div class="uploader-panel">
        <h4>上传图纸</h4>
        <van-uploader :after-read="onFileRead" multiple accept=".dxf,.dwg,.pdf" />
        <p class="uploader-tip">支持 .dxf / .dwg / .pdf，可多选组成图纸集</p>
        <div v-if="fileList.length" class="file-list">
          <div v-for="(f, i) in fileList" :key="i" class="file-item">
            <span>{{ f.name }}</span>
            <van-icon name="close" @click="fileList.splice(i, 1)" />
          </div>
        </div>
        <van-button type="primary" block round :loading="uploading" @click="doUpload" style="margin-top: 12px">
          {{ uploading ? '解析中…' : '解析图纸' }}
        </van-button>
      </div>
    </van-popup>

    <!-- 「我的」菜单：修改密码 / 退出登录 -->
    <van-action-sheet
      v-model:show="showMyMenu"
      :actions="myMenuActions"
      cancel-text="取消"
      close-on-click-action
      @select="onMyMenuSelect"
    />

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

          <!-- 图纸集 -->
          <template v-if="projSets.length">
            <p class="uploader-tip" style="margin-bottom: 4px">图纸集</p>
            <div
              v-for="s in projSets" :key="s.id" class="file-item"
              @click="selectedDrawingIds = [...s.drawing_ids]; applyProjectDrawings()"
            >
              <span>📁 {{ s.name }}</span>
              <span style="color: #c8c9cc; font-size: 12px">{{ s.drawing_ids.length }}张</span>
            </div>
          </template>

          <!-- 图纸多选（常用置顶，可切全部） -->
          <div style="display: flex; justify-content: space-between; align-items: center">
            <p class="uploader-tip" style="margin: 4px 0">图纸（{{ showAll ? '全部' : '近期常用' }}）</p>
            <van-switch :model-value="showAll" size="20px" @update:model-value="showAll = $event; loadProjDrawings()" />
          </div>
          <van-checkbox-group v-model="selectedDrawingIds" style="max-height: 180px; overflow-y: auto">
            <van-checkbox
              v-for="d in projDrawings" :key="d.id" :name="d.id"
              style="padding: 6px 4px"
            >
              {{ d.filename }}
              <van-tag v-if="d.is_frequent" type="warning" size="medium">常用</van-tag>
            </van-checkbox>
            <van-empty
              v-if="!projDrawings.length" image-size="40"
              :description="showAll ? '项目暂无已处理图纸' : '暂无常用图纸，打开开关看全部'"
            />
          </van-checkbox-group>

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
import { auth as authApi } from '../api/auth'
import { useAuthStore } from '../stores/auth'

const authStore = useAuthStore()

// 上传
const showUploader = ref(false)
const fileList = ref([])
const uploading = ref(false)

// 「我的」菜单 + 修改密码
const showMyMenu = ref(false)
const showPwdPopup = ref(false)
const pwdSubmitting = ref(false)
const pwdForm = ref({ old_password: '', new_password: '', confirm_password: '' })
const myMenuActions = [
  { name: '修改密码', key: 'change-pwd' },
  { name: '退出登录', key: 'logout', color: '#ee0a24' },
]

function onMyMenuSelect(action) {
  if (action.key === 'change-pwd') {
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

async function selectSheet(fid) {
  previewUrls.value = []
  pageIdx.value = 0
  scale.value = 1
  pan.value = { x: 0, y: 0 }
  try {
    const { data } = await drawingApi.image(fid)
    previewUrls.value.push(URL.createObjectURL(data))
    for (let n = 2; n <= 3; n++) {
      try {
        const r = await drawingApi.imageN(fid, n)
        previewUrls.value.push(URL.createObjectURL(r.data))
      } catch { break }
    }
  } catch { previewUrls.value = [] }
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
const projDrawings = ref([])
const projSets = ref([])
const projSessions = ref([])
const selectedDrawingIds = ref([])
const showAll = ref(false)
const projApplying = ref(false)
const projSessionId = ref(0)

const projectOptions = computed(() => myProjects.value.map(p => ({ text: p.name, value: p.id })))

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
    const scope = showAll.value ? 'all' : 'frequent'
    const [d, s, sess] = await Promise.all([
      projectsApi.drawings(activeProjectId.value, scope),
      projectsApi.sets(activeProjectId.value),
      projectsApi.sessions(activeProjectId.value),
    ])
    projDrawings.value = d.data
    projSets.value = s.data
    projSessions.value = sess.data
    // 常用为空时自动切全部
    if (!showAll.value && !d.data.length) {
      const { data: all } = await projectsApi.drawings(activeProjectId.value, 'all')
      if (all.length) { showAll.value = true; projDrawings.value = all }
    }
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
  messages.value.push({ role: 'user', content: question.value })
  const q = question.value
  question.value = ''
  chatLoading.value = true
  try {
    const { data } = await drawingApi.chat(aiPayload({ question: q }))
    if (data.session_id) projSessionId.value = data.session_id
    messages.value.push({ role: 'assistant', content: data.answer, referenced: data.referenced })
  } catch (e) {
    messages.value.push({ role: 'assistant', content: '回答失败: ' + (e.response?.data?.detail || e.message) })
  } finally {
    chatLoading.value = false
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

// 语音输入（浏览器 SpeechRecognition）
let recognizer = null
let voiceBaseText = ''
function toggleVoice() {
  const SR = window.SpeechRecognition || window.webkitSpeechRecognition
  if (!SR) { showToast('浏览器不支持语音，请用 Chrome'); return }
  if (recognizer) { recognizer.stop(); recognizer = null; return }
  recognizer = new SR()
  recognizer.lang = 'zh-CN'
  recognizer.continuous = true
  recognizer.interimResults = true
  let finals = ''
  recognizer.onresult = (e) => {
    let interim = ''
    for (let i = e.resultIndex; i < e.results.length; i++) {
      if (e.results[i].isFinal) finals += e.results[i][0].transcript
      else interim += e.results[i][0].transcript
    }
    question.value = voiceBaseText + finals + interim
  }
  recognizer.onend = () => { recognizer = null }
  voiceBaseText = question.value
  recognizer.start()
}

// 触摸手势（单指拖动 + 双指捏合缩放）
let touchState = null
function onTouchStart(e) {
  if (!displaySrc.value) return
  const rect = previewRef.value.getBoundingClientRect()
  if (e.touches.length === 1) {
    const t = e.touches[0]
    touchState = { mode: 'drag', startX: t.clientX - pan.value.x, startY: t.clientY - pan.value.y }
  } else if (e.touches.length === 2) {
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
  if (touchState.mode === 'drag' && e.touches.length === 1) {
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
function onTouchEnd() {
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
}
.top-title { font-size: 15px; font-weight: 600; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
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
.bottom-panel { flex-shrink: 0; background: #fff; border-top: 1px solid #ebedf0; max-height: 45vh; display: flex; flex-direction: column; }
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
.file-list { margin-top: 12px; max-height: 30vh; overflow-y: auto; }
.file-item {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 8px 0;
  border-bottom: 1px solid #f2f3f5;
  font-size: 13px;
}
</style>
