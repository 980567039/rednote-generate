import {
  API_BASE_URL,
  apiFetch,
  responseError,
} from './client'

export interface AuthUser {
  id: string
  email: string
  displayName: string
  role?: string
}

export interface RegistrationStatus {
  registrationOpen: boolean
}

function normalizeUser(value: unknown): AuthUser {
  if (!value || typeof value !== 'object' || Array.isArray(value)) {
    throw new Error('登录状态返回格式不正确。')
  }
  const item = value as Record<string, unknown>
  if (
    typeof item.id !== 'string'
    || typeof item.email !== 'string'
    || typeof item.displayName !== 'string'
  ) {
    throw new Error('登录状态返回格式不正确。')
  }
  return {
    id: item.id,
    email: item.email,
    displayName: item.displayName,
    ...(typeof item.role === 'string' ? { role: item.role } : {}),
  }
}

async function authResponse(response: Response, fallback: string): Promise<AuthUser> {
  if (!response.ok) throw await responseError(response, fallback)
  const body = await response.json() as { user?: unknown }
  return normalizeUser(body.user)
}

export async function getCurrentUser(): Promise<AuthUser | null> {
  const response = await apiFetch(
    `${API_BASE_URL}/auth/me`,
    { cache: 'no-store' },
    { handleUnauthorized: false }
  )
  if (response.status === 401) return null
  return authResponse(response, '暂时无法确认登录状态。')
}

export async function getRegistrationStatus(): Promise<RegistrationStatus> {
  const response = await apiFetch(
    `${API_BASE_URL}/auth/status`,
    { cache: 'no-store' },
    { handleUnauthorized: false }
  )
  if (!response.ok) throw await responseError(response, '暂时无法读取注册状态。')
  const body = await response.json() as { status?: unknown }
  if (!body.status || typeof body.status !== 'object') {
    throw new Error('注册状态返回格式不正确。')
  }
  const status = body.status as Record<string, unknown>
  return { registrationOpen: status.registrationOpen !== false }
}

export async function login(input: { email: string; password: string }): Promise<AuthUser> {
  const response = await apiFetch(
    `${API_BASE_URL}/auth/login`,
    {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(input),
    },
    { handleUnauthorized: false }
  )
  return authResponse(response, response.status === 401 ? '邮箱或密码不正确。' : '登录失败，请稍后重试。')
}

export async function register(input: {
  displayName: string
  email: string
  password: string
}): Promise<AuthUser> {
  const response = await apiFetch(
    `${API_BASE_URL}/auth/register`,
    {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(input),
    },
    { handleUnauthorized: false }
  )
  return authResponse(response, '注册失败，请稍后重试。')
}

export async function logout(): Promise<void> {
  const response = await apiFetch(
    `${API_BASE_URL}/auth/logout`,
    { method: 'POST' },
    { handleUnauthorized: false }
  )
  if (!response.ok && response.status !== 401) {
    throw await responseError(response, '退出登录失败，请稍后重试。')
  }
}

export function safeNextPath(value: unknown, fallback = '/'): string {
  if (typeof value !== 'string' || !value.startsWith('/') || value.startsWith('//') || value.startsWith('/\\')) {
    return fallback
  }
  try {
    const base = new URL('https://redink.local')
    const destination = new URL(value, base)
    if (destination.origin !== base.origin) return fallback
    if (['/login', '/register'].includes(destination.pathname)) return fallback
    return `${destination.pathname}${destination.search}${destination.hash}`
  } catch {
    return fallback
  }
}
