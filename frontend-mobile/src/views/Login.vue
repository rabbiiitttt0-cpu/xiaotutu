<template>
  <div class="login-page">
    <!-- 品牌区 -->
    <div class="brand">
      <div class="brand-logo">🐰</div>
      <h1 class="brand-title">小图兔</h1>
      <p class="brand-sub">工程图纸识别助手</p>
    </div>

    <!-- 登录/注册表单 -->
    <div class="form-card">
      <van-tabs v-model:active="activeTab" @change="onTabChange">
        <van-tab title="登录" name="login">
          <van-form @submit="handleLogin">
            <van-cell-group inset>
              <van-field
                v-model="loginForm.username"
                name="username"
                label="账号"
                placeholder="用户名 / 邮箱 / 手机号"
                :rules="[{ required: true, message: '请输入账号' }]"
              />
              <van-field
                v-model="loginForm.password"
                type="password"
                name="password"
                label="密码"
                placeholder="请输入密码"
                :rules="[{ required: true, message: '请输入密码' }]"
              />
            </van-cell-group>
            <div class="submit-wrap">
              <van-button round block type="primary" native-type="submit" :loading="loading">
                登录
              </van-button>
            </div>
          </van-form>
        </van-tab>

        <van-tab title="注册" name="register">
          <van-form @submit="handleRegister">
            <van-cell-group inset>
              <van-field v-model="regForm.username" name="username" label="用户名" placeholder="2-50字符" :rules="[{ required: true, message: '请输入用户名' }]" />
              <van-field v-model="regForm.password" type="password" name="password" label="密码" placeholder="至少6位" :rules="[{ required: true, message: '请输入密码' }]" />
              <van-field v-model="regForm.display_name" name="display_name" label="昵称" placeholder="可选" />
            </van-cell-group>
            <div class="submit-wrap">
              <van-button round block type="primary" native-type="submit" :loading="loading">
                注册
              </van-button>
            </div>
          </van-form>
        </van-tab>
      </van-tabs>
    </div>

    <!-- 底部：切换 PC 版 -->
    <div class="footer">
      <a class="switch-link" :href="pcUrl">🖥️ 切换到 PC 版</a>
    </div>
  </div>
</template>

<script setup>
import { ref, reactive, computed } from 'vue'
import { useRouter, useRoute } from 'vue-router'
import { showToast, showSuccessToast } from 'vant'
import { useAuthStore } from '../stores/auth'

const router = useRouter()
const route = useRoute()
const authStore = useAuthStore()

const activeTab = ref('login')
const loading = ref(false)
const loginForm = reactive({ username: '', password: '' })
const regForm = reactive({ username: '', password: '', display_name: '' })

// PC 版地址：本地 dev 走 PC 前端端口；生产部署后由后端同源服务
const pcUrl = computed(() => {
  const loc = window.location
  return `${loc.protocol}//${loc.hostname}:7780/login`
})

function onTabChange() {
  // 切换 tab 时清空 loading
}

async function handleLogin() {
  loading.value = true
  try {
    await authStore.login(loginForm.username, loginForm.password)
    showSuccessToast('登录成功')
    const redirect = route.query.redirect || '/drawing'
    router.push(redirect)
  } catch (e) {
    showToast(e.response?.data?.detail || '登录失败')
  } finally {
    loading.value = false
  }
}

async function handleRegister() {
  loading.value = true
  try {
    const { auth } = await import('../api/auth')
    await auth.register({ username: regForm.username, password: regForm.password, display_name: regForm.display_name || undefined })
    showSuccessToast('注册成功，请等待管理员审批')
    activeTab.value = 'login'
  } catch (e) {
    showToast(e.response?.data?.detail || '注册失败')
  } finally {
    loading.value = false
  }
}
</script>

<style scoped>
.login-page {
  min-height: 100vh;
  display: flex;
  flex-direction: column;
  background: linear-gradient(160deg, #003a6e 0%, #005a9c 60%, #f7f8fa 60%);
}
.brand {
  padding: 48px 24px 20px;
  color: #fff;
  text-align: center;
}
.brand-logo { font-size: 56px; line-height: 1; }
.brand-title { font-size: 28px; font-weight: 700; margin: 12px 0 4px; }
.brand-sub { font-size: 14px; opacity: 0.85; margin: 0; }
.form-card {
  flex: 1;
  margin: 0 16px;
  background: #fff;
  border-radius: 16px;
  padding: 16px;
  box-shadow: 0 8px 24px rgba(0, 0, 0, 0.08);
}
.submit-wrap { margin-top: 20px; }
.footer { padding: 16px; text-align: center; }
.switch-link { color: #409eff; font-size: 14px; text-decoration: none; }
</style>
