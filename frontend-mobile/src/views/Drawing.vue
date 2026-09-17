<template>
  <div class="drawing-page">
    <!-- 顶部：图幅切换 + 上传 -->
    <div class="top-bar">
      <van-dropdown-menu v-if="sheets.length > 1">
        <van-dropdown-item :model-value="activeSheetId" :options="sheetOptions" @change="onSheetChange" />
      </van-dropdown-menu>
      <span v-else class="top-title">{{ sheets[0]?.filename || '识图助手' }}</span>
      <van-button size="small" type="primary" plain @click="showUploader = true">上传图纸</van-button>
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
  </div>
</template>

<script setup>
import { ref, computed, onMounted } from 'vue'
import { showToast, showSuccessToast } from 'vant'
import { drawing as drawingApi } from '../api'
import { useAuthStore } from '../stores/auth'

const authStore = useAuthStore()

// 上传
const showUploader = ref(false)
const fileList = ref([])
const uploading = ref(false)

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
  return setId.value ? { set_id: setId.value, ...extra } : { file_id: activeSheetId.value, ...extra }
}

async function autoSummarize() {
  chatLoading.value = true
  try {
    const { data } = await drawingApi.chat(aiPayload({ question: '请综观这套图纸，简要概括图纸内容和各图幅关系' }))
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
