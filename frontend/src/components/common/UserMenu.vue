<template>
  <section v-if="auth.user" class="user-menu">
    <span class="user-avatar" aria-hidden="true">{{ initial }}</span>
    <div class="user-summary">
      <strong :title="auth.user.displayName">{{ auth.user.displayName }}</strong>
      <span :title="auth.user.email">{{ auth.user.email }}</span>
    </div>
    <button type="button" :disabled="loggingOut" @click="handleLogout">
      {{ loggingOut ? '退出中…' : '退出' }}
    </button>
    <p v-if="error" role="alert">{{ error }}</p>
  </section>
</template>

<script setup lang="ts">
import { computed, ref } from 'vue'
import { useRouter } from 'vue-router'
import { useAuthStore } from '../../stores/auth'

const router = useRouter()
const auth = useAuthStore()
const loggingOut = ref(false)
const error = ref('')
const initial = computed(() => Array.from(auth.user?.displayName.trim() || auth.user?.email || 'R')[0]?.toUpperCase() || 'R')

async function handleLogout() {
  loggingOut.value = true
  error.value = ''
  try {
    await auth.logout()
    await router.replace({ name: 'login' })
  } catch (reason) {
    error.value = reason instanceof Error ? reason.message : '退出失败，请稍后重试。'
  } finally {
    loggingOut.value = false
  }
}
</script>
