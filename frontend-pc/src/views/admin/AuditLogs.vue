<template>
  <div>
    <div class="page-header"><h2>日志查询</h2></div>

    <el-card shadow="never">
      <el-tabs v-model="tab">
        <!-- ============ 操作审计日志 ============ -->
        <el-tab-pane label="操作审计日志" name="audit">
          <el-form inline size="small" style="margin-bottom: 12px">
            <el-form-item label="事件类型">
              <el-select v-model="auditFilter.event_type" clearable placeholder="全部" style="width: 150px" @change="loadAudit(1)">
                <el-option v-for="(label, val) in eventTypeMap" :key="val" :label="label" :value="val" />
              </el-select>
            </el-form-item>
            <el-form-item label="用户">
              <el-input v-model="auditFilter.username" clearable placeholder="用户名" style="width: 140px" @keyup.enter="loadAudit(1)" />
            </el-form-item>
            <el-form-item label="关键字">
              <el-input v-model="auditFilter.keyword" clearable placeholder="详情关键字" style="width: 160px" @keyup.enter="loadAudit(1)" />
            </el-form-item>
            <el-form-item label="时间">
              <el-date-picker
                v-model="auditTimeRange" type="datetimerange" range-separator="至"
                start-placeholder="开始" end-placeholder="结束" value-format="YYYY-MM-DD HH:mm:ss"
                style="width: 340px" @change="loadAudit(1)"
              />
            </el-form-item>
            <el-form-item>
              <el-button type="primary" @click="loadAudit(1)">查询</el-button>
              <el-button @click="exportAudit">导出CSV</el-button>
            </el-form-item>
          </el-form>

          <el-table :data="auditItems" stripe size="small" border>
            <el-table-column prop="created_at" label="时间" width="170" />
            <el-table-column label="类型" width="110">
              <template #default="{ row }">
                <el-tag size="small" :type="tagType(row.event_type)">{{ eventTypeMap[row.event_type] || row.event_type }}</el-tag>
              </template>
            </el-table-column>
            <el-table-column prop="username" label="用户" width="110" show-overflow-tooltip />
            <el-table-column prop="ip" label="IP" width="130" />
            <el-table-column prop="detail" label="详情" min-width="220" show-overflow-tooltip />
          </el-table>

          <el-pagination
            style="margin-top: 12px; justify-content: flex-end"
            background layout="total, prev, pager, next, sizes"
            :total="auditTotal" v-model:current-page="auditPage" v-model:page-size="auditPageSize"
            :page-sizes="[20, 50, 100]" @current-change="loadAudit" @size-change="loadAudit(1)"
          />
        </el-tab-pane>

        <!-- ============ LLM 调用日志 ============ -->
        <el-tab-pane label="LLM 调用日志" name="llm">
          <!-- 汇总统计 -->
          <el-row :gutter="12" style="margin-bottom: 12px">
            <el-col :span="6"><el-card shadow="never" class="stat-card"><div class="stat-num">{{ llmStats.total_calls }}</div><div class="stat-label">总调用次数</div></el-card></el-col>
            <el-col :span="6"><el-card shadow="never" class="stat-card"><div class="stat-num">{{ (llmStats.total_tokens || 0).toLocaleString() }}</div><div class="stat-label">总 token</div></el-card></el-col>
            <el-col :span="6"><el-card shadow="never" class="stat-card"><div class="stat-num" :style="{ color: llmStats.failed ? '#f56c6c' : '#67c23a' }">{{ llmStats.failed }}</div><div class="stat-label">失败次数</div></el-card></el-col>
            <el-col :span="6"><el-card shadow="never" class="stat-card"><div class="stat-num">{{ Object.keys(llmStats.by_module || {}).length }}</div><div class="stat-label">覆盖模块数</div></el-card></el-col>
          </el-row>

          <el-form inline size="small" style="margin-bottom: 12px">
            <el-form-item label="模块">
              <el-select v-model="llmFilter.module" clearable placeholder="全部" style="width: 140px" @change="loadLlm(1)">
                <el-option v-for="m in llmModules" :key="m" :label="m" :value="m" />
              </el-select>
            </el-form-item>
            <el-form-item label="状态">
              <el-select v-model="llmFilter.success" clearable placeholder="全部" style="width: 120px" @change="loadLlm(1)">
                <el-option label="成功" value="true" />
                <el-option label="失败" value="false" />
              </el-select>
            </el-form-item>
            <el-form-item label="时间">
              <el-date-picker
                v-model="llmTimeRange" type="datetimerange" range-separator="至"
                start-placeholder="开始" end-placeholder="结束" value-format="YYYY-MM-DD HH:mm:ss"
                style="width: 340px" @change="loadLlm(1)"
              />
            </el-form-item>
            <el-form-item><el-button type="primary" @click="loadLlm(1)">查询</el-button></el-form-item>
          </el-form>

          <el-table :data="llmItems" stripe size="small" border>
            <el-table-column prop="created_at" label="时间" width="170" />
            <el-table-column prop="module" label="模块" width="110" />
            <el-table-column prop="model" label="模型" width="150" show-overflow-tooltip />
            <el-table-column prop="username" label="用户" width="90" />
            <el-table-column label="输入tokens" width="90"><template #default="{ row }">{{ (row.prompt_tokens || 0).toLocaleString() }}</template></el-table-column>
            <el-table-column label="输出tokens" width="90"><template #default="{ row }">{{ (row.completion_tokens || 0).toLocaleString() }}</template></el-table-column>
            <el-table-column label="延迟" width="80"><template #default="{ row }">{{ row.latency_ms }}ms</template></el-table-column>
            <el-table-column label="状态" width="70">
              <template #default="{ row }">
                <el-tag size="small" :type="row.success ? 'success' : 'danger'">{{ row.success ? '成功' : '失败' }}</el-tag>
              </template>
            </el-table-column>
            <el-table-column prop="error" label="错误" min-width="160" show-overflow-tooltip />
          </el-table>

          <el-pagination
            style="margin-top: 12px; justify-content: flex-end"
            background layout="total, prev, pager, next, sizes"
            :total="llmTotal" v-model:current-page="llmPage" v-model:page-size="llmPageSize"
            :page-sizes="[20, 50, 100]" @current-change="loadLlm" @size-change="loadLlm(1)"
          />
        </el-tab-pane>

        <!-- ============ 视觉模型用量 ============ -->
        <el-tab-pane label="视觉模型用量" name="vision">
          <el-row :gutter="12" style="margin-bottom: 12px">
            <el-col :span="6">
              <el-card shadow="never" class="stat-card">
                <div class="stat-num">{{ vision.total.requests ?? 0 }}</div>
                <div class="stat-label">累计请求（带图 {{ vision.total.with_image ?? 0 }}）</div>
              </el-card>
            </el-col>
            <el-col :span="6">
              <el-card shadow="never" class="stat-card">
                <div class="stat-num">{{ (vision.total.prompt_tokens || 0).toLocaleString() }}</div>
                <div class="stat-label">输入 tokens（缓存命中 {{ (vision.total.cache_hit_tokens || 0).toLocaleString() }}）</div>
              </el-card>
            </el-col>
            <el-col :span="6">
              <el-card shadow="never" class="stat-card">
                <div class="stat-num">{{ (vision.total.completion_tokens || 0).toLocaleString() }}</div>
                <div class="stat-label">输出 tokens</div>
              </el-card>
            </el-col>
            <el-col :span="6">
              <el-card shadow="never" class="stat-card">
                <div class="stat-num">${{ vision.total.est_cost_usd ?? 0 }}</div>
                <div class="stat-label">估算费用</div>
              </el-card>
            </el-col>
          </el-row>

          <div class="cost-note">{{ vision.cost_note }}</div>

          <h4 class="sub-title">近 14 天</h4>
          <el-table :data="vision.by_day" stripe size="small" border style="margin-bottom: 16px">
            <el-table-column prop="date" label="日期" width="120" />
            <el-table-column prop="requests" label="请求" width="90" />
            <el-table-column prop="with_image" label="带图" width="90" />
            <el-table-column label="输入tokens" width="130">
              <template #default="{ row }">{{ (row.prompt_tokens || 0).toLocaleString() }}</template>
            </el-table-column>
            <el-table-column label="输出tokens" width="130">
              <template #default="{ row }">{{ (row.completion_tokens || 0).toLocaleString() }}</template>
            </el-table-column>
            <el-table-column label="估算费用" min-width="120">
              <template #default="{ row }">${{ row.est_cost_usd }}</template>
            </el-table-column>
          </el-table>

          <h4 class="sub-title">最近调用</h4>
          <el-table :data="vision.recent" stripe size="small" border>
            <el-table-column prop="ts" label="时间" width="170" />
            <el-table-column prop="endpoint" label="功能" width="110" />
            <el-table-column label="带图" width="70">
              <template #default="{ row }">{{ row.with_image ? '是' : '否' }}</template>
            </el-table-column>
            <el-table-column label="输入tokens" width="110">
              <template #default="{ row }">{{ (row.prompt_tokens || 0).toLocaleString() }}</template>
            </el-table-column>
            <el-table-column label="输出tokens" width="110">
              <template #default="{ row }">{{ (row.completion_tokens || 0).toLocaleString() }}</template>
            </el-table-column>
            <el-table-column label="缓存命中" width="100">
              <template #default="{ row }">{{ (row.cache_hit_tokens || 0).toLocaleString() }}</template>
            </el-table-column>
          </el-table>
        </el-tab-pane>

        <!-- ============ 系统错误日志 ============ -->
        <el-tab-pane label="系统错误日志" name="errors">
          <el-form inline size="small" style="margin-bottom: 12px">
            <el-form-item label="关键字">
              <el-input v-model="errorFilter.keyword" clearable placeholder="错误关键字" style="width: 200px" @keyup.enter="loadErrors" />
            </el-form-item>
            <el-form-item label="行数">
              <el-input-number v-model="errorFilter.lines" :min="50" :max="2000" :step="50" @change="loadErrors" />
            </el-form-item>
            <el-form-item>
              <el-button type="primary" @click="loadErrors">查询</el-button>
              <el-button @click="exportErrors">导出TXT</el-button>
            </el-form-item>
          </el-form>

          <div style="font-size: 12px; color: #909399; margin-bottom: 8px">共 {{ errorTotal }} 条（匹配行，最新在前）</div>
          <div class="error-log-box">
            <div v-for="(e, i) in errorItems" :key="i" class="error-log-line" :class="{ isError: e.line.includes('[ERROR]') }">{{ e.line }}</div>
            <el-empty v-if="!errorItems.length" description="暂无错误日志（运行正常）" :image-size="60" />
          </div>
        </el-tab-pane>
      </el-tabs>
    </el-card>
  </div>
