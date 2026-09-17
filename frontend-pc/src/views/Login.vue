<template>
  <div class="login-page" :class="{ 'form-open': showForm }">
    <!-- 品牌区（默认全屏，打开表单后收缩到 65%） -->
    <div class="login-brand">
      <img src="/login-calligraphy.png" alt="" class="login-calligraphy" />
      <div class="brand-content">
        <h1 class="brand-title" @click="openForm('login')">
          同舟智航施工方案管理系统
          <span class="title-tip">点击即可注册及登录试用</span>
        </h1>
        <el-tooltip content="点击了解中建港航局" placement="bottom" effect="dark" :offset="-15">
          <a
            href="https://cschcc.cscec.com/gywm/qyjj/"
            target="_blank"
            rel="noopener"
            class="brand-logo-link"
          >
            <img src="/logo-white.png" alt="中建港航局" class="brand-logo" />
          </a>
        </el-tooltip>
        <div class="brand-carousel">
          <transition name="fade" mode="out-in">
            <div :key="carouselIndex" class="brand-slide">
              <p class="brand-slogan">
                {{ carouselItems[carouselIndex].title }}
                <span class="brand-tip">{{ carouselItems[carouselIndex].desc }}</span>
              </p>
            </div>
          </transition>
          <div class="carousel-dots">
            <span
              v-for="(item, i) in carouselItems"
              :key="i"
              :class="['dot', { active: i === carouselIndex }]"
            ></span>
          </div>
        </div>
      </div>
    </div>

    <!-- 右上角导航 -->
    <div v-if="!showForm" class="top-nav">
      <span class="nav-item" @click="openForm('login')">登录</span>
      <span class="nav-divider"></span>
      <span class="nav-item" @click="openForm('register')">注册</span>
      <span class="nav-divider"></span>
      <span class="nav-item" @click="openAbout">了解系统</span>
    </div>

    <!-- 表单区（点击登录/注册后从右侧滑出，占 35%） -->
    <div class="login-form-side">
      <button class="close-btn" title="关闭" @click="closeForm">×</button>
      <div class="login-header">
        <img src="/logo.png" alt="中建港航局" class="login-logo" />
        <h1>同舟智航施工方案管理系统</h1>
      </div>

      <el-tabs v-model="activeTab" class="login-tabs">
        <!-- 登录 -->
        <el-tab-pane label="登录" name="login">
          <el-form ref="loginFormRef" :model="loginForm" :rules="loginRules" @submit.prevent="handleLogin">
            <el-form-item prop="username">
              <el-input
                v-model="loginForm.username"
                placeholder="用户名 / 邮箱 / 手机号"
                :prefix-icon="User"
                size="large"
              />
            </el-form-item>
            <el-form-item prop="password">
              <el-input
                v-model="loginForm.password"
                type="password"
                placeholder="密码"
                :prefix-icon="Lock"
                size="large"
                show-password
                @keyup.enter="handleLogin"
              />
            </el-form-item>
            <el-form-item>
              <el-button
                type="primary"
                size="large"
                :loading="loading"
                style="width: 100%"
                @click="handleLogin"
              >
                登 录
              </el-button>
            </el-form-item>
          </el-form>
        </el-tab-pane>

        <!-- 注册 -->
        <el-tab-pane label="注册" name="register">
          <el-form ref="registerFormRef" :model="registerForm" :rules="registerRules" @submit.prevent="handleRegister">
            <el-form-item prop="username">
              <el-input
                v-model="registerForm.username"
                placeholder="用户名"
                :prefix-icon="User"
                size="large"
              />
            </el-form-item>
            <el-form-item prop="email">
              <el-input
                v-model="registerForm.email"
                placeholder="邮箱（可选）"
                :prefix-icon="Message"
                size="large"
              />
            </el-form-item>
            <el-form-item prop="phone">
              <el-input
                v-model="registerForm.phone"
                placeholder="手机号（可选）"
                :prefix-icon="Phone"
                size="large"
              />
            </el-form-item>
            <el-form-item prop="password">
              <el-input
                v-model="registerForm.password"
                type="password"
                placeholder="密码（至少6位）"
                :prefix-icon="Lock"
                size="large"
                show-password
              />
            </el-form-item>
            <el-form-item prop="confirmPassword">
              <el-input
                v-model="registerForm.confirmPassword"
                type="password"
                placeholder="确认密码"
                :prefix-icon="Lock"
                size="large"
                show-password
                @keyup.enter="handleRegister"
              />
            </el-form-item>
            <el-form-item>
              <el-button
                type="primary"
                size="large"
                :loading="loading"
                style="width: 100%"
                @click="handleRegister"
              >
                注 册
              </el-button>
            </el-form-item>
          </el-form>
        </el-tab-pane>
      </el-tabs>

      <div class="login-footer">
        <div>© 中建港航局集团有限公司</div>
        <div class="version">v1.0.0</div>
      </div>
    </div>
  </div>
