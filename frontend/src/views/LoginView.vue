<template>
  <main class="auth-page">
    <div class="auth-wrap">
      <header class="auth-brand">
        <span class="auth-brand-mark" aria-hidden="true">R</span>
        <div>
          <strong>RedInk</strong>
          <span>把灵感变成可发布的内容</span>
        </div>
      </header>

      <section class="auth-card" aria-labelledby="login-title">
        <h1 id="login-title">欢迎回来</h1>
        <p class="auth-subtitle">登录后继续你的内容创作、系列管理和拼豆图纸设计。</p>

        <p v-if="auth.status === 'error' && auth.error" class="auth-warning" role="alert">
          {{ auth.error }}
        </p>

        <form class="auth-form" @submit.prevent="submit">
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
                maxlength="128"
                autocomplete="current-password"
              />
              <button type="button" :aria-label="showPassword ? '隐藏密码' : '显示密码'" @click="showPassword = !showPassword">
                {{ showPassword ? '隐藏' : '显示' }}
              </button>
            </span>
          </label>

          <p v-if="error" class="auth-error" role="alert">{{ error }}</p>

          <button class="auth-submit" type="submit" :disabled="submitting || !email.trim() || !password">
            {{ submitting ? '正在登录…' : '登录' }}
          </button>
        </form>

        <p class="auth-switch">
          还没有账号？
          <RouterLink :to="{ name: 'register', query: { next: nextPath } }">注册新账号</RouterLink>
        </p>
      </section>
    </div>
  </main>
</template>

<script setup lang="ts">
import { computed, ref } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { safeNextPath } from '../api/auth'
import { useAuthStore } from '../stores/auth'

const route = useRoute()
const router = useRouter()
const auth = useAuthStore()
const email = ref('')
const password = ref('')
const showPassword = ref(false)
const submitting = ref(false)
const error = ref('')
const nextPath = computed(() => safeNextPath(route.query.next))

async function submit() {
  submitting.value = true
  error.value = ''
  try {
    await auth.login(email.value, password.value)
    await router.replace(nextPath.value)
  } catch (reason) {
    error.value = reason instanceof Error ? reason.message : '登录失败，请稍后重试。'
  } finally {
    submitting.value = false
  }
}
</script>