</template>

<script setup>
import { ref, onMounted } from 'vue'
import { ElMessage } from 'element-plus'
import { audit as auditApi, drawing as drawingApi } from '../../api'

const tab = ref('audit')

// 事件类型中文映射
const eventTypeMap = {
  login_success: '登录成功',
  login_failed: '登录失败',
  user_create: '创建用户',
  user_update: '编辑用户',
  user_disable: '禁用用户',
  user_delete: '删除账号',
  grant_create: '管理员授权',
  grant_revoke: '收回授权',
  drawing_upload: '上传图纸',
}

function tagType(type) {
  if (type?.includes('failed')) return 'danger'
  if (type?.startsWith('login_success')) return 'success'
  if (type?.startsWith('user_') || type?.startsWith('grant_')) return 'warning'
  return 'info'
}

// ===== 审计日志 =====
const auditItems = ref([])
const auditTotal = ref(0)
const auditPage = ref(1)
const auditPageSize = ref(50)
const auditFilter = ref({ event_type: '', username: '', keyword: '' })
const auditTimeRange = ref(null)

async function loadAudit(p = auditPage.value) {
  auditPage.value = p
  const params = {
    page: auditPage.value,
    page_size: auditPageSize.value,
    event_type: auditFilter.value.event_type || undefined,
    username: auditFilter.value.username || undefined,
    keyword: auditFilter.value.keyword || undefined,
    start: auditTimeRange.value?.[0] || undefined,
    end: auditTimeRange.value?.[1] || undefined,
  }
  const { data } = await auditApi.logs(params)
  auditItems.value = data.items
  auditTotal.value = data.total
}

