<template>
  <div>
    <div class="page-header">
      <h2>系统设置</h2>
      <el-button type="primary" :loading="saving" @click="saveAll">保存全部</el-button>
    </div>

    <!-- ===== 模型接入 ===== -->
    <el-card shadow="never" class="section-card">
      <template #header>
        <div class="card-header">
          <div class="card-heading">
            <span class="card-title">模型接入</span>
            <span class="card-desc">配置可调用的 AI 模型，每个模型可单独测试连通性</span>
          </div>
          <el-button size="small" @click="addProvider">添加模型</el-button>
        </div>
      </template>

      <el-table :data="providers" stripe border size="small" v-loading="loading">
        <el-table-column label="启用" width="60" align="center">
          <template #default="{ row }">
            <el-switch v-model="row.enabled" size="small" />
          </template>
        </el-table-column>
        <el-table-column label="名称" min-width="110">
          <template #default="{ row }">
            <el-input v-model="row.name" size="small" placeholder="如：DeepSeek" />
          </template>
        </el-table-column>
        <el-table-column label="类型" width="120">
          <template #default="{ row }">
            <el-select v-model="row.provider" size="small">
              <el-option v-for="p in PROVIDER_TYPES" :key="p.value" :label="p.label" :value="p.value" />
            </el-select>
          </template>
        </el-table-column>
        <el-table-column label="API Key" min-width="180">
          <template #default="{ row }">
            <el-input v-model="row.api_key" size="small" placeholder="sk-..." />
          </template>
        </el-table-column>
        <el-table-column label="Base URL" min-width="170">
          <template #default="{ row }">
            <el-input v-model="row.base_url" size="small" placeholder="https://api.example.com/v1" />
          </template>
        </el-table-column>
        <el-table-column label="模型名" min-width="130">
          <template #default="{ row }">
            <el-input v-model="row.model" size="small" placeholder="如：deepseek-chat" />
          </template>
        </el-table-column>
        <el-table-column label="视觉" width="55" align="center">
          <template #default="{ row }">
            <el-switch v-model="row.supports_vision" size="small" />
          </template>
        </el-table-column>
        <el-table-column label="温度" width="80">
          <template #default="{ row }">
            <el-input-number v-model="row.temperature" size="small" :min="0" :max="2" :step="0.1" :controls="false" style="width:70px" />
          </template>
        </el-table-column>
        <el-table-column label="Max Tokens" width="100">
          <template #default="{ row }">
            <el-input-number v-model="row.max_tokens" size="small" :min="256" :max="65536" :step="256" :controls="false" style="width:90px" />
          </template>
        </el-table-column>
        <el-table-column label="操作" width="130" align="center">
          <template #default="{ row, $index }">
            <el-button size="small" :type="row._testResult === 'ok' ? 'success' : row._testResult === 'fail' ? 'danger' : 'primary'"
              plain :loading="row._testing" @click="testRow(row)">
              {{ row._testing ? '测试中' : row._testResult === 'ok' ? '✓ 通过' : row._testResult === 'fail' ? '重试' : '测试' }}
            </el-button>
            <el-button size="small" type="danger" plain @click="removeProvider($index)">删</el-button>
          </template>
        </el-table-column>
      </el-table>
      <div class="table-tip" v-if="providers.length === 0 && !loading">
        还没有模型，点击右上角「添加模型」接入。
      </div>
    </el-card>

    <!-- ===== 模型分配 ===== -->
    <el-card shadow="never" class="section-card">
      <template #header>
        <div class="card-heading">
          <span class="card-title">模型分配</span>
          <span class="card-desc">按功能指定使用的模型，「跟随识图模型」会随下方识图问答的选择自动变化</span>
        </div>
      </template>

      <div class="bind-grid">
        <!-- 识图问答（主） -->
        <div class="bind-item">
          <div class="bind-top">
            <div>
              <div class="bind-name">识图问答 <el-tag size="small" type="primary" effect="plain">主</el-tag></div>
              <div class="bind-desc">识图助手主对话与视觉理解</div>
            </div>
          </div>
          <el-select v-model="drawingProviderIdx" size="small" class="bind-select">
            <el-option v-for="(p, i) in providers" :key="i"
              :label="providerLabel(p)" :value="i" :disabled="!p.enabled" />
          </el-select>
          <div class="bind-current" v-if="drawingProviderIdx >= 0 && providers[drawingProviderIdx]">
            当前：{{ providers[drawingProviderIdx].name || '未命名' }} · {{ providers[drawingProviderIdx].model || '未填模型名' }}
          </div>
        </div>

        <!-- 定位 Agent -->
        <div class="bind-item">
          <div class="bind-top">
            <div>
              <div class="bind-name">定位 / 路由 Agent</div>
              <div class="bind-desc">图纸集路由与问题定位，纯文本调用，可选轻量模型</div>
            </div>
            <el-switch v-model="agentSettings.snip_locate_enabled" size="small" />
          </div>
          <el-select v-model="locateIdx" size="small" class="bind-select">
            <el-option label="跟随识图模型" :value="-1" />
            <el-option v-for="(p, i) in providers" :key="i"
              :label="providerLabel(p)" :value="i" :disabled="!p.enabled" />
          </el-select>
          <div class="bind-current" v-if="locateIdx === -1">当前：跟随识图模型</div>
          <div class="bind-current" v-else-if="locateIdx >= 0 && providers[locateIdx]">
            当前：{{ providers[locateIdx].name || '未命名' }} · {{ providers[locateIdx].model || '未填模型名' }}
          </div>
        </div>

        <!-- 画像 Agent -->
        <div class="bind-item">
          <div class="bind-top">
            <div>
              <div class="bind-name">画像 Agent <el-tag size="small" effect="plain">预处理</el-tag></div>
              <div class="bind-desc">项目预处理的图纸摘要与批次关系图</div>
            </div>
            <el-switch v-model="agentSettings.profile_agent_enabled" size="small" />
          </div>
          <el-select v-model="profileIdx" size="small" class="bind-select">
            <el-option label="跟随识图模型" :value="-1" />
            <el-option v-for="(p, i) in providers" :key="i"
              :label="providerLabel(p)" :value="i" :disabled="!p.enabled" />
          </el-select>
          <div class="bind-current" v-if="profileIdx === -1">当前：跟随识图模型</div>
          <div class="bind-current" v-else-if="profileIdx >= 0 && providers[profileIdx]">
            当前：{{ providers[profileIdx].name || '未命名' }} · {{ providers[profileIdx].model || '未填模型名' }}
          </div>
        </div>

        <!-- 材料提取 -->
        <div class="bind-item">
          <div class="bind-top">
            <div>
              <div class="bind-name">材料提取</div>
              <div class="bind-desc">图纸批量提取材料清单（JSON 输出）</div>
            </div>
          </div>
          <el-select v-model="materialsIdx" size="small" class="bind-select">
            <el-option label="跟随识图模型" :value="-1" />
            <el-option v-for="(p, i) in providers" :key="i"
              :label="providerLabel(p)" :value="i" :disabled="!p.enabled" />
          </el-select>
          <div class="bind-current" v-if="materialsIdx === -1">当前：跟随识图模型</div>
          <div class="bind-current" v-else-if="materialsIdx >= 0 && providers[materialsIdx]">
            当前：{{ providers[materialsIdx].name || '未命名' }} · {{ providers[materialsIdx].model || '未填模型名' }}
          </div>
        </div>

        <!-- 快速交底 -->
        <div class="bind-item">
          <div class="bind-top">
            <div>
              <div class="bind-name">快速交底</div>
              <div class="bind-desc">图纸一键生成施工交底文件</div>
            </div>
          </div>
          <el-select v-model="briefingIdx" size="small" class="bind-select">
            <el-option label="跟随识图模型" :value="-1" />
            <el-option v-for="(p, i) in providers" :key="i"
              :label="providerLabel(p)" :value="i" :disabled="!p.enabled" />
          </el-select>
          <div class="bind-current" v-if="briefingIdx === -1">当前：跟随识图模型</div>
          <div class="bind-current" v-else-if="briefingIdx >= 0 && providers[briefingIdx]">
            当前：{{ providers[briefingIdx].name || '未命名' }} · {{ providers[briefingIdx].model || '未填模型名' }}
          </div>
        </div>
      </div>
    </el-card>

    <!-- ===== 识图参数 ===== -->
    <el-card shadow="never" class="section-card">
      <template #header>
        <div class="card-heading">
          <span class="card-title">识图参数</span>
          <span class="card-desc">影响图纸渲染、OCR 与文字层注入的识别行为</span>
        </div>
      </template>

      <div class="param-grid">
        <div class="param-item">
          <div class="param-text">
            <div class="param-name">分块渲染</div>
            <div class="param-desc">密集小字图纸自动触发（OCR 文本框≥100 且中位框高≤40px）</div>
          </div>
          <el-switch v-model="agentSettings.drawing_tile_enabled" />
        </div>
        <div class="param-item">
          <div class="param-text">
            <div class="param-name">PDF 视觉读取页数上限</div>
            <div class="param-desc">单份 PDF 最多渲染几页送入视觉模型</div>
          </div>
          <el-input-number v-model="agentSettings.drawing_pdf_max_pages" size="small"
            :min="1" :max="10" style="width: 90px" />
        </div>
        <div class="param-item">
          <div class="param-text">
            <div class="param-name">PDF 文字层注入上限</div>
            <div class="param-desc">注入 prompt 的文字层字符总量上限</div>
          </div>
          <el-input-number v-model="agentSettings.drawing_pdf_text_max" size="small"
            :min="1000" :max="50000" :step="1000" style="width: 110px" />
        </div>
        <div class="param-item">
          <div class="param-text">
            <div class="param-name">OCR 渲染精度 DPI</div>
            <div class="param-desc">无文字层扫描件本地 OCR 的渲染精度</div>
          </div>
          <el-input-number v-model="agentSettings.drawing_ocr_dpi" size="small"
            :min="72" :max="300" :step="10" style="width: 90px" />
        </div>
        <div class="param-item">
          <div class="param-text">
            <div class="param-name">OCR 文字层注入上限</div>
            <div class="param-desc">OCR 文字层注入 prompt 的字符上限</div>
          </div>
          <el-input-number v-model="agentSettings.drawing_ocr_text_max" size="small"
            :min="1000" :max="50000" :step="1000" style="width: 110px" />
        </div>
      </div>
    </el-card>

    <!-- ===== 系统说明 ===== -->
    <el-card shadow="never" class="section-card">
      <template #header>
        <div class="card-heading">
          <span class="card-title">系统说明</span>
          <span class="card-desc">版本与数据安全说明</span>
        </div>
      </template>
      <el-descriptions :column="1" border style="max-width: 640px">
        <el-descriptions-item label="系统名称">看图兔</el-descriptions-item>
        <el-descriptions-item label="版本">v1.0.0</el-descriptions-item>
        <el-descriptions-item label="功能简介">
          工程图纸识别助手。支持 DWG / DXF / PDF 图纸上传、AI 视觉问答、材料提取、快速交底、图纸集管理。
          项目模式下支持压缩包批量导入、自动预处理、脱敏保护。
        </el-descriptions-item>
        <el-descriptions-item label="支持的图纸格式">.dwg / .dxf / .pdf</el-descriptions-item>
        <el-descriptions-item label="项目会话保留时长">5 天（活跃自动续期）</el-descriptions-item>
        <el-descriptions-item label="数据安全">
          项目图纸经脱敏处理后送 AI 模型，敏感文字映射关系仅存服务端，LLM 侧仅见密文。
        </el-descriptions-item>
        <el-descriptions-item label="开源地址">
          <a href="https://github.com/xiaotutu" target="_blank">github.com/xiaotutu</a>
        </el-descriptions-item>
      </el-descriptions>
    </el-card>
  </div>
