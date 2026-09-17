<template>
  <div class="user-management">
    <div class="page-header">
      <h2>用户管理</h2>
      <el-button type="primary" @click="showCreateDialog">
        <el-icon><Plus /></el-icon> 添加用户
      </el-button>
    </div>

    <el-card>
      <div class="toolbar">
        <el-input
          v-model="searchText"
          placeholder="搜索用户名/邮箱/手机号"
          :prefix-icon="Search"
          clearable
          style="width: 280px"
        />
      </div>

      <el-table :data="filteredUsers" stripe v-loading="loading">
        <el-table-column prop="username" label="用户名" width="120" />
        <el-table-column prop="display_name" label="显示名" width="120" />
        <el-table-column prop="email" label="邮箱" width="180">
          <template #default="{ row }">
            {{ row.email || '-' }}
          </template>
        </el-table-column>
        <el-table-column prop="phone" label="手机号" width="130">
          <template #default="{ row }">
            {{ row.phone || '-' }}
          </template>
        </el-table-column>
        <el-table-column label="角色" width="100">
          <template #default="{ row }">
            <el-tag v-if="row.is_super_admin" type="danger" size="small">超级管理员</el-tag>
            <el-tag v-else type="info" size="small">成员</el-tag>
          </template>
        </el-table-column>
        <el-table-column label="状态" width="80">
          <template #default="{ row }">
            <el-tag :type="row.is_active ? 'success' : 'danger'" size="small">
              {{ row.is_active ? '启用' : '禁用' }}
            </el-tag>
          </template>
        </el-table-column>
        <el-table-column label="操作" width="180" fixed="right">
          <template #default="{ row }">
            <el-button link type="primary" @click="showEditDialog(row)">编辑</el-button>
            <el-button
              link
              :type="row.is_active ? 'danger' : 'success'"
              @click="toggleActive(row)"
              v-if="row.id !== currentUserId"
            >
              {{ row.is_active ? '禁用' : '启用' }}
            </el-button>
            <el-button
              link
              type="danger"
              v-if="authStore.isSuperAdmin && !row.is_active && !row.is_super_admin && row.id !== currentUserId"
              @click="permanentDelete(row)"
            >
              删除
            </el-button>
          </template>
        </el-table-column>
      </el-table>
    </el-card>

    <!-- 创建/编辑用户弹窗 -->
    <el-dialog
      v-model="dialogVisible"
      :title="isEdit ? '编辑用户' : '添加用户'"
      width="500px"
      @close="resetForm"
    >
      <el-form ref="formRef" :model="form" :rules="formRules" label-width="100px">
        <el-form-item label="用户名" prop="username">
          <el-input v-model="form.username" :disabled="isEdit" placeholder="用户名" />
        </el-form-item>
        <el-form-item label="密码" prop="password" v-if="!isEdit">
          <el-input v-model="form.password" type="password" show-password placeholder="至少6位" />
        </el-form-item>
        <el-form-item label="显示名">
          <el-input v-model="form.display_name" placeholder="显示名称" />
        </el-form-item>
        <el-form-item label="邮箱">
          <el-input v-model="form.email" placeholder="邮箱（可选）" />
        </el-form-item>
        <el-form-item label="手机号">
          <el-input v-model="form.phone" placeholder="手机号（可选）" />
        </el-form-item>
        <el-form-item label="超级管理员" v-if="authStore.isSuperAdmin">
          <el-switch v-model="form.is_super_admin" />
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="dialogVisible = false">取消</el-button>
        <el-button type="primary" :loading="submitting" @click="submitForm">
          {{ isEdit ? '保存' : '创建' }}
        </el-button>
      </template>
    </el-dialog>
  </div>
</template>

<script setup>
import { ref, reactive, computed, onMounted } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import { Plus, Search } from '@element-plus/icons-vue'
import { adminUsers } from '../../api/auth'
import { useAuthStore } from '../../stores/auth'