function exportAudit() {
  const header = '时间,类型,用户,IP,详情\n'
  const rows = auditItems.value.map(r =>
    `${r.created_at},"${eventTypeMap[r.event_type] || r.event_type}","${r.username || ''}","${r.ip || ''}","${(r.detail || '').replace(/"/g, '""')}"`
  ).join('\n')
  const blob = new Blob(['﻿' + header + rows], { type: 'text/csv;charset=utf-8' })
  const a = document.createElement('a')
  a.href = URL.createObjectURL(blob)
  a.download = `审计日志_${new Date().toISOString().slice(0, 10)}.csv`
  a.click()
  URL.revokeObjectURL(a.href)
  ElMessage.success('已导出当前筛选结果')
}

// ===== LLM 调用日志 =====
const llmItems = ref([])
const llmTotal = ref(0)
const llmPage = ref(1)
const llmPageSize = ref(50)
const llmFilter = ref({ module: '', success: '' })
const llmTimeRange = ref(null)
const llmStats = ref({ total_calls: 0, total_tokens: 0, failed: 0, by_module: {} })
const llmModules = ref([])

async function loadLlm(p = llmPage.value) {
  llmPage.value = p
  const params = {
    page: llmPage.value,
    page_size: llmPageSize.value,
    module: llmFilter.value.module || undefined,
    success: llmFilter.value.success || undefined,
    start: llmTimeRange.value?.[0] || undefined,
    end: llmTimeRange.value?.[1] || undefined,
  }
  const { data } = await auditApi.llmCalls(params)
  llmItems.value = data.items
  llmTotal.value = data.total
}

