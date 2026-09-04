export interface PerlerPatternSettings {
  columns: number
  rows: number
  maxUsedColors: number
}

export const PERLER_SETTINGS_STORAGE_KEY = 'redink:perler-auto-settings:v1'

export const DEFAULT_PERLER_SETTINGS: Readonly<PerlerPatternSettings> = Object.freeze({
  columns: 104,
  rows: 104,
  maxUsedColors: 40,
})

function isIntegerInRange(value: unknown, minimum: number, maximum: number): value is number {
  return Number.isInteger(value) && (value as number) >= minimum && (value as number) <= maximum
}

export function isValidPerlerSettings(value: unknown): value is PerlerPatternSettings {
  if (!value || typeof value !== 'object') return false
  const settings = value as Partial<PerlerPatternSettings>
  return (
    isIntegerInRange(settings.columns, 1, 300)
    && isIntegerInRange(settings.rows, 1, 300)
    && isIntegerInRange(settings.maxUsedColors, 2, 64)
  )
}

function defaultSettings(): PerlerPatternSettings {
  return { ...DEFAULT_PERLER_SETTINGS }
}

export function loadPerlerSettings(storage?: Pick<Storage, 'getItem'>): PerlerPatternSettings {
  try {
    const target = storage ?? window.localStorage
    const saved = target.getItem(PERLER_SETTINGS_STORAGE_KEY)
    if (!saved) return defaultSettings()
    const parsed: unknown = JSON.parse(saved)
    return isValidPerlerSettings(parsed) ? { ...parsed } : defaultSettings()
  } catch {
    return defaultSettings()
  }
}

export function savePerlerSettings(
  settings: PerlerPatternSettings,
  storage?: Pick<Storage, 'setItem'>,
): boolean {
  if (!isValidPerlerSettings(settings)) return false
  try {
    const target = storage ?? window.localStorage
    target.setItem(PERLER_SETTINGS_STORAGE_KEY, JSON.stringify(settings))
    return true
  } catch {
    return false
  }
}