</template>

<script setup>
import { ref, onMounted } from 'vue'
import { ElMessage } from 'element-plus'
import api from '../../api'

const loading = ref(false)
const saving = ref(false)
const providers = ref([])
// 各功能的模型绑定（-1 = 跟随识图模型）
const drawingProviderIdx = ref(0)
const locateIdx = ref(-1)
const profileIdx = ref(-1)
const materialsIdx = ref(-1)
const briefingIdx = ref(-1)
const agentSettings = ref({
  drawing_tile_enabled: true,
  drawing_pdf_max_pages: 3,
  drawing_pdf_text_max: 8000,
  drawing_ocr_dpi: 150,
  drawing_ocr_text_max: 8000,
  snip_locate_enabled: true,
  profile_agent_enabled: true,
})

const PROVIDER_TYPES = [
  { label: 'OpenAI', value: 'openai' },
  { label: 'Claude', value: 'claude' },
  { label: 'DeepSeek', value: 'deepseek' },
  { label: '通义千问', value: 'qwen' },
  { label: '小米MiMo', value: 'mimo' },
  { label: 'Kimi', value: 'kimi' },
  { label: '智谱GLM', value: 'glm' },
  { label: 'MiniMax', value: 'minimax' },
  { label: '百炼', value: 'bailian' },
]

