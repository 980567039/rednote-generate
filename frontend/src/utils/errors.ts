import axios from 'axios'

export interface AppError {
  type: string
  code: string
  title: string
  detail: string
  suggestion: string
  status: number
  retryable: boolean
  diagnostics?: Record<string, any>
}

export type ErrorLike = AppError | string | Error | unknown

export function normalizeApiError(error: ErrorLike, fallbackTitle = '操作失败'): AppError {
  if (isAppError(error)) return error

  if (axios.isAxiosError(error)) {
    const data = error.response?.data
    if (isAppError(data?.error)) return data.error
    if (typeof data?.error === 'string') {
      return legacyMessageToError(data.error, data.error_message || fallbackTitle, error.response?.status)
    }
    if (typeof data?.error_message === 'string') {
      return legacyMessageToError(data.error_message, fallbackTitle, error.response?.status)
    }
    if (!error.response) {
      return legacyMessageToError(
        error.message || '网络连接失败',
        '网络连接失败',
        0,
        '请确认后端服务已启动，并检查浏览器网络连接。'
      )
    }
    return legacyMessageToError(error.message, fallbackTitle, error.response.status)
  }

  const maybeData = error as any
  if (isAppError(maybeData?.error)) return maybeData.error
  if (typeof maybeData?.error === 'string') {
    return legacyMessageToError(maybeData.error, maybeData.error_message || fallbackTitle, maybeData.status)
  }
  if (typeof maybeData?.message === 'string') {
    return legacyMessageToError(maybeData.message, fallbackTitle, maybeData.status)
  }
  if (typeof error === 'string') {
    return legacyMessageToError(error, fallbackTitle)
  }

  return legacyMessageToError('请稍后重试；如果持续失败，请复制诊断信息反馈。', fallbackTitle)
}

export function formatErrorMessage(error: ErrorLike, fallbackTitle = '操作失败'): string {
  const appError = normalizeApiError(error, fallbackTitle)
  return `${appError.title}：${appError.suggestion || appError.detail}`
}

export function diagnosticsText(error: AppError): string {
  const payload = {
    code: error.code,
    title: error.title,
    detail: error.detail,
    suggestion: error.suggestion,
    status: error.status,
    retryable: error.retryable,
    diagnostics: error.diagnostics || {}
  }
  return JSON.stringify(payload, null, 2)
}

function isAppError(value: any): value is AppError {
  return !!value
    && typeof value === 'object'
    && typeof value.code === 'string'
    && typeof value.title === 'string'
    && typeof value.detail === 'string'
}

function legacyMessageToError(
  message: string,
  fallbackTitle = '操作失败',
  status = 500,
  suggestion?: string
): AppError {
  const clean = message || '发生未知错误'
  const firstLine = clean.split('\n').map(line => line.trim()).find(Boolean) || fallbackTitle

  return {
    type: `https://app.local/errors/${inferCode(clean).toLowerCase().replace(/_/g, '-')}`,
    code: inferCode(clean),
    title: inferTitle(clean, fallbackTitle),
    detail: firstLine,
    suggestion: suggestion || inferSuggestion(clean),
    status: status || 500,
    retryable: inferRetryable(clean),
    diagnostics: {
      raw: clean
    }
  }
}

function inferCode(message: string): string {
  const text = message.toLowerCase()
  if (text.includes('proxyerror') || (text.includes('connection refused') && text.includes('127.0.0.1'))) return 'PROXY_UNAVAILABLE'
  if (text.includes('ssleoferror') || text.includes('unexpected_eof') || text.includes('198.18.')) return 'NETWORK_FAKE_IP_TLS'
  if (message.includes('不支持 /v1/chat/completions')) return 'MODEL_ENDPOINT_MISMATCH'
  if (text.includes('405') || text.includes('method not allowed') || text.includes('not allowed')) return 'ENDPOINT_METHOD_MISMATCH'
  if (text.includes('401') || text.includes('403') || text.includes('unauthorized') || text.includes('forbidden')) return 'AUTH_OR_PERMISSION'
  if (text.includes('429') || text.includes('rate') || message.includes('配额') || message.includes('限流')) return 'RATE_LIMITED'
  if (text.includes('timeout') || message.includes('超时')) return 'NETWORK_TIMEOUT'
  if (message.includes('不存在') || text.includes('not found')) return 'RESOURCE_NOT_FOUND'
  return 'UNKNOWN_ERROR'
}

function inferTitle(message: string, fallbackTitle: string): string {
  const code = inferCode(message)
  const titles: Record<string, string> = {
    PROXY_UNAVAILABLE: '本机代理不可用',
    NETWORK_FAKE_IP_TLS: '网络代理连接异常',
    MODEL_ENDPOINT_MISMATCH: '模型与接口不匹配',
    ENDPOINT_METHOD_MISMATCH: '接口路径或请求方法不匹配',
    AUTH_OR_PERMISSION: 'API Key 或权限不可用',
    RATE_LIMITED: '上游限流或配额不足',
    NETWORK_TIMEOUT: '网络请求超时',
    RESOURCE_NOT_FOUND: '资源不存在',
    UNKNOWN_ERROR: fallbackTitle
  }
  return titles[code] || fallbackTitle
}

function inferSuggestion(message: string): string {
  const code = inferCode(message)
  const suggestions: Record<string, string> = {
    PROXY_UNAVAILABLE: '请确认代理客户端已开启，且 HTTP/HTTPS 代理端口正在监听。',
    NETWORK_FAKE_IP_TLS: '请确认代理客户端已开启，或关闭 Fake-IP DNS 后重试。',
    MODEL_ENDPOINT_MISMATCH: '请在设置中换成支持当前接口的模型，或调整服务商 endpoint_type。',
    ENDPOINT_METHOD_MISMATCH: '请重启后端服务以加载最新路由；如果仍失败，再检查接口路径和请求方法。',
    AUTH_OR_PERMISSION: '请检查 API Key、模型访问权限、账户余额和服务商配置。',
    RATE_LIMITED: '请稍后重试，或降低并发/检查账户配额。',
    NETWORK_TIMEOUT: '请检查网络、代理和服务商状态后重试。',
    RESOURCE_NOT_FOUND: '请返回列表刷新后重试。',
    UNKNOWN_ERROR: '请稍后重试；如果持续失败，请复制诊断信息反馈。'
  }
  return suggestions[code] || suggestions.UNKNOWN_ERROR
}

function inferRetryable(message: string): boolean {
  const code = inferCode(message)
  return ['PROXY_UNAVAILABLE', 'NETWORK_FAKE_IP_TLS', 'RATE_LIMITED', 'NETWORK_TIMEOUT', 'UNKNOWN_ERROR'].includes(code)
}
