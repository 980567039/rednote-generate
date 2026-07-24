import { computed, readonly, ref } from 'vue'

export type ThemePreference = 'system' | 'light' | 'dark'

const STORAGE_KEY = 'ai-content-theme-preference'
const preference = ref<ThemePreference>('system')
let mediaQuery: MediaQueryList | undefined
let initialized = false

function isThemePreference(value: string | null): value is ThemePreference {
  return value === 'system' || value === 'light' || value === 'dark'
}

function readPreference(): ThemePreference {
  try {
    const stored = window.localStorage.getItem(STORAGE_KEY)
    return isThemePreference(stored) ? stored : 'system'
  } catch {
    return 'system'
  }
}

function resolveTheme(value: ThemePreference): 'light' | 'dark' {
  if (value !== 'system') return value
  return mediaQuery?.matches ? 'dark' : 'light'
}

function applyTheme(value: ThemePreference) {
  const resolved = resolveTheme(value)
  const root = document.documentElement
  root.dataset.theme = resolved
  root.style.colorScheme = resolved
}

function handleSystemThemeChange() {
  if (preference.value === 'system') applyTheme('system')
}

/** Initialize the UI theme before the app mounts. Safe to call more than once. */
export function initializeTheme() {
  if (initialized || typeof window === 'undefined') return

  initialized = true
  mediaQuery = window.matchMedia('(prefers-color-scheme: dark)')
  preference.value = readPreference()
  applyTheme(preference.value)
  mediaQuery.addEventListener?.('change', handleSystemThemeChange)
}

export function useTheme() {
  const resolvedTheme = computed(() => resolveTheme(preference.value))

  function setTheme(value: ThemePreference) {
    preference.value = value
    try {
      window.localStorage.setItem(STORAGE_KEY, value)
    } catch {
      // Private browsing or a full storage quota should not prevent changing theme.
    }
    applyTheme(value)
  }

  return { preference: readonly(preference), resolvedTheme, setTheme }
}
