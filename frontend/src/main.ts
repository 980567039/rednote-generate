import { createApp } from 'vue'
import { createPinia } from 'pinia'
import App from './App.vue'
import router from './router'
import { initializeTheme } from './composables/useTheme'

// Styles
import './assets/css/variables.css'
import './assets/css/base.css'
import './assets/css/components.css'
import './assets/css/home.css'
import './assets/css/history.css'
import './assets/css/theme.css'

// Apply persisted/system preference before Vue paints the application.
initializeTheme()

const app = createApp(App)

app.use(createPinia())
app.use(router)

app.mount('#app')
