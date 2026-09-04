import { createApp } from 'vue'
import { createPinia } from 'pinia'
import App from './App.vue'
import router from './router'
import { installAuthGuard } from './router'
import { initializeTheme } from './composables/useTheme'
import { AUTH_UNAUTHORIZED_EVENT } from './api/client'
import { safeNextPath } from './api/auth'
import { useAuthStore } from './stores/auth'

// Styles
import './assets/css/variables.css'
import './assets/css/base.css'
import './assets/css/components.css'
import './assets/css/home.css'
import './assets/css/history.css'
import './assets/css/theme.css'
import './assets/css/auth.css'

// Apply persisted/system preference before Vue paints the application.
initializeTheme()

const app = createApp(App)
const pinia = createPinia()

app.use(pinia)
installAuthGuard(pinia)
app.use(router)

window.addEventListener(AUTH_UNAUTHORIZED_EVENT, () => {
  const auth = useAuthStore(pinia)
  auth.markUnauthenticated()
  if (router.currentRoute.value.meta.public !== true) {
    void router.replace({
      name: 'login',
      query: { next: safeNextPath(router.currentRoute.value.fullPath) }
    })
  }
})

app.mount('#app')
