<template>
  <div>
    <div class="page-header"><h2>项目管理</h2></div>

    <el-card shadow="never">
      <div style="margin-bottom: 12px; display: flex; justify-content: space-between">
        <span style="color: #909399; font-size: 13px">
          项目图纸预处理：上传压缩包后后台自动转换/解析/脱敏，成员问答时秒开
        </span>
        <el-button type="primary" @click="openCreate">新建项目</el-button>
      </div>

      <el-table :data="projectList" stripe border v-loading="loading">
        <el-table-column prop="name" label="项目名" min-width="160" />
        <el-table-column prop="description" label="备注" min-width="160" show-overflow-tooltip />
        <el-table-column label="图纸" width="120">
          <template #default="{ row }">
            <el-tag size="small" :type="row.drawing_ready === row.drawing_total ? 'success' : 'warning'">
              {{ row.drawing_ready }}/{{ row.drawing_total }}
            </el-tag>
          </template>
        </el-table-column>
        <el-table-column prop="member_count" label="成员" width="70" />
        <el-table-column prop="created_at" label="创建时间" width="160" />
        <el-table-column label="操作" width="260" fixed="right">
          <template #default="{ row }">
            <el-button size="small" type="primary" plain @click="openDetail(row)">管理</el-button>
            <el-button size="small" plain @click="openEdit(row)">编辑</el-button>
            <el-popconfirm title="删除项目将清除全部图纸与会话，确定？" width="240" @confirm="removeProject(row)">
              <template #reference>
                <el-button size="small" type="danger" plain>删除</el-button>
              </template>
            </el-popconfirm>
          </template>
        </el-table-column>
      </el-table>
    </el-card>

    <!-- 新建/编辑项目 -->
    <el-dialog v-model="formVisible" :title="form.id ? '编辑项目' : '新建项目'" width="440px">
      <el-form label-width="70px">
        <el-form-item label="项目名" required>
          <el-input v-model="form.name" maxlength="100" placeholder="如：XX码头一期工程" />
        </el-form-item>
        <el-form-item label="备注">
          <el-input v-model="form.description" type="textarea" :rows="2" maxlength="500" />
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="formVisible = false">取消</el-button>
        <el-button type="primary" :loading="saving" @click="saveProject">保存</el-button>
      </template>
    </el-dialog>

    <!-- 项目详情抽屉：图纸 + 成员 -->
    <el-drawer v-model="detailVisible" :title="current?.name" size="720px" destroy-on-close>
      <el-tabs v-model="detailTab">
        <!-- ===== 图纸 ===== -->
        <el-tab-pane label="图纸管理" name="drawings">
          <div style="display: flex; gap: 10px; margin-bottom: 12px; align-items: center">
            <el-upload
              :show-file-list="false" accept=".zip" :auto-upload="false"
              :on-change="onZipPicked" :disabled="zipUploading"
            >
              <el-button type="primary" :loading="zipUploading">
                {{ zipUploading ? '上传中...' : '上传图纸压缩包(.zip)' }}
              </el-button>
            </el-upload>
            <span style="font-size: 12px; color: #909399; flex: 1">
              支持 .dwg/.dxf/.pdf 混合打包；上传后后台串行预处理，可离开本页稍后查看
            </span>
            <el-button size="small" plain :disabled="!drawings.length" @click="openRelations">
              图纸关系图
            </el-button>
          </div>

          <!-- 有目录层级时用树形展示，否则用平铺表格 -->
          <template v-if="hasDirs">
            <el-tree
              :data="treeData"
              node-key="key"
              :props="{ label: 'name', children: 'children' }"
              default-expand-all
              :expand-on-click-node="false"
              stripe
              style="margin-top: 8px"
            >
              <template #default="{ data }">
                <div style="display: flex; align-items: center; gap: 8px; flex: 1; min-width: 0">
                  <el-icon v-if="data.type === 'dir'" :size="14" style="color: #e6a23c"><Folder /></el-icon>
                  <el-icon v-else :size="14" style="color: #409eff"><Document /></el-icon>
                  <span v-if="data.type === 'dir'" style="font-weight: 600; font-size: 13px">{{ data.name }}</span>
                  <template v-else>
                    <span style="font-size: 13px; flex: 1; overflow: hidden; text-overflow: ellipsis; white-space: nowrap">{{ data.filename }}</span>
                    <el-tag size="small" :type="data.file_type === 'pdf' ? 'warning' : 'success'" style="flex-shrink: 0">
                      {{ data.file_type.toUpperCase() }}
                    </el-tag>
                    <el-tag size="small" :type="statusType(data.status)" style="flex-shrink: 0">{{ statusText(data.status) }}</el-tag>
                    <el-switch
                      :model-value="data.is_frequent" :disabled="data.status !== 'ready'"
                      size="small" style="flex-shrink: 0"
                      @change="(v) => toggleFrequent(data, v)"
                    />
                    <el-popconfirm title="删除该图纸及预处理产物？" width="200" @confirm="removeDrawing(data)">
                      <template #reference>
                        <el-button size="small" type="danger" text style="flex-shrink: 0">删除</el-button>
                      </template>
                    </el-popconfirm>
                  </template>
                </div>
              </template>
            </el-tree>
          </template>

          <template v-else>
            <el-table :data="drawings" stripe border size="small" v-loading="drawingsLoading">
              <el-table-column prop="filename" label="文件名" min-width="180" show-overflow-tooltip />
              <el-table-column label="类型" width="60">
                <template #default="{ row }">
                  <el-tag size="small" :type="row.file_type === 'pdf' ? 'warning' : 'success'">
                    {{ row.file_type.toUpperCase() }}
                  </el-tag>
                </template>
              </el-table-column>
              <el-table-column label="状态" width="90">
                <template #default="{ row }">
                  <el-tag size="small" :type="statusType(row.status)">{{ statusText(row.status) }}</el-tag>
                </template>
              </el-table-column>
              <el-table-column label="近期常用" width="80">
                <template #default="{ row }">
                  <el-switch
                    :model-value="row.is_frequent" :disabled="row.status !== 'ready'"
                    @change="(v) => toggleFrequent(row, v)"
                  />
                </template>
              </el-table-column>
              <el-table-column label="失败原因" min-width="140">
                <template #default="{ row }">
                  <span v-if="row.error" style="color: #f56c6c; font-size: 12px">{{ row.error }}</span>
                </template>
              </el-table-column>
              <el-table-column label="操作" width="70">
                <template #default="{ row }">
                  <el-popconfirm title="删除该图纸及预处理产物？" width="200" @confirm="removeDrawing(row)">
                    <template #reference>
                      <el-button size="small" type="danger" text>删除</el-button>
                    </template>
                  </el-popconfirm>
                </template>
              </el-table-column>
            </el-table>
          </template>
          <el-empty v-if="!drawings.length && !drawingsLoading && !hasDirs" description="尚未上传图纸" :image-size="60" />

          <!-- 图纸集管理（预设常用组合，仅管理员可维护；识图助手端项目共享可见） -->
          <el-divider content-position="left">图纸集</el-divider>
          <div style="display: flex; justify-content: flex-end; margin-bottom: 8px">
            <el-button size="small" type="primary" plain :disabled="!drawings.length" @click="openSetDialog()">
              新建图纸集
            </el-button>
          </div>
          <el-empty v-if="!projSets.length" description="暂无图纸集，可预设常用图纸组合（如：桩基一套）" :image-size="50" />
          <div v-for="s in projSets" :key="s.id" class="set-row">
            <span class="set-name" :title="s.name">{{ s.name }}</span>
            <el-tag size="small" type="warning" effect="plain">{{ s.drawing_ids.length }} 张</el-tag>
            <el-button size="small" text type="primary" @click="openSetDialog(s)">编辑</el-button>
            <el-popconfirm title="删除该图纸集？（不影响图纸本身）" width="220" @confirm="removeSet(s)">
              <template #reference>
                <el-button size="small" text type="danger">删除</el-button>
              </template>
            </el-popconfirm>
          </div>
        </el-tab-pane>

        <!-- ===== 成员 ===== -->
        <el-tab-pane label="项目成员" name="members">
          <div style="display: flex; gap: 10px; margin-bottom: 12px">
            <el-select v-model="memberToAdd" filterable placeholder="选择用户加入项目" style="flex: 1">
              <el-option
                v-for="u in addableUsers" :key="u.id" :value="u.id"
                :label="`${u.display_name || u.username}（${u.username}）`"
              />
            </el-select>
            <el-button type="primary" :disabled="!memberToAdd" @click="addMember">添加</el-button>
          </div>
          <el-table :data="members" stripe border size="small">
            <el-table-column prop="username" label="用户名" width="140" />
            <el-table-column prop="display_name" label="姓名" min-width="120" />
            <el-table-column prop="joined_at" label="加入时间" width="160" />
            <el-table-column label="操作" width="80">
              <template #default="{ row }">
                <el-popconfirm title="移出该项目？" width="180" @confirm="removeMember(row)">
                  <template #reference>
                    <el-button size="small" type="danger" text>移除</el-button>
                  </template>
                </el-popconfirm>
              </template>
            </el-table-column>
          </el-table>
        </el-tab-pane>
      </el-tabs>
    </el-drawer>

    <!-- 图纸集编辑对话框（勾选组成图纸集，仅 ready 图纸可选） -->
    <el-dialog
      v-model="setDialogVisible" :title="setForm.id ? '编辑图纸集' : '新建图纸集'"
      width="520px" destroy-on-close
    >
      <el-form label-width="80px">
        <el-form-item label="名称" required>
          <el-input v-model="setForm.name" placeholder="如：桩基一套" maxlength="100" show-word-limit />
        </el-form-item>
        <el-form-item label="选择图纸">
          <el-tree
            ref="setTreeRef" :data="setTreeData" node-key="key" show-checkbox default-expand-all
            :default-checked-keys="setForm.id ? editingSetCheckedKeys : []"
            :props="{ label: 'name', children: 'children', disabled: 'disabled' }"
            style="width: 100%; max-height: 320px; overflow-y: auto"
          >
            <template #default="{ data }">
              <span style="font-size: 13px; display: flex; align-items: center; gap: 6px">
                <el-icon v-if="data.type === 'dir'" :size="14" style="color: #e6a23c"><Folder /></el-icon>
                <span>{{ data.filename || data.name }}</span>
                <el-tag v-if="data.type === 'file' && data.status !== 'ready'" size="small" type="info">
                  {{ statusText(data.status) }}
                </el-tag>
              </span>
            </template>
          </el-tree>
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="setDialogVisible = false">取消</el-button>
        <el-button type="primary" :loading="setSaving" @click="saveSet">保存</el-button>
      </template>
    </el-dialog>

    <!-- 图纸关系图（预处理自动生成的批次画像；手绘 SVG，不引图库） -->
    <el-dialog v-model="relVisible" title="图纸关系图" width="780px" destroy-on-close>
      <div v-loading="relLoading">
        <el-alert
          v-if="relData.available && relData.stale" type="warning" :closable="false"
          title="图纸已有增删，关系图可能过期，可点击右下角重新生成"
          style="margin-bottom: 10px"
        />
        <template v-if="relData.available">
          <svg
            v-if="relLayout.nodes.length"
            :viewBox="`0 0 ${relLayout.w} ${relLayout.h}`"
            style="width: 100%; background: #fafafa; border: 1px solid #ebeef5; border-radius: 4px"
          >
            <defs>
              <marker id="rel-arrow" viewBox="0 0 10 10" refX="9" refY="5"
                      markerWidth="7" markerHeight="7" orient="auto-start-reverse">
                <path d="M 0 0 L 10 5 L 0 10 z" fill="#c0c4cc" />
              </marker>
            </defs>
            <text
              v-for="(k, i) in relLayout.kinds" :key="'k' + i"
              :x="20 + i * (REL_NW + REL_GX) + REL_NW / 2" y="22"
              font-size="12" fill="#909399" text-anchor="middle" font-weight="600"
            >{{ k }}</text>
            <g v-for="(e, i) in relLayout.edges" :key="'e' + i">
              <line :x1="e.x1" :y1="e.y1" :x2="e.x2" :y2="e.y2"
                    stroke="#c0c4cc" stroke-width="1.2" marker-end="url(#rel-arrow)" />
              <text :x="e.mx" :y="e.my" font-size="11" fill="#909399" text-anchor="middle">{{ e.relation }}</text>
            </g>
            <g v-for="n in relLayout.nodes" :key="n.file_id">
              <rect :x="n.x" :y="n.y" :width="REL_NW" :height="REL_NH" rx="4"
                    fill="#fff" stroke="#409eff" stroke-width="1" />
              <text :x="n.x + REL_NW / 2" :y="n.y + 20" font-size="12" fill="#303133" text-anchor="middle">
                {{ n.label }}
              </text>
              <text :x="n.x + REL_NW / 2" :y="n.y + 36" font-size="10" fill="#909399" text-anchor="middle">
                {{ n.kind }}
              </text>
            </g>
          </svg>
          <el-divider content-position="left">关系描述</el-divider>
          <p style="white-space: pre-wrap; font-size: 13px; color: #606266; margin: 0 4px">
            {{ relData.description || '（无描述）' }}
          </p>
          <div style="color: #909399; font-size: 12px; margin-top: 8px">
            生成时间：{{ relData.generated_at }}
          </div>
        </template>
        <el-empty
          v-else-if="!relLoading" :image-size="60"
          description="关系图尚未生成（图纸预处理完成后自动生成，也可手动生成）"
        />
      </div>
      <template #footer>
        <el-button @click="relVisible = false">关闭</el-button>
        <el-button type="primary" :loading="relRefreshing" @click="refreshRelations">重新生成</el-button>
      </template>
    </el-dialog>
  </div>