function providerLabel(p) {
  const n = p.name || '未命名'
  return p.model ? `${n} · ${p.model}` : n
}

async function load() {
  loading.value = true
  try {
    const { data } = await api.get('/system/llm-config')
    providers.value = data.providers.map(p => ({
      ...p,
      // key 明文回显、原样回传：留空 = 主动清除，不再有「空串冲掉已存 key」的问题
      api_key: p.api_key || '',
      _testing: false,
      _testResult: null,
    }))
    drawingProviderIdx.value = data.drawing_provider_index
    locateIdx.value = data.locate_provider_index ?? -1
    profileIdx.value = data.profile_provider_index ?? -1
    materialsIdx.value = data.materials_provider_index ?? -1
    briefingIdx.value = data.briefing_provider_index ?? -1
    Object.assign(agentSettings.value, data.agent_settings)
  } catch (e) {
    ElMessage.error(e.response?.data?.detail || e.message)
  } finally {
    loading.value = false
  }
}

function addProvider() {
  providers.value.push({
    name: '', provider: 'openai', api_key: '', base_url: '',
    model: '', temperature: 0.7, max_tokens: 4096,
    enabled: true, supports_vision: false, thinking_effort: 'off',
    _testing: false, _testResult: null,
  })
}

function removeProvider(idx) {
  providers.value.splice(idx, 1)
  if (drawingProviderIdx.value >= providers.value.length) {
    drawingProviderIdx.value = 0
  }
  // 绑定索引若指向被删行，回退为跟随
  for (const r of [locateIdx, profileIdx, materialsIdx, briefingIdx]) {
    if (r.value !== -1 && (r.value >= providers.value.length || r.value === idx)) {
      r.value = r.value === idx ? -1 : (r.value > idx ? r.value - 1 : r.value)
    }
  }
}

