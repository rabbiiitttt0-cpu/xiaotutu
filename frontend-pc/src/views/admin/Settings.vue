<template>
  <div>
    <div class="page-header"><h2>系统设置</h2></div>

    <el-tabs v-model="activeTab" type="border-card">

      <!-- ===== 模型设置 ===== -->
      <el-tab-pane label="模型设置" name="models">
        <div style="margin-bottom: 12px; display: flex; justify-content: space-between; align-items: center">
          <span style="color: #909399; font-size: 13px">
            配置接入的 AI 模型。识图助手使用下方选中的「识图模型」。
          </span>
          <div>
            <el-button size="small" @click="addProvider">添加模型</el-button>
            <el-button size="small" type="primary" :loading="saving" @click="saveAll">保存全部</el-button>
          </div>
        </div>

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
              <el-input v-model="row.api_key" size="small" type="password" show-password
                :placeholder="row.has_key ? '已配置（留空不修改）' : 'sk-...'" />
            </template>
          </el-table-column>
          <el-table-column label="Base URL" min-width="180">
            <template #default="{ row }">
              <el-input v-model="row.base_url" size="small" placeholder="https://api.example.com/v1" />
            </template>
          </el-table-column>
          <el-table-column label="模型名" min-width="140">
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
          <el-table-column label="识图模型" width="75" align="center">
            <template #default="{ row, $index }">
              <el-radio v-model="drawingProviderIdx" :value="$index" :disabled="!row.enabled">
                <span></span>
              </el-radio>
            </template>
          </el-table-column>
          <el-table-column label="操作" width="65" align="center">
            <template #default="{ $index }">
              <el-button size="small" type="danger" plain @click="removeProvider($index)">删</el-button>
            </template>
          </el-table-column>
        </el-table>

        <el-divider content-position="left">识图参数</el-divider>
        <el-form label-width="180px" size="small" style="max-width: 560px">
          <el-form-item label="分块渲染（密集小字自动触发）">
            <el-switch v-model="agentSettings.drawing_tile_enabled" />
          </el-form-item>
          <el-form-item label="PDF 视觉读取页数上限">
            <el-input-number v-model="agentSettings.drawing_pdf_max_pages" :min="1" :max="10" />
          </el-form-item>
          <el-form-item label="PDF 文字层注入上限（字符）">
            <el-input-number v-model="agentSettings.drawing_pdf_text_max" :min="1000" :max="50000" :step="1000" />
          </el-form-item>
          <el-form-item label="OCR 渲染精度 DPI">
            <el-input-number v-model="agentSettings.drawing_ocr_dpi" :min="72" :max="300" />
          </el-form-item>
          <el-form-item label="OCR 文字层注入上限（字符）">
            <el-input-number v-model="agentSettings.drawing_ocr_text_max" :min="1000" :max="50000" :step="1000" />
          </el-form-item>
        </el-form>
      </el-tab-pane>

      <!-- ===== 系统说明 ===== -->
      <el-tab-pane label="系统说明" name="about">
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
      </el-tab-pane>

    </el-tabs>
  </div>
</template>

<script setup>
import { ref, onMounted } from 'vue'
import { ElMessage } from 'element-plus'
import api from '../../api'

const activeTab = ref('models')
const loading = ref(false)
const saving = ref(false)
const providers = ref([])
const drawingProviderIdx = ref(0)
const agentSettings = ref({
  drawing_tile_enabled: true,
  drawing_pdf_max_pages: 3,
  drawing_pdf_text_max: 8000,
  drawing_ocr_dpi: 150,
  drawing_ocr_text_max: 8000,
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

async function load() {
  loading.value = true
  try {
    const { data } = await api.get('/system/llm-config')
    providers.value = data.providers.map(p => ({
      ...p,
      has_key: !!p.api_key && !p.api_key.includes('****'),
      api_key: p.api_key.includes('****') ? '' : p.api_key,
    }))
    drawingProviderIdx.value = data.drawing_provider_index
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
    has_key: false,
  })
}

function removeProvider(idx) {
  providers.value.splice(idx, 1)
  if (drawingProviderIdx.value >= providers.value.length) {
    drawingProviderIdx.value = 0
  }
}

async function saveAll() {
  saving.value = true
  try {
    await api.put('/system/llm-config', {
      providers: providers.value.map((p, i) => ({ ...p, index: i })),
      drawing_provider_index: drawingProviderIdx.value,
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
.page-header { margin-bottom: 16px; }
.page-header h2 { margin: 0; font-size: 20px; }
</style>