async function loadLlmStats() {
  try {
    const { data } = await auditApi.llmStats()
    llmStats.value = data
    llmModules.value = Object.keys(data.by_module || {})
  } catch { /* 静默 */ }
}

// ===== 视觉模型用量（识图模块 LLM 用量，仅超管）=====
const vision = ref({ total: {}, by_day: [], recent: [], cost_note: '' })

async function loadVisionUsage() {
  try {
    const { data } = await drawingApi.usage()
    vision.value = {
      total: data.total || {},
      by_day: data.by_day || [],
      recent: data.recent || [],
      cost_note: data.cost_note || '',
    }
  } catch { /* 静默（非超管无权限） */ }
}

// ===== 系统错误日志 =====
const errorItems = ref([])
const errorTotal = ref(0)
const errorFilter = ref({ keyword: '', lines: 200 })

async function loadErrors() {
  const { data } = await auditApi.errors({
    keyword: errorFilter.value.keyword || undefined,
    lines: errorFilter.value.lines,
  })
  errorItems.value = data.items
  errorTotal.value = data.total
}

function exportErrors() {
  const blob = new Blob([errorItems.value.map(e => e.line).join('\n')], { type: 'text/plain;charset=utf-8' })
  const a = document.createElement('a')
  a.href = URL.createObjectURL(blob)
  a.download = `错误日志_${new Date().toISOString().slice(0, 10)}.txt`
  a.click()
  URL.revokeObjectURL(a.href)
  ElMessage.success('已导出错误日志')
}

onMounted(() => {
  loadAudit(1)
  loadLlm(1)
  loadLlmStats()
  loadVisionUsage()
  loadErrors()
})
</script>

<style scoped>
.page-header { margin-bottom: 16px; }
.page-header h2 { margin: 0; font-size: 20px; }
.stat-card { text-align: center; }
.stat-num { font-size: 26px; font-weight: 600; color: #409eff; }
.stat-label { font-size: 12px; color: #909399; margin-top: 4px; }
.cost-note { font-size: 12px; color: #909399; margin-bottom: 12px; }
.sub-title { margin: 0 0 8px; font-size: 14px; color: #303133; }
.error-log-box {
  background: #1e1e1e;
  color: #d4d4d4;
  font-family: Consolas, Monaco, monospace;
  font-size: 12px;
  line-height: 1.7;
  padding: 12px;
  border-radius: 4px;
  max-height: 600px;
  overflow-y: auto;
  white-space: pre-wrap;
  word-break: break-all;
}
.error-log-line.isError { color: #f48771; }
</style>