</template>

<script setup>
import { ref, computed, onMounted, onBeforeUnmount } from 'vue'
import { ElMessage } from 'element-plus'
import { projects as projectsApi } from '../../api'
import { adminUsers } from '../../api/auth'

const loading = ref(false)
const projectList = ref([])

async function loadProjects() {
  loading.value = true
  try {
    const { data } = await projectsApi.list()
    projectList.value = data
  } finally {
    loading.value = false
  }
}

// ===== 新建/编辑 =====
const formVisible = ref(false)
const saving = ref(false)
const form = ref({ id: 0, name: '', description: '' })

function openCreate() {
  form.value = { id: 0, name: '', description: '' }
  formVisible.value = true
}
function openEdit(row) {
  form.value = { id: row.id, name: row.name, description: row.description }
  formVisible.value = true
}
async function saveProject() {
  if (!form.value.name.trim()) { ElMessage.warning('请填写项目名'); return }
  saving.value = true
  try {
    if (form.value.id) await projectsApi.update(form.value.id, form.value)
    else await projectsApi.create(form.value)
    ElMessage.success('已保存')
    formVisible.value = false
    loadProjects()
  } catch (e) {
    ElMessage.error(e.response?.data?.detail || e.message)
  } finally {
    saving.value = false
  }
}
async function removeProject(row) {
  try {
    await projectsApi.remove(row.id)
    ElMessage.success('已删除')
    loadProjects()
  } catch (e) {
    ElMessage.error(e.response?.data?.detail || e.message)
  }
}

