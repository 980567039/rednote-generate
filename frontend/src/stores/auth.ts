import { computed, ref } from 'vue'
import { defineStore } from 'pinia'
import {
  getCurrentUser,
  login as loginRequest,
  logout as logoutRequest,
  register as registerRequest,
  type AuthUser,
} from '../api/auth'

export type AuthStatus = 'idle' | 'loading' | 'authenticated' | 'unauthenticated' | 'error'

export const useAuthStore = defineStore('auth', () => {
  const user = ref<AuthUser | null>(null)
  const status = ref<AuthStatus>('idle')
  const error = ref('')
  let refreshPromise: Promise<void> | null = null

  const authenticated = computed(() => status.value === 'authenticated' && Boolean(user.value))

  function markUnauthenticated() {
    user.value = null
    error.value = ''
    status.value = 'unauthenticated'
  }

  async function refresh() {
    if (refreshPromise) return refreshPromise
    refreshPromise = (async () => {
      status.value = 'loading'
      error.value = ''
      try {
        const nextUser = await getCurrentUser()
        if (!nextUser) {
          markUnauthenticated()
          return
        }
        user.value = nextUser
        status.value = 'authenticated'
      } catch (reason) {
        user.value = null
        status.value = 'error'
        error.value = reason instanceof Error ? reason.message : '暂时无法确认登录状态。'
      }
    })().finally(() => {
      refreshPromise = null
    })
    return refreshPromise
  }

  async function ensureInitialized() {
    if (status.value === 'idle') await refresh()
  }

  async function login(email: string, password: string) {
    const nextUser = await loginRequest({ email: email.trim(), password })
    user.value = nextUser
    error.value = ''
    status.value = 'authenticated'
  }

  async function register(displayName: string, email: string, password: string) {
    const nextUser = await registerRequest({
      displayName: displayName.trim(),
      email: email.trim(),
      password,
    })
    user.value = nextUser
    error.value = ''
    status.value = 'authenticated'
  }

  async function logout() {
    try {
      await logoutRequest()
    } finally {
      markUnauthenticated()
    }
  }

  return {
    user,
    status,
    error,
    authenticated,
    refresh,
    ensureInitialized,
    login,
    register,
    logout,
    markUnauthenticated,
  }
})
