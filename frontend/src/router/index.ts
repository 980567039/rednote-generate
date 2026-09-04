import { createRouter, createWebHistory } from 'vue-router'
import type { Pinia } from 'pinia'
import HomeView from '../views/HomeView.vue'
import OutlineView from '../views/OutlineView.vue'
import GenerateView from '../views/GenerateView.vue'
import ResultView from '../views/ResultView.vue'
import HistoryView from '../views/HistoryView.vue'
import SettingsView from '../views/SettingsView.vue'
import SeriesView from '../views/SeriesView.vue'
import SeriesListView from '../views/SeriesListView.vue'
import LoginView from '../views/LoginView.vue'
import RegisterView from '../views/RegisterView.vue'
import { safeNextPath } from '../api/auth'
import { useAuthStore } from '../stores/auth'

const router = createRouter({
  history: createWebHistory(import.meta.env.BASE_URL),
  routes: [
    {
      path: '/login',
      name: 'login',
      component: LoginView,
      meta: { public: true }
    },
    {
      path: '/register',
      name: 'register',
      component: RegisterView,
      meta: { public: true }
    },
    {
      path: '/',
      name: 'home',
      component: HomeView
    },
    {
      path: '/outline',
      name: 'outline',
      component: OutlineView
    },
    {
      path: '/generate',
      name: 'generate',
      component: GenerateView
    },
    {
      path: '/result',
      name: 'result',
      component: ResultView
    },
    {
      path: '/history',
      name: 'history',
      component: HistoryView
    },
    {
      path: '/history/:id',
      name: 'history-detail',
      component: HistoryView
    },
    {
      path: '/settings',
      name: 'settings',
      component: SettingsView
    },
    {
      path: '/series',
      name: 'series-list',
      component: SeriesListView
    },
    {
      path: '/series/:id',
      name: 'series-project',
      component: SeriesView
    }
  ]
})

export function installAuthGuard(pinia: Pinia) {
  router.beforeEach(async to => {
    const auth = useAuthStore(pinia)
    await auth.ensureInitialized()
    const publicRoute = to.meta.public === true

    if (publicRoute) {
      if (auth.authenticated) return safeNextPath(to.query.next)
      return true
    }
    if (auth.authenticated) return true
    return {
      name: 'login',
      query: { next: safeNextPath(to.fullPath) }
    }
  })
}

export default router