// ===== 详情抽屉 =====
const detailVisible = ref(false)
const detailTab = ref('drawings')
const current = ref(null)

function openDetail(row) {
  current.value = row
  detailTab.value = 'drawings'
  detailVisible.value = true
  loadDrawings()
  loadMembers()
  loadAllUsers()
  loadSets()
}

// ----- 图纸 -----
const drawings = ref([])
const drawingsLoading = ref(false)
const zipUploading = ref(false)
const treeData = ref([])
let pollTimer = null

const hasDirs = computed(() => treeData.value.length > 0 && treeData.value.some(n => n.type === 'dir'))

function statusType(s) {
  return { ready: 'success', processing: 'warning', pending: 'info', failed: 'danger' }[s] || 'info'
}
function statusText(s) {
  return { ready: '就绪', processing: '处理中', pending: '排队中', failed: '失败' }[s] || s
}

function buildTree(drawings) {
  const root = { __dirs__: {}, __files__: [] }
  for (const d of drawings) {
    const parts = (d.rel_path || d.filename).split('/').filter(Boolean)
    let node = root
    for (const part of parts.slice(0, -1)) {
      node = node.__dirs__[part] ||= { __dirs__: {}, __files__: [] }
    }
    node.__files__.push(d)
  }
  function build(node, prefix) {
    const result = []
    for (const [name, sub] of Object.entries(node.__dirs__).sort()) {
      const key = prefix ? `${prefix}/${name}` : name
      result.push({ key, type: 'dir', name, children: build(sub, key) })
    }
    for (const f of node.__files__) {
      result.push({ key: `f-${f.id}`, type: 'file', ...f })
    }
    return result
  }
  return build(root, '')
}