/** 测试连通性：index 用 load 时的原索引（未保存前指向后端当前配置），新行不带 index */
async function testRow(row) {
  row._testing = true
  row._testResult = null
  try {
    const { data } = await api.post('/system/llm-config/test', {
      index: row.index ?? null,
      name: row.name, provider: row.provider,
      api_key: row.api_key, base_url: row.base_url, model: row.model,
    })
    if (data.ok) {
      row._testResult = 'ok'
      ElMessage.success(`连接成功 · ${data.latency_ms}ms · ${data.model || data.provider}`)
    } else {
      row._testResult = 'fail'
      ElMessage.error(`连接失败：${data.message || '未知错误'}`)
    }
  } catch (e) {
    row._testResult = 'fail'
    ElMessage.error(e.response?.data?.detail || e.message || '测试失败')
  } finally {
    row._testing = false
  }
}

async function saveAll() {
  saving.value = true
  try {
    await api.put('/system/llm-config', {
      providers: providers.value.map((p, i) => ({ ...p, index: i })),
      drawing_provider_index: drawingProviderIdx.value,
      locate_provider_index: locateIdx.value,
      profile_provider_index: profileIdx.value,
      materials_provider_index: materialsIdx.value,
      briefing_provider_index: briefingIdx.value,
      agent_settings: agentSettings.value,
    })
    ElMessage.success('已保存')
    load()
  } catch (e) {
    ElMessage.error(e.response?.data?.detail || e.message)
  } finally {
    saving.value = false
  }
}

onMounted(load)
</script>

<style scoped>
/* 页头/留白统一走 App.vue 全局规范 */

.section-card { margin-bottom: 16px; }
.section-card:last-child { margin-bottom: 0; }

.card-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
}
.card-heading { display: flex; align-items: baseline; gap: 10px; flex-wrap: wrap; }
.card-title { font-size: 15px; font-weight: 600; color: #303133; }
.card-desc { font-size: 12px; color: #909399; }

.table-tip { padding: 24px 0; text-align: center; color: #909399; font-size: 13px; }

/* ===== 模型分配 ===== */
.bind-grid {
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(280px, 1fr));
  gap: 12px;
}
.bind-item {
  border: 1px solid #ebeef5;
  border-radius: 8px;
  padding: 12px 14px;
  background: #fafbfc;
}
.bind-top {
  display: flex;
  justify-content: space-between;
  align-items: flex-start;
  gap: 8px;
  margin-bottom: 8px;
}
.bind-name {
  font-size: 14px;
  font-weight: 600;
  color: #303133;
  display: flex;
  align-items: center;
  gap: 6px;
}
.bind-desc { font-size: 12px; color: #909399; margin-top: 3px; line-height: 1.5; }
.bind-select { width: 100%; }
.bind-current { font-size: 12px; color: #409eff; margin-top: 6px; }

/* ===== 识图参数 ===== */
.param-grid {
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(340px, 1fr));
  gap: 12px;
}
.param-item {
  display: flex;
  justify-content: space-between;
  align-items: center;
  gap: 16px;
  border: 1px solid #ebeef5;
  border-radius: 8px;
  padding: 12px 16px;
  background: #fafbfc;
}
.param-text { min-width: 0; }
.param-name { font-size: 14px; font-weight: 600; color: #303133; }
.param-desc { font-size: 12px; color: #909399; margin-top: 3px; line-height: 1.5; }
</style>