</template>

<script setup>
import { ref, reactive, onMounted, onUnmounted } from 'vue'
import { useRouter, useRoute } from 'vue-router'
import { ElMessage } from 'element-plus'
import { User, Lock, Message, Phone } from '@element-plus/icons-vue'
import { useAuthStore } from '../stores/auth'

const router = useRouter()
const route = useRoute()
const authStore = useAuthStore()

// 表单区折叠/展开
const showForm = ref(false)

function openForm(tab) {
  activeTab.value = tab
  showForm.value = true
}

function closeForm() {
  showForm.value = false
}

function openAbout() {
  window.open('/about', '_blank')
}

// 品牌区轮播：企业简介与文化
const carouselItems = [
  { title: '奋楫争先 · 同舟共赢', desc: '中建港航局同舟文化' },
  { title: '科技创新 · 技术先行', desc: '洋山精神' },
  { title: '同舟共智 · 智慧相通', desc: '港航智慧依托 AI 跨越时间相通' },
  { title: '集中智慧 · 攻坚克难', desc: '洋山港时期老港航人精神' },
  { title: '数字化 · 资产化', desc: '港航智慧不再封存于文件袋' },
  { title: '共享真智能 · 随时可用', desc: '所有港航人共享随时可用的真智能' },
  { title: '拥抱 AI · 奋楫争先', desc: '主动拥抱 AI 新时代的开拓意志' },
]
const carouselIndex = ref(0)
let carouselTimer = null

onMounted(() => {
  carouselTimer = setInterval(() => {
    carouselIndex.value = (carouselIndex.value + 1) % carouselItems.length
  }, 4000)

  // 从「了解系统」页跳转过来时，按 query.tab 自动唤出表单区
  const tab = route.query.tab
  if (tab === 'login' || tab === 'register') {
    openForm(tab)
  }
})

onUnmounted(() => {
  if (carouselTimer) clearInterval(carouselTimer)
})

const activeTab = ref('login')
const loading = ref(false)
const loginFormRef = ref(null)
const registerFormRef = ref(null)

// 登录表单
const loginForm = reactive({
  username: '',
  password: '',
})

const loginRules = {
  username: [{ required: true, message: '请输入用户名', trigger: 'blur' }],
  password: [{ required: true, message: '请输入密码', trigger: 'blur' }],
}

// 注册表单
const registerForm = reactive({
  username: '',
  email: '',
  phone: '',
  password: '',
  confirmPassword: '',
})

const validateConfirmPassword = (rule, value, callback) => {
  if (value !== registerForm.password) {
    callback(new Error('两次输入密码不一致'))
  } else {
    callback()
  }
}

const registerRules = {
  username: [
    { required: true, message: '请输入用户名', trigger: 'blur' },
    { min: 2, max: 50, message: '用户名长度2-50个字符', trigger: 'blur' },
  ],
  password: [
    { required: true, message: '请输入密码', trigger: 'blur' },
    { min: 6, message: '密码至少6位', trigger: 'blur' },
  ],
  confirmPassword: [
    { required: true, message: '请确认密码', trigger: 'blur' },
    { validator: validateConfirmPassword, trigger: 'blur' },
  ],
}

