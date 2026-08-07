<template>
  <main class="auth-page">
    <div class="auth-wrap">
      <header class="auth-brand">
        <span class="auth-brand-mark" aria-hidden="true">R</span>
        <div>
          <strong>RedInk</strong>
          <span>创建你的内容创作账号</span>
        </div>
      </header>

      <section class="auth-card" aria-labelledby="register-title">
        <h1 id="register-title">开始创作</h1>
        <p class="auth-subtitle">首次使用请创建站点账号；完成注册后，注册入口会自动关闭。</p>

        <p v-if="statusWarning" class="auth-warning" role="alert">{{ statusWarning }}</p>
        <p v-if="registrationOpen === false" class="auth-warning" role="status">
          站点账号已经创建，请使用已有账号登录。
        </p>

        <form v-if="registrationOpen !== false" class="auth-form" @submit.prevent="submit">
          <label>
            <span>昵称</span>
            <input v-model="displayName" required maxlength="40" autocomplete="name" placeholder="怎么称呼你" />
          </label>
          <label>
            <span>邮箱</span>
            <input
              v-model="email"
              type="email"
              required
              maxlength="320"
              autocomplete="email"
              placeholder="creator@example.com"
            />
          </label>
          <label>
            <span>密码</span>
            <span class="auth-password-field">
              <input
                v-model="password"
                :type="showPassword ? 'text' : 'password'"
                required
                minlength="8"
                maxlength="128"
                autocomplete="new-password"
                placeholder="至少 8 个字符"
              />
              <button type="button" :aria-label="showPassword ? '隐藏密码' : '显示密码'" @click="showPassword = !showPassword">
                {{ showPassword ? '隐藏' : '显示' }}
              </button>
            </span>
          </label>
          <label>
            <span>确认密码</span>
            <input
              v-model="confirmation"
              :type="showPassword ? 'text' : 'password'"
              required
              minlength="8"
              maxlength="128"
              autocomplete="new-password"
            />
          </label>

          <p v-if="error" class="auth-error" role="alert">{{ error }}</p>

          <button
            class="auth-submit"
            type="submit"
            :disabled="registrationOpen === null || submitting || !displayName.trim() || !email.trim() || !password || !confirmation"
          >
            {{ submitting ? '正在创建账号…' : '注册并进入工作台' }}
          </button>
        </form>

        <p class="auth-switch">
          已有账号？
          <RouterLink :to="{ name: 'login', query: { next: nextPath } }">返回登录</RouterLink>
        </p>
      </section>
    </div>
  </main>
</template>

<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { getRegistrationStatus, safeNextPath } from '../api/auth'
import { useAuthStore } from '../stores/auth'

const route = useRoute()
const router = useRouter()
const auth = useAuthStore()
const displayName = ref('')
const email = ref('')
const password = ref('')
const confirmation = ref('')
const showPassword = ref(false)
const submitting = ref(false)
const error = ref('')
const statusWarning = ref('')
const registrationOpen = ref<boolean | null>(null)
const nextPath = computed(() => safeNextPath(route.query.next))

onMounted(async () => {
  try {
    registrationOpen.value = (await getRegistrationStatus()).registrationOpen
  } catch (reason) {
    registrationOpen.value = true
    statusWarning.value = reason instanceof Error ? reason.message : '暂时无法读取注册状态。'
  }
})

async function submit() {
  error.value = ''
  if (password.value.length < 8) {
    error.value = '密码至少需要 8 个字符。'
    return
  }
  if (password.value !== confirmation.value) {
    error.value = '两次输入的密码不一致。'
    return
  }
  submitting.value = true
  try {
    await auth.register(displayName.value, email.value, password.value)
    await router.replace(nextPath.value)
  } catch (reason) {
    error.value = reason instanceof Error ? reason.message : '注册失败，请稍后重试。'
  } finally {
    submitting.value = false
  }
}
</script>
