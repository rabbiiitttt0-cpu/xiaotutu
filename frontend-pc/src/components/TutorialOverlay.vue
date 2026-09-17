<template>
  <el-dialog
    v-model="visible"
    :title="current.title"
    width="520px"
    :close-on-click-modal="true"
    @close="onClose"
  >
    <div style="min-height: 120px">
      <div style="display: flex; align-items: center; gap: 12px; margin-bottom: 16px">
        <el-tag type="info">{{ stepIndex + 1 }} / {{ steps.length }}</el-tag>
        <el-progress :percentage="progress" :stroke-width="6" :show-text="false" style="flex: 1" />
      </div>

      <div style="display: flex; gap: 16px; align-items: flex-start">
        <el-icon :size="32" :style="{ color: current.color || '#409eff', flexShrink: 0, marginTop: '4px' }">
          <component :is="current.icon" />
        </el-icon>
        <div>
          <div style="font-weight: 500; margin-bottom: 8px">{{ current.content }}</div>
          <div v-if="current.detail" style="font-size: 13px; color: #909399; line-height: 1.6">
            {{ current.detail }}
          </div>
        </div>
      </div>
    </div>

    <template #footer>
      <div style="display: flex; justify-content: space-between; align-items: center">
        <el-checkbox v-model="dontShowAgain" label="不再显示" size="small" />
        <div>
          <el-button v-if="stepIndex > 0" @click="prev">上一步</el-button>
          <el-button v-if="stepIndex < steps.length - 1" type="primary" @click="next">下一步</el-button>
          <el-button v-if="stepIndex === steps.length - 1" type="primary" @click="finish">开始使用</el-button>
        </div>
      </div>
    </template>
  </el-dialog>
</template>

<script setup>
import { ref, computed, watch } from 'vue'

const props = defineProps({
  steps: { type: Array, default: () => [] },
  pageKey: { type: String, required: true },
})

const visible = ref(false)
const stepIndex = ref(0)
const dontShowAgain = ref(false)

const current = computed(() => props.steps[stepIndex.value] || {})
const progress = computed(() => props.steps.length > 0 ? Math.round(((stepIndex.value + 1) / props.steps.length) * 100) : 0)

function checkAndShow() {
  const enabled = localStorage.getItem('tutorialEnabled') !== 'false'
  const seen = localStorage.getItem(`tutorial_seen_${props.pageKey}`)
  if (enabled && !seen && props.steps.length > 0) {
    stepIndex.value = 0
    visible.value = true
  }
}

function next() { if (stepIndex.value < props.steps.length - 1) stepIndex.value++ }
function prev() { if (stepIndex.value > 0) stepIndex.value-- }

function finish() {
  // v4.9.12：任何方式完成/关闭都只出现一次（此前必须勾选"不再显示"否则每进页面都弹，
  // 弹窗遮罩拦截页面点击，用户误判"UI无响应"）
  localStorage.setItem(`tutorial_seen_${props.pageKey}`, '1')
  visible.value = false
}

function onClose() {
  localStorage.setItem(`tutorial_seen_${props.pageKey}`, '1')
}

// Expose show method
defineExpose({ show: checkAndShow })
</script>