async function loadDrawings() {
  if (!current.value) return
  drawingsLoading.value = true
  try {
    const { data } = await projectsApi.drawings(current.value.id, 'admin')
    drawings.value = data
    treeData.value = buildTree(data)
    // 有排队/处理中的图纸时轮询进度（3s）
    const busy = data.some(d => d.status === 'pending' || d.status === 'processing')
    clearTimeout(pollTimer)
    if (busy) pollTimer = setTimeout(loadDrawings, 3000)
  } finally {
    drawingsLoading.value = false
  }
}

async function onZipPicked(file) {
  zipUploading.value = true
  try {
    const { data } = await projectsApi.uploadZip(current.value.id, file.raw)
    const skipNote = data.skipped?.length ? `，跳过不支持文件 ${data.skipped.length} 个` : ''
    ElMessage.success(`已接收 ${data.created.length} 个图纸文件，后台预处理中${skipNote}`)
    loadDrawings()
  } catch (e) {
    ElMessage.error(e.response?.data?.detail || e.message)
  } finally {
    zipUploading.value = false
  }
}

async function toggleFrequent(row, v) {
  try {
    await projectsApi.patchDrawing(current.value.id, row.id, { is_frequent: v })
    row.is_frequent = v
  } catch (e) {
    ElMessage.error(e.response?.data?.detail || e.message)
  }
}

