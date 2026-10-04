<template>
  <div class="drawing-page">
    <!-- 面包屑顶栏：菜单 / 当前图纸名（点开预览）/ 图幅·切换 -->
    <div class="top-bar">
      <button class="logo-btn" @click="showLogoMenu = true">
        <img src="/logo.png" alt="菜单" class="logo-img" />
      </button>
      <button class="crumb" @click="onCrumbClick">
        <template v-if="currentDrawingName">
          <span class="crumb-text">{{ currentDrawingName }}</span>
        </template>
        <span v-else class="crumb-empty">请选择图纸 ↓</span>
      </button>
      <button v-if="sheets.length > 1" class="icon-btn" @click="showSheetMenu = true">
        <van-icon name="apps-o" size="18" />
      </button>
      <button class="icon-btn" @click="openPicker('project')" title="切换图纸">
        <van-icon name="exchange" size="18" />
      </button>
    </div>

    <!-- 主区：图纸问答（常态下占据顶栏以下全部视口） -->
    <div class="chat-area">
      <div class="chat-messages" ref="chatRef">
        <div v-if="!messages.length" class="chat-empty">
          <p>{{ currentDrawingName ? '可以开始提问了' : '请先选择图纸' }}</p>
          <van-button
            v-if="!currentDrawingName" size="small" type="primary" plain
            @click="openPicker('project')"
          >选择图纸</van-button>
        </div>
        <div v-for="(msg, i) in messages" :key="i" :class="['msg', msg.role]">
          <img v-if="msg.snip" :src="msg.snip" class="msg-snip" />
          <!-- 回答渲染 Markdown（14px 阶梯约束见样式）；用户消息保持纯文本 -->
          <div
            v-if="msg.role === 'assistant'" class="msg-bubble md"
            v-html="renderMd(msg.content)"
          />
          <div v-else class="msg-bubble">{{ msg.content }}</div>
          <div v-if="msg.referenced?.length" class="msg-ref">
            参考图幅：{{ msg.referenced.map(r => r.filename).join('、') }}
          </div>
        </div>
        <div v-if="chatLoading" class="msg assistant">
          <div class="msg-bubble">分析中…</div>
        </div>
      </div>

      <div v-if="snipBlobUrl" class="snip-chip">
        <img :src="snipBlobUrl" alt="框选截图" />
        <span>已框选局部截图，提问将针对该区域</span>
        <van-icon name="close" @click="snipBlobUrl = ''" />
      </div>

      <div class="chat-input">
        <van-button
          size="small" type="primary" :plain="!snipMode"
          @click="startSnipPreview"
        >{{ snipMode ? '框选中' : '截图' }}</van-button>
        <van-field
          ref="questionFieldRef"
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

    <!-- 预览态：遮罩覆盖问答区（两态互斥，关闭后问答状态原样保留） -->
    <van-popup
      :show="showPreview" position="top" close-on-click-overlay
      :style="{ height: 'calc(100% - 44px)', marginTop: '44px' }"
      @update:show="onPreviewShow"
    >
      <div class="preview-wrap">
        <div class="preview-head">
          <button class="ph-close" @click="closePreview">✕ 关闭</button>
          <span class="ph-title">{{ currentDrawingName }}</span>
          <span v-if="displaySrc" class="ph-zoom">{{ Math.round(scale * 100) }}%</span>
          <span v-if="displaySrc && previewUrls.length > 1" class="ph-pages">
            <button class="page-btn" :disabled="pageIdx === 0" @click="prevPage">‹</button>
            <span class="page-text">{{ pageIdx + 1 }} / {{ previewUrls.length }}</span>
            <button class="page-btn" :disabled="pageIdx >= previewUrls.length - 1" @click="nextPage">›</button>
          </span>
        </div>

        <div
          class="preview-area" ref="previewRef"
          @touchstart.prevent="onTouchStart" @touchmove.prevent="onTouchMove" @touchend="onTouchEnd"
        >
          <img v-if="displaySrc" :src="displaySrc" class="preview-img" :style="imgStyle" />
          <div v-else class="preview-empty" @click="openPicker('upload')">
            <van-icon name="plus" size="48" color="#c8c9cc" />
            <p>暂无图纸，点此上传</p>
          </div>
          <div v-if="snipRect" class="snip-rect" :style="snipRectStyle" />
        </div>

        <!-- 轻量底栏：截图确认动作（框选→回问答提问） -->
        <div class="preview-foot">
          <template v-if="snipBlobUrl">
            <img :src="snipBlobUrl" class="foot-snip" />
            <van-button size="small" type="primary" @click="closePreview">去提问</van-button>
            <van-button size="small" plain @click="snipBlobUrl = ''; enterSnipMode()">重选区域</van-button>
          </template>
          <template v-else>
            <van-button size="small" type="primary" :plain="!snipMode" @click="snipMode ? (snipMode = false) : enterSnipMode()">
              {{ snipMode ? '拖动框选中…' : '框选截图提问' }}
            </van-button>
            <span class="foot-tip">双指缩放 · 拖动查看 · 翻页</span>
          </template>
        </div>
      </div>
    </van-popup>

    <!-- ≡ 菜单：图纸切换 / 历史 / 预览 / 材料 / 交底 / 账号 -->
    <van-action-sheet
      v-model:show="showLogoMenu"
      :actions="logoMenuActions"
      cancel-text="取消"
      close-on-click-action
      @select="onLogoMenuSelect"
    />

    <!-- 多图幅切换 -->
    <van-action-sheet
      v-model:show="showSheetMenu"
      :actions="sheetActions"
      cancel-text="取消"
      close-on-click-action
      @select="onSheetMenuSelect"
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

    <!-- 选图弹窗：项目图纸 / 本地上传 两源并列（预处理秒开 + 图纸集 + 5天会话） -->
    <van-popup v-model:show="showProjectPicker" position="bottom" round :style="{ maxHeight: '80%' }">
      <div class="uploader-panel">
        <div class="pick-toggle">
          <button :class="['pick-toggle-btn', { active: pickerSource === 'project' }]" @click="pickerSource = 'project'">项目图纸</button>
          <button :class="['pick-toggle-btn', { active: pickerSource === 'upload' }]" @click="pickerSource = 'upload'">本地上传</button>
        </div>

        <!-- 本地上传 -->
        <template v-if="pickerSource === 'upload'">
          <div class="upload-block">
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
        </template>

        <!-- 项目图纸 -->
        <template v-else>
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
        </template>
      </div>
    </van-popup>

    <!-- 材料表面板（菜单唤出，非常驻 tab） -->
    <van-popup
      :show="panelView === 'materials'" position="bottom" round :style="{ maxHeight: '75%' }"
      @update:show="v => !v && (panelView = '')"
    >
      <div class="uploader-panel">
        <h4>材料表</h4>
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
    </van-popup>

    <!-- 交底面板（菜单唤出，非常驻 tab） -->
    <van-popup
      :show="panelView === 'briefing'" position="bottom" round :style="{ maxHeight: '75%' }"
      @update:show="v => !v && (panelView = '')"
    >
      <div class="uploader-panel">
        <h4>快速交底</h4>
        <van-field v-model="briefingProjectName" label="项目名称" placeholder="可选" />
        <van-button size="small" type="primary" plain @click="generateBriefing" :loading="briefingLoading" style="margin-top: 8px">
          {{ briefingContent ? '重新生成' : '生成交底文件' }}
        </van-button>
        <div v-if="briefingContent" class="briefing-content">{{ briefingContent }}</div>
      </div>
    </van-popup>
  </div>