// 登录
async function handleLogin() {
  const valid = await loginFormRef.value?.validate().catch(() => false)
  if (!valid) return

  loading.value = true
  try {
    await authStore.login(loginForm.username, loginForm.password)
    ElMessage.success('登录成功')
    const redirect = route.query.redirect || '/'
    router.push(redirect)
  } catch (e) {
    ElMessage.error(e.response?.data?.detail || '登录失败')
  } finally {
    loading.value = false
  }
}

// 注册
async function handleRegister() {
  const valid = await registerFormRef.value?.validate().catch(() => false)
  if (!valid) return

  loading.value = true
  try {
    await authStore.register({
      username: registerForm.username,
      email: registerForm.email || undefined,
      phone: registerForm.phone || undefined,
      password: registerForm.password,
    })
    ElMessage.success('注册成功，账号需总管理员审批后方可登录')
    activeTab.value = 'login'
    loginForm.username = registerForm.username
    loginForm.password = ''
  } catch (e) {
    ElMessage.error(e.response?.data?.detail || '注册失败')
  } finally {
    loading.value = false
  }
}
</script>

<style scoped>
.login-page {
  display: flex;
  height: 100vh;
  width: 100vw;
  overflow: hidden;
  position: relative;
}

/* ===== 品牌区（默认全屏，打开表单后收缩到 65%） ===== */
.login-brand {
  flex: 1;
  position: relative;
  background: linear-gradient(135deg, #0c1d30 0%, #123049 14%, #0f2840 29%, #163a5c 43%, #143354 57%, #1f4e75 71%, #0f2840 86%, #0c1d30 100%);
  background-size: 200% 200%;
  animation: gradient-flow 15s ease infinite;
  display: flex;
  align-items: center;
  justify-content: center;
  overflow: hidden;
  transition: flex 0.35s ease;
  /* AIGC 背景图占位：生成后替换为
     background: linear-gradient(rgba(10,22,40,0.55), rgba(10,22,40,0.55)), url('/login-bg.jpg') center/cover; */
}

@keyframes gradient-flow {
  0% { background-position: 0% 50%; }
  50% { background-position: 100% 50%; }
  100% { background-position: 0% 50%; }
}

.login-calligraphy {
  position: absolute;
  top: 40px;
  left: 40px;
  width: 180px;
  height: auto;
  opacity: 0.45;
  pointer-events: none;
}

.brand-content {
  text-align: center;
  color: #fff;
  z-index: 1;
  padding: 0 40px;
}

.brand-logo-link {
  display: inline-block;
  cursor: pointer;
  margin-bottom: 28px;
  transition: transform 0.25s ease, opacity 0.25s ease;
}

.brand-logo-link:hover {
  transform: translateY(-2px);
  opacity: 0.88;
}

.brand-logo {
  height: 52px; /* 原86px × 60%（2026-08-21 甲方：logo与标题位置对调、大小互换） */
}

.brand-title {
  position: relative;
  font-size: 36px; /* 原28px +8（2026-08-21 甲方：logo与标题位置对调、大小互换） */
  font-weight: 600;
  color: #fff;
  letter-spacing: 3px;
  margin: 0 0 20px;
  cursor: pointer;
  transition: transform 0.25s ease, font-size 0.25s ease;
}

.brand-title:hover {
  transform: translateY(-3px);
  font-size: 38px;
}

.title-tip {
  position: absolute;
  bottom: 135%;
  left: 50%;
  transform: translateX(-50%) translateY(4px);
  background: rgba(0, 0, 0, 0.72);
  color: #fff;
  padding: 7px 14px;
  border-radius: 6px;
  font-size: 12px;
  font-weight: 400;
  letter-spacing: 1px;
  white-space: nowrap;
  opacity: 0;
  pointer-events: none;
  transition: opacity 0.25s ease, transform 0.25s ease;
}

.title-tip::after {
  content: '';
  position: absolute;
  top: 100%;
  left: 50%;
  transform: translateX(-50%);
  border: 5px solid transparent;
  border-top-color: rgba(0, 0, 0, 0.72);
}

.brand-title:hover .title-tip {
  opacity: 1;
  transform: translateX(-50%) translateY(0);
}

.brand-carousel {
  min-height: 72px;
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
}

.brand-slide {
  text-align: center;
}

.brand-slogan {
  position: relative;
  font-size: 18px;
  color: rgba(255, 255, 255, 0.9);
  letter-spacing: 4px;
  margin: 0;
  cursor: default;
}

.brand-tip {
  position: absolute;
  bottom: 135%;
  left: 50%;
  transform: translateX(-50%) translateY(9px);
  background: rgba(0, 0, 0, 0.72);
  color: #fff;
  padding: 7px 14px;
  border-radius: 6px;
  font-size: 12px;
  font-weight: 400;
  letter-spacing: 1px;
  white-space: nowrap;
  opacity: 0;
  pointer-events: none;
  transition: opacity 0.25s ease, transform 0.25s ease;
}

.brand-tip::after {
  content: '';
  position: absolute;
  top: 100%;
  left: 50%;
  transform: translateX(-50%);
  border: 5px solid transparent;
  border-top-color: rgba(0, 0, 0, 0.72);
}

.brand-slogan:hover .brand-tip {
  opacity: 1;
  transform: translateX(-50%) translateY(5px);
}

.carousel-dots {
  display: flex;
  gap: 8px;
  margin-top: 18px;
}

.carousel-dots .dot {
  width: 6px;
  height: 6px;
  border-radius: 50%;
  background: rgba(255, 255, 255, 0.3);
  transition: background 0.3s, width 0.3s;
}

.carousel-dots .dot.active {
  background: #fff;
  width: 18px;
  border-radius: 3px;
}

/* 轮播渐入渐出 */
.fade-enter-active,
.fade-leave-active {
  transition: opacity 0.6s ease;
}
.fade-enter-from,
.fade-leave-to {
  opacity: 0;
}

/* ===== 右上角导航 ===== */
.top-nav {
  position: absolute;
  top: 28px;
  right: 36px;
  display: flex;
  align-items: center;
  gap: 14px;
  z-index: 10;
}

.nav-item {
  color: rgba(255, 255, 255, 0.85);
  font-size: 14px;
  letter-spacing: 1px;
  cursor: pointer;
  transition: color 0.2s;
}

.nav-item:hover {
  color: #fff;
}

.nav-divider {
  width: 1px;
  height: 14px;
  background: rgba(255, 255, 255, 0.3);
}

/* ===== 表单区（右侧滑出，占 35%） ===== */
.login-form-side {
  width: 0;
  flex-shrink: 0;
  overflow: hidden;
  background: #f5f7fa;
  position: relative;
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  transition: width 0.35s ease;
}

.login-page.form-open .login-form-side {
  width: 35%;
}

.close-btn {
  position: absolute;
  top: 16px;
  right: 20px;
  width: 32px;
  height: 32px;
  border: none;
  background: transparent;
  color: #909399;
  font-size: 24px;
  line-height: 1;
  cursor: pointer;
  border-radius: 50%;
  transition: background 0.2s, color 0.2s;
}

.close-btn:hover {
  background: rgba(0, 0, 0, 0.06);
  color: #303133;
}

.login-header {
  text-align: center;
  margin-bottom: 20px;
  width: 100%;
  max-width: 360px;
}

.login-logo {
  height: 40px;
  margin-bottom: 14px;
}

.login-header h1 {
  margin: 0;
  font-size: 20px;
  color: #303133;
  letter-spacing: 1px;
}

.login-footer {
  text-align: center;
  margin-top: 20px;
  color: #c0c4cc;
  font-size: 12px;
}

.login-footer .version {
  margin-top: 4px;
  color: #c0c4cc;
  font-size: 11px;
}

.login-tabs {
  width: 100%;
  max-width: 360px;
}

.login-tabs :deep(.el-tabs__nav-wrap::after) {
  display: none;
}

.login-tabs :deep(.el-tabs__item) {
  font-size: 16px;
}

/* ===== 移动端适配（<768px 手机竖屏）===== */
@media (max-width: 768px) {
  .login-page.form-open .login-form-side { width: 100%; }  /* 表单占满屏 */
  .brand-title { font-size: 24px; letter-spacing: 2px; margin-bottom: 14px; }
  .login-calligraphy { width: 130px; }
  .brand-slogan { font-size: 14px; line-height: 1.8; }
  .top-nav { font-size: 14px; }
}
</style>