async function removeDrawing(row) {
  try {
    await projectsApi.removeDrawing(current.value.id, row.id)
    ElMessage.success('已删除')
    loadDrawings()
    loadProjects()
    loadSets()  // 后端会同步清理图纸集引用，刷新集内张数
  } catch (e) {
    ElMessage.error(e.response?.data?.detail || e.message)
  }
}

// ----- 图纸集（预设常用组合，仅管理员维护） -----
const projSets = ref([])
const setDialogVisible = ref(false)
const setSaving = ref(false)
const setForm = ref({ id: 0, name: '' })
const editingSetCheckedKeys = ref([])   // 编辑时回填的勾选 key（对话框 destroy-on-close 每次重挂载生效）
const setTreeRef = ref()

// 图纸树映射：目录禁用勾选（避免级联误选未就绪图纸），未 ready 文件禁用
const setTreeData = computed(() => {
  const mark = (nodes) => nodes.map(n => n.type === 'dir'
    ? { ...n, disabled: true, children: mark(n.children || []) }
    : { ...n, disabled: n.status !== 'ready' })
  return mark(treeData.value)
})

async function loadSets() {
  if (!current.value) return
  try {
    const { data } = await projectsApi.sets(current.value.id)
    projSets.value = data
  } catch { /* 静默 */ }
}

function openSetDialog(s) {
  setForm.value = { id: s?.id || 0, name: s?.name || '' }
  editingSetCheckedKeys.value = (s?.drawing_ids || []).map(id => `f-${id}`)
  setDialogVisible.value = true
}

async function saveSet() {
  const name = setForm.value.name.trim()
  if (!name) { ElMessage.warning('请输入图纸集名称'); return }
  const ids = setTreeRef.value.getCheckedKeys()
    .filter(k => String(k).startsWith('f-'))
    .map(k => Number(String(k).slice(2)))
  if (!ids.length) { ElMessage.warning('请至少勾选一张图纸'); return }
  setSaving.value = true
  try {
    if (setForm.value.id) {
      await projectsApi.updateSet(current.value.id, setForm.value.id, { name, drawing_ids: ids })
    } else {
      await projectsApi.createSet(current.value.id, { name, drawing_ids: ids })
    }
    ElMessage.success('图纸集已保存')
    setDialogVisible.value = false
    loadSets()
  } catch (e) {
    ElMessage.error(e.response?.data?.detail || e.message)
  } finally {
    setSaving.value = false
  }
}

async function removeSet(s) {
  try {
    await projectsApi.removeSet(current.value.id, s.id)
    ElMessage.success('已删除')
    loadSets()
  } catch (e) {
    ElMessage.error(e.response?.data?.detail || e.message)
  }
}