</template>

<script setup>
import { ref, computed, onMounted, watch, nextTick } from 'vue'
import { showToast, showSuccessToast } from 'vant'
import { marked } from 'marked'
import DOMPurify from 'dompurify'
import { drawing as drawingApi, projects as projectsApi, chatErrMsg } from '../api'
import { WavRecorder } from '../utils/wavRecorder'
import { auth as authApi } from '../api/auth'
import { useAuthStore } from '../stores/auth'

const authStore = useAuthStore()

marked.setOptions({ breaks: true })
function renderMd(text) {
  try { return DOMPurify.sanitize(marked.parse(text || '')) } catch { return '' }
}

// ===== 两态互斥：常态=问答区为绝对主体；预览=遮罩覆盖问答区 =====
const showPreview = ref(false)

function onPreviewShow(v) { if (!v) closePreview() }
function closePreview() {
  showPreview.value = false
  snipMode.value = false
  snipRect.value = null
  snipStart = null
}
function onCrumbClick() {
  if (displaySrc.value) showPreview.value = true
  else openPicker('project')
}

// ===== 选图弹窗：项目图纸 / 本地上传 =====
const showProjectPicker = ref(false)
const pickerSource = ref('project')   // project 项目图纸 | upload 本地上传
const fileList = ref([])
const uploading = ref(false)