const authStore = useAuthStore()
const currentUserId = computed(() => authStore.userId)

const loading = ref(false)
const submitting = ref(false)
const users = ref([])
const searchText = ref('')
const dialogVisible = ref(false)
const isEdit = ref(false)
const editingId = ref(null)
const formRef = ref(null)

const form = reactive({
  username: '',
  password: '',
  display_name: '',
  email: '',
  phone: '',
  is_super_admin: false,
})

const formRules = {
  username: [{ required: true, message: '请输入用户名', trigger: 'blur' }],
  password: [{ required: true, message: '请输入密码', trigger: 'blur' }],
}

const filteredUsers = computed(() => {
  if (!searchText.value) return users.value
  const keyword = searchText.value.toLowerCase()
  return users.value.filter(u =>
    u.username?.toLowerCase().includes(keyword) ||
    u.email?.toLowerCase().includes(keyword) ||
    u.phone?.includes(keyword)
  )
})

async function loadUsers() {
  loading.value = true
  try {
    const res = await adminUsers.list()
    users.value = res.data
  } catch (e) {
    ElMessage.error('加载用户列表失败')
  } finally {
    loading.value = false
  }
}

function showCreateDialog() {
  isEdit.value = false
  editingId.value = null
  resetForm()
  dialogVisible.value = true
}

function showEditDialog(user) {
  isEdit.value = true
  editingId.value = user.id
  Object.assign(form, {
    username: user.username,
    password: '',
    display_name: user.display_name || '',
    email: user.email || '',
    phone: user.phone || '',
    is_super_admin: user.is_super_admin,
  })
  dialogVisible.value = true
}

function resetForm() {
  Object.assign(form, {
    username: '',
    password: '',
    display_name: '',
    email: '',
    phone: '',
    is_super_admin: false,
  })
}

async function submitForm() {
  const valid = await formRef.value?.validate().catch(() => false)
  if (!valid) return

  submitting.value = true
  try {
    if (isEdit.value) {
      const data = {
        display_name: form.display_name,
        email: form.email || undefined,
        phone: form.phone || undefined,
        is_super_admin: form.is_super_admin,
      }
      await adminUsers.update(editingId.value, data)
      ElMessage.success('用户已更新')
    } else {
      await adminUsers.create({
        username: form.username,
        password: form.password,
        display_name: form.display_name,
        email: form.email || undefined,
        phone: form.phone || undefined,
        is_super_admin: form.is_super_admin,
      })
      ElMessage.success('用户已创建')
    }
    dialogVisible.value = false
    await loadUsers()
  } catch (e) {
    ElMessage.error(e.response?.data?.detail || '操作失败')
  } finally {
    submitting.value = false
  }
}

async function toggleActive(user) {
  const action = user.is_active ? '禁用' : '启用'
  try {
    await ElMessageBox.confirm(`确定要${action}用户 ${user.username} 吗？`, '确认', {
      type: 'warning',
    })
    await adminUsers.update(user.id, { is_active: !user.is_active })
    ElMessage.success(`用户已${action}`)
    await loadUsers()
  } catch {}
}

async function permanentDelete(user) {
  try {
    await ElMessageBox.confirm(
      `确定要彻底删除账号 ${user.username} 吗？\n该操作不可恢复，请谨慎操作。`,
      '危险操作',
      { type: 'error', confirmButtonText: '彻底删除', cancelButtonText: '取消' }
    )
    await adminUsers.permanentDelete(user.id)
    ElMessage.success('账号已彻底删除')
    await loadUsers()
  } catch {}
}

onMounted(() => {
  loadUsers()
})
</script>

<style scoped>
.user-management {
  max-width: 1200px;
  margin: 0 auto;
}
.page-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
  margin-bottom: 20px;
}
.page-header h2 {
  margin: 0;
  font-size: 20px;
  color: #303133;
}
.toolbar {
  margin-bottom: 16px;
}
</style>