// ----- 关系图（批次画像：预处理自动生成，可手动刷新） -----
const relVisible = ref(false)
const relLoading = ref(false)
const relRefreshing = ref(false)
const relData = ref({ available: false, nodes: [], edges: [], description: '' })

const REL_NW = 190  // 节点宽
const REL_NH = 46   // 节点高
const REL_GX = 60   // 列间距
const REL_GY = 64   // 行间距

// 布局：按 kind 分列，列内纵排；边 = 节点中心连线
const relLayout = computed(() => {
  const nodes = relData.value.nodes || []
  const edges = relData.value.edges || []
  const kinds = [...new Set(nodes.map(n => n.kind || '其他'))]
  const pos = {}
  kinds.forEach((k, ci) => {
    nodes.filter(n => (n.kind || '其他') === k).forEach((n, ri) => {
      const name = n.filename || n.file_id
      pos[n.file_id] = {
        ...n,
        label: name.length > 15 ? name.slice(0, 14) + '…' : name,
        x: 20 + ci * (REL_NW + REL_GX),
        y: 40 + ri * (REL_NH + REL_GY),
      }
    })
  })
  const ns = Object.values(pos)
  const es = edges.map(e => {
    const a = pos[e.from]
    const b = pos[e.to]
    if (!a || !b) return null
    return {
      x1: a.x + REL_NW / 2, y1: a.y + REL_NH / 2,
      x2: b.x + REL_NW / 2, y2: b.y + REL_NH / 2,
      mx: (a.x + b.x) / 2 + REL_NW / 2, my: (a.y + b.y) / 2 + REL_NH / 2 - 6,
      relation: e.relation,
    }
  }).filter(Boolean)
  const maxRows = Math.max(1, ...kinds.map(
    k => nodes.filter(n => (n.kind || '其他') === k).length))
  return {
    kinds,
    nodes: ns,
    edges: es,
    w: Math.max(360, 40 + kinds.length * (REL_NW + REL_GX)),
    h: Math.max(160, 40 + maxRows * (REL_NH + REL_GY)),
  }
})

async function openRelations() {
  relVisible.value = true
  relLoading.value = true
  try {
    const { data } = await projectsApi.relations(current.value.id)
    relData.value = data.available
      ? data
      : { available: false, nodes: [], edges: [], description: '' }
  } catch (e) {
    ElMessage.error(e.response?.data?.detail || e.message)
  } finally {
    relLoading.value = false
  }
}

async function refreshRelations() {
  relRefreshing.value = true
  try {
    const { data } = await projectsApi.refreshRelations(current.value.id)
    if (data.available) relData.value = data
    ElMessage.success('关系图已重新生成')
  } catch (e) {
    ElMessage.error(e.response?.data?.detail || e.message)
  } finally {
    relRefreshing.value = false
  }
}

// ----- 成员 -----
const members = ref([])
const allUsers = ref([])
const memberToAdd = ref(null)

async function loadMembers() {
  const { data } = await projectsApi.members(current.value.id)
  members.value = data
}
async function loadAllUsers() {
  try {
    const { data } = await adminUsers.list()
    allUsers.value = data
  } catch { /* 静默 */ }
}
const addableUsers = computed(() => {
  const ids = new Set(members.value.map(m => m.user_id))
  return allUsers.value.filter(u => !ids.has(u.id) && u.is_active !== false)
})
async function addMember() {
  try {
    await projectsApi.addMember(current.value.id, memberToAdd.value)
    memberToAdd.value = null
    ElMessage.success('已添加')
    loadMembers()
    loadProjects()
  } catch (e) {
    ElMessage.error(e.response?.data?.detail || e.message)
  }
}
async function removeMember(row) {
  try {
    await projectsApi.removeMember(current.value.id, row.user_id)
    ElMessage.success('已移除')
    loadMembers()
    loadProjects()
  } catch (e) {
    ElMessage.error(e.response?.data?.detail || e.message)
  }
}

onMounted(loadProjects)
onBeforeUnmount(() => clearTimeout(pollTimer))
</script>

<style scoped>
.set-row {
  display: flex;
  align-items: center;
  gap: 8px;
  padding: 8px 10px;
  border-bottom: 1px solid #f2f3f5;
}
.set-row .set-name {
  flex: 1;
  min-width: 0;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
  font-size: 13px;
  font-weight: 600;
}
</style>