function openPicker(source = 'project') {
  pickerSource.value = source
  showProjectPicker.value = true
  if (source === 'project') loadMyProjects()
}

const logoMenuActions = [
  { name: '切换图纸', key: 'switch-drawing' },
  { name: '历史会话', key: 'history' },
  { name: '图纸预览', key: 'preview' },
  { name: '材料表', key: 'materials' },
  { name: '交底', key: 'briefing' },
  { name: '切换为电脑端', key: 'switch-pc' },
  { name: '账号信息', key: 'account-info' },
  { name: '修改密码', key: 'change-pwd' },
  { name: '退出登录', key: 'logout', color: '#ee0a24' },
]
const showLogoMenu = ref(false)
const showAccountInfo = ref(false)
const showPwdPopup = ref(false)
const pwdSubmitting = ref(false)
const pwdForm = ref({ old_password: '', new_password: '', confirm_password: '' })
const panelView = ref('')   // '' | materials | briefing

function onLogoMenuSelect(action) {
  if (action.key === 'switch-drawing') {
    openPicker('project')
  } else if (action.key === 'history') {
    projPickMode.value = 'browse'
    openPicker('project')
  } else if (action.key === 'preview') {
    if (displaySrc.value) showPreview.value = true
    else { showToast('请先选择图纸'); openPicker('project') }
  } else if (action.key === 'materials' || action.key === 'briefing') {
    if (!activeSheetId.value) { showToast('请先选择图纸'); openPicker('project'); return }
    panelView.value = action.key
  } else if (action.key === 'switch-pc') {
    // 标记本次会话留在 PC 版，否则 PC index.html 的 UA 跳转会把手机用户弹回 /m/
    sessionStorage.setItem('use_pc', '1')
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
const showSheetMenu = ref(false)

// 面包屑：项目名 / 图纸名（点它唤预览）
const currentDrawingName = computed(() => {
  if (activeSheetId.value) {
    const s = sheets.value.find(x => x.file_id === activeSheetId.value)
    const base = s?.filename || '图纸'
    const proj = myProjects.value.find(p => p.id === activeProjectId.value)
    return proj ? `${proj.name} / ${base}` : base
  }
  if (sheets.value.length) return `图纸集 · ${sheets.value.length} 张`
  return ''
})

const sheetActions = computed(() =>
  sheets.value.map(s => ({ name: s.filename, key: s.file_id })))

function onSheetMenuSelect(action) {
  showSheetMenu.value = false
  onSheetChange(action.key)
}

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
const messages = ref([])
const question = ref('')
const chatLoading = ref(false)
const summarizing = ref(false)  // 图纸概述后台生成中（错峰，不占用 chatLoading）
const chatRef = ref(null)
const questionFieldRef = ref(null)

watch(() => messages.value.length, async () => {
  await nextTick()
  const el = chatRef.value
  if (el) el.scrollTop = el.scrollHeight
})

function focusInput() {
  nextTick(() => questionFieldRef.value?.focus?.())
}

// 材料/交底
const materials = ref([])
const materialsLoading = ref(false)
const briefingProjectName = ref('')
const briefingContent = ref('')
const briefingLoading = ref(false)

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
      showProjectPicker.value = false
      showSuccessToast(`图纸集已就绪（${sheets.value.length} 张）`)
      focusInput()
      autoSummarize()  // 概述后台错峰执行，可立即提问（一期优化#6）
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
    // 总页数走 /drawing/{file_id}/pages（按缓存 file_id 查）；
    // drawingInfo 路由要 int 图纸 id，传 pd_ 缓存 id 会 422，这里不能用
    try {
      const pg = await drawingApi.pages(fid)
      if (token !== sheetReqToken) return
      totalPages.value = pg.data.count || 1
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

async function loadMyProjects() {
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
    focusInput()   // 选完即问
    autoSummarize()  // 概述后台错峰执行（一期优化#6）
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
    focusInput()
  } catch (e) {
    showToast(e.response?.data?.detail || '恢复会话失败')
  }
}

// 图纸概述：后台错峰执行（一期优化#6）——不占用 chatLoading，概述生成期间可立即提问
async function autoSummarize() {
  if (summarizing.value) return  // 防重复触发
  summarizing.value = true
  const placeholder = { role: 'assistant', content: '⏳ 图纸概述生成中…', pending: true }
  messages.value.push(placeholder)
  try {
    const { data } = await drawingApi.chat(aiPayload({ question: '请综观这套图纸，简要概括图纸内容和各图幅关系' }))
    if (data.session_id) projSessionId.value = data.session_id
    const ans = { role: 'assistant', content: data.answer, referenced: data.referenced }
    const i = messages.value.indexOf(placeholder)  // 占位回填；会话被切换则追加不覆盖
    if (i >= 0) messages.value[i] = ans
    else messages.value.push(ans)
  } catch {
    // 静默：移除占位气泡（原实现失败不提示）
    const i = messages.value.indexOf(placeholder)
    if (i >= 0) messages.value.splice(i, 1)
  } finally {
    summarizing.value = false
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
    messages.value.push({ role: 'assistant', content: '回答失败: ' + chatErrMsg(e) })
  } finally {
    chatLoading.value = false
    snipBlobUrl.value = ''  // 截图随本次问题消费，不残留
  }
}

async function extractMaterials() {
  if (!activeSheetId.value) { showToast('请先选择图纸'); return }
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
  if (!activeSheetId.value) { showToast('请先选择图纸'); return }
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

// 输入栏「截图」→ 唤出预览并直接进入框选（预览是截图的载体）
function startSnipPreview() {
  if (!displaySrc.value) { showToast('请先选择图纸'); openPicker('project'); return }
  showPreview.value = true
  enterSnipMode()
}

function enterSnipMode() {
  if (!displaySrc.value) { showToast('请先选择图纸'); openPicker('project'); return }
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
    showSuccessToast('已框选，点「去提问」返回问答')
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
  // 先选图再问答：进入页面无当前图纸 → 自动唤出选图
  if (!activeSheetId.value) openPicker('project')
})
</script>

<style scoped>
.drawing-page { display: flex; flex-direction: column; height: 100vh; height: 100dvh; overflow: hidden; }

/* ===== 面包屑顶栏 ===== */
.top-bar {
  display: flex;
  align-items: center;
  gap: 6px;
  padding: 6px 10px;
  background: #fff;
  border-bottom: 1px solid #ebedf0;
  flex-shrink: 0;
  min-height: 44px;
  z-index: 2;
}
.logo-btn { background: none; border: none; padding: 2px; cursor: pointer; flex-shrink: 0; }
.logo-img { width: 28px; height: 28px; border-radius: 6px; }
.crumb {
  flex: 1;
  min-width: 0;
  display: flex;
  align-items: center;
  gap: 4px;
  background: #f2f3f5;
  border: none;
  border-radius: 14px;
  padding: 6px 12px;
  font-size: 14px;
  cursor: pointer;
}
.crumb-text { font-weight: 600; color: #323233; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.crumb-empty { color: #969799; }
.icon-btn {
  flex-shrink: 0;
  width: 34px; height: 34px;
  display: flex; align-items: center; justify-content: center;
  background: #f2f3f5;
  border: none;
  border-radius: 50%;
  color: #646566;
  cursor: pointer;
}
.account-info { padding: 12px 0; }
.account-info p { margin: 8px 0; font-size: 14px; color: #333; }

/* ===== 主区：问答（常态占满顶栏以下全部空间） ===== */
.chat-area {
  flex: 1;
  min-height: 0;
  display: flex;
  flex-direction: column;
  background: #fff;
}
.chat-messages {
  flex: 1;
  min-height: 0;
  overflow-y: auto;
  -webkit-overflow-scrolling: touch;
  padding: 12px;
  font-size: 14px;
  line-height: 1.55;
}
.chat-empty {
  height: 100%;
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  gap: 12px;
  color: #969799;
  font-size: 14px;
}
.chat-empty p { margin: 0; }
.msg { margin-bottom: 10px; display: flex; flex-direction: column; }
.msg.user { align-items: flex-end; }
.msg.assistant { align-items: flex-start; }
.msg-bubble {
  max-width: 92%;
  padding: 8px 12px;
  border-radius: 12px;
  font-size: 14px;
  line-height: 1.55;
  white-space: pre-wrap;
  word-break: break-word;
}
.msg.user .msg-bubble { background: #1989fa; color: #fff; }
.msg.assistant .msg-bubble { background: #f2f3f5; color: #323233; }

/* 回答 Markdown：显式字号阶梯，杜绝继承默认 16px 膨胀 */
.msg-bubble.md { white-space: normal; }
.msg-bubble.md :deep(h1), .msg-bubble.md :deep(h2), .msg-bubble.md :deep(h3),
.msg-bubble.md :deep(h4), .msg-bubble.md :deep(h5), .msg-bubble.md :deep(h6) {
  font-size: 15px;
  line-height: 1.4;
  font-weight: 600;
  margin: 10px 0 6px;
}
.msg-bubble.md :deep(h1) { font-size: 16px; }
.msg-bubble.md :deep(h1:first-child), .msg-bubble.md :deep(h2:first-child),
.msg-bubble.md :deep(h3:first-child), .msg-bubble.md :deep(p:first-child) { margin-top: 0; }
.msg-bubble.md :deep(p) { font-size: 14px; line-height: 1.55; margin: 0 0 8px; }
.msg-bubble.md :deep(p:last-child) { margin-bottom: 0; }
.msg-bubble.md :deep(ul), .msg-bubble.md :deep(ol) {
  font-size: 14px; line-height: 1.55; margin: 0 0 8px; padding-left: 20px;
}
.msg-bubble.md :deep(li) { margin: 3px 0; }
.msg-bubble.md :deep(strong) { font-weight: 600; }
.msg-bubble.md :deep(a) { color: #1989fa; }
.msg-bubble.md :deep(code) {
  font-size: 13px;
  background: rgba(0, 0, 0, 0.06);
  padding: 1px 4px;
  border-radius: 4px;
  word-break: break-all;
}
.msg-bubble.md :deep(pre) {
  overflow-x: auto;
  background: #fff;
  padding: 8px;
  border-radius: 8px;
  margin: 0 0 8px;
  max-width: 100%;
}
.msg-bubble.md :deep(pre code) { background: none; padding: 0; font-size: 12px; }
.msg-bubble.md :deep(table) {
  border-collapse: collapse;
  font-size: 13px;
  display: block;
  overflow-x: auto;
  max-width: 100%;
  margin: 0 0 8px;
}
.msg-bubble.md :deep(th), .msg-bubble.md :deep(td) {
  border: 1px solid #ebedf0;
  padding: 4px 8px;
  text-align: left;
}
.msg-bubble.md :deep(img) { max-width: 100%; }
/* 引用段落：默认 40px 大缩进在手机上太占宽，收紧为左侧色条 */
.msg-bubble.md :deep(blockquote) {
  margin: 0 0 8px;
  padding: 4px 8px;
  border-left: 3px solid rgba(25, 137, 250, 0.4);
  background: rgba(25, 137, 250, 0.06);
  border-radius: 0 6px 6px 0;
  color: #646566;
}
.msg-ref { font-size: 12px; color: #969799; margin-top: 4px; max-width: 92%; }

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
.msg-snip { max-width: 60%; border-radius: 8px; margin-bottom: 4px; }

.chat-input {
  display: flex;
  align-items: center;
  gap: 8px;
  padding: 8px;
  border-top: 1px solid #ebedf0;
  background: #fff;
  flex-shrink: 0;
}
.chat-input :deep(.van-field) {
  background: #f2f3f5;
  border-radius: 18px;
  padding: 4px 12px;
  flex: 1;
  min-width: 0;             /* 输入框可收缩，避免挤掉右侧发送按钮 */
}
.chat-input :deep(.van-field__body) { font-size: 14px; }
.chat-input :deep(.van-button) {
  flex-shrink: 0;
  white-space: nowrap;      /* 「截图」「发送」不许竖排换行 */
}

/* ===== 预览态（遮罩覆盖问答区） ===== */
.preview-wrap {
  display: flex;
  flex-direction: column;
  height: 100%;
  background: #f7f8fa;
}
.preview-head {
  display: flex;
  align-items: center;
  gap: 8px;
  padding: 8px 12px;
  background: #fff;
  border-bottom: 1px solid #ebedf0;
  flex-shrink: 0;
  min-height: 44px;
}
.ph-close {
  border: none; background: #f2f3f5; border-radius: 14px;
  padding: 6px 12px; font-size: 14px; color: #323233; cursor: pointer;
}
.ph-title {
  flex: 1; min-width: 0;
  font-size: 14px; font-weight: 600; color: #323233;
  overflow: hidden; text-overflow: ellipsis; white-space: nowrap;
}
.ph-zoom { font-size: 12px; color: #969799; }
.ph-pages { display: flex; align-items: center; gap: 8px; }

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
  top: 50%; left: 50%;
  width: 100%; height: 100%;
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
  font-size: 14px;
}
.snip-rect {
  position: absolute;
  border: 1.5px dashed #1989fa;
  background: rgba(25, 137, 250, 0.12);
  pointer-events: none;
  z-index: 9;
}
.preview-foot {
  display: flex;
  align-items: center;
  gap: 10px;
  padding: 10px 12px;
  background: #fff;
  border-top: 1px solid #ebedf0;
  flex-shrink: 0;
}
.foot-snip { width: 40px; height: 40px; object-fit: cover; border-radius: 6px; }
.foot-tip { font-size: 12px; color: #969799; }

.page-btn {
  width: 30px; height: 30px;
  border: none; border-radius: 50%;
  background: #f2f3f5;
  color: #323233;
  font-size: 18px;
  display: flex; align-items: center; justify-content: center;
  cursor: pointer;
}
.page-btn:disabled { opacity: 0.3; cursor: default; }
.page-text { font-size: 13px; color: #646566; min-width: 44px; text-align: center; }

/* ===== 选图弹窗 ===== */
.uploader-panel { padding: 16px 16px 24px; }
.uploader-panel h4 { margin: 0 0 12px; font-size: 16px; }
.uploader-tip { font-size: 12px; color: #969799; margin-top: 8px; }
.upload-block { padding-top: 8px; }
.file-list { margin-top: 12px; max-height: 30vh; overflow-y: auto; }
.pick-toggle {
  display: flex;
  background: #f2f3f5;
  border-radius: 18px;
  padding: 3px;
  margin: 4px 0 10px;
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
  box-shadow: 0 1px 4px rgba(0, 0, 0, 0.08);
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

/* ===== 材料表 / 交底 ===== */
.materials-list { margin-top: 12px; max-height: 50vh; overflow-y: auto; }
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
  max-height: 45vh;
  overflow-y: auto;
}
</style>
