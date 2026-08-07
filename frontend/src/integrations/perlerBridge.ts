import { isValidPerlerSettings, type PerlerPatternSettings } from './perlerSettings'

const MANUAL_CHANNEL = 'redink-perler'
const AUTO_CHANNEL = 'redink-perler-auto'
const VERSION = 1
const MAX_SOURCE_BYTES = 25 * 1024 * 1024
const MAX_PATTERN_BYTES = 20 * 1024 * 1024
const CONNECTION_TIMEOUT_MS = 15 * 1000
const HANDOFF_TIMEOUT_MS = 5 * 60 * 1000
const ALLOWED_SOURCE_TYPES = new Set(['image/png', 'image/jpeg', 'image/webp'])
const AUTO_PROGRESS_STAGES = new Set<PerlerAutoProgressStage>([
  'prepare',
  'sample',
  'select',
  'map',
  'cleanup',
  'background',
  'render',
])

export interface PerlerPatternMetadata {
  columns: number
  rows: number
  usedColors: number
}

export interface PerlerPatternResult {
  requestId: string
  pattern: Blob
  metadata: PerlerPatternMetadata
}

export type PerlerAutoProgressStage =
  | 'prepare'
  | 'sample'
  | 'select'
  | 'map'
  | 'cleanup'
  | 'background'
  | 'render'

export interface PerlerProgressUpdate {
  stage: 'connect' | PerlerAutoProgressStage
  completed: number
  total: number
}

export interface PerlerAutoJob {
  requestId: string
  result: Promise<PerlerPatternResult>
  cancel: () => void
}

interface PerlerMessage {
  channel: string
  version: number
  type: string
  requestId?: string
  pattern?: ArrayBuffer
  mimeType?: string
  metadata?: PerlerPatternMetadata
  stage?: unknown
  completed?: unknown
  total?: unknown
  message?: unknown
}

export class PerlerBridgeCancelledError extends Error {
  constructor() {
    super('已取消生成拼豆图纸。')
    this.name = 'PerlerBridgeCancelledError'
  }
}

function configuredPerlerOrigin(): string | null {
  const configured = import.meta.env.VITE_PERLER_ORIGIN?.trim() || 'http://localhost:5174'
  try {
    const parsed = new URL(configured)
    if (
      !['http:', 'https:'].includes(parsed.protocol)
      || parsed.username
      || parsed.password
      || parsed.pathname !== '/'
      || parsed.search
      || parsed.hash
    ) return null
    return parsed.origin
  } catch {
    return null
  }
}

function validMessage(value: unknown, channel: string): value is PerlerMessage {
  if (!value || typeof value !== 'object') return false
  const message = value as Partial<PerlerMessage>
  return message.channel === channel && message.version === VERSION && typeof message.type === 'string'
}

function validMetadata(value: unknown): value is PerlerPatternMetadata {
  if (!value || typeof value !== 'object') return false
  const metadata = value as Partial<PerlerPatternMetadata>
  return (
    Number.isInteger(metadata.columns) && metadata.columns! >= 1 && metadata.columns! <= 300
    && Number.isInteger(metadata.rows) && metadata.rows! >= 1 && metadata.rows! <= 300
    && Number.isInteger(metadata.usedColors) && metadata.usedColors! >= 1 && metadata.usedColors! <= 64
  )
}

function validProgress(message: PerlerMessage): message is PerlerMessage & {
  stage: PerlerAutoProgressStage
  completed: number
  total: number
} {
  return (
    typeof message.stage === 'string'
    && AUTO_PROGRESS_STAGES.has(message.stage as PerlerAutoProgressStage)
    && Number.isInteger(message.completed)
    && (message.completed as number) >= 0
    && Number.isInteger(message.total)
    && (message.total as number) >= 1
    && (message.completed as number) <= (message.total as number)
  )
}

function randomRequestId(): string {
  return typeof crypto.randomUUID === 'function'
    ? crypto.randomUUID()
    : `${Date.now().toString(36)}-${Math.random().toString(36).slice(2)}`
}

function validateBridgeInput(input: {
  recordId: string
  imageUrl: string
  imageIndex: number
  settings?: PerlerPatternSettings
}) {
  if (!input.recordId.trim()) throw new Error('缺少历史记录 ID，无法生成拼豆图纸。')
  if (!input.imageUrl.trim()) throw new Error('缺少原图地址，无法生成拼豆图纸。')
  if (!Number.isInteger(input.imageIndex) || input.imageIndex < 0) throw new Error('原图页码无效。')
  if (input.settings && !isValidPerlerSettings(input.settings)) throw new Error('拼豆图纸规格无效。')
}

async function fetchSourceImage(imageUrl: string, signal?: AbortSignal): Promise<{
  bytes: ArrayBuffer
  mimeType: string
}> {
  const sourceUrl = new URL(imageUrl, window.location.origin)
  const response = await fetch(sourceUrl.toString(), { credentials: 'same-origin', signal })
  if (!response.ok) throw new Error(`读取原图失败：HTTP ${response.status}`)
  const bytes = await response.arrayBuffer()
  if (bytes.byteLength === 0 || bytes.byteLength > MAX_SOURCE_BYTES) throw new Error('原图为空或超过 25MB。')
  const mimeType = (response.headers.get('content-type') || 'image/png').split(';', 1)[0].toLowerCase()
  if (!ALLOWED_SOURCE_TYPES.has(mimeType)) throw new Error('原图格式不受支持，仅支持 PNG、JPEG 和 WebP。')
  return { bytes, mimeType }
}

function patternResultFromMessage(message: PerlerMessage, requestId: string): PerlerPatternResult {
  if (
    message.mimeType !== 'image/png'
    || !(message.pattern instanceof ArrayBuffer)
    || message.pattern.byteLength === 0
    || message.pattern.byteLength > MAX_PATTERN_BYTES
  ) throw new Error('Perler 回传的图纸不是有效 PNG，或文件超过 20MB。')
  if (!validMetadata(message.metadata)) throw new Error('Perler 回传的图纸元数据无效。')
  return {
    requestId,
    pattern: new Blob([message.pattern], { type: 'image/png' }),
    metadata: message.metadata,
  }
}

export async function generatePatternWithPerler(input: {
  recordId: string
  imageUrl: string
  imageIndex: number
  fileName?: string
  settings?: PerlerPatternSettings
}): Promise<PerlerPatternResult> {
  validateBridgeInput(input)
  const origin = configuredPerlerOrigin()
  if (!origin) throw new Error('Perler 地址配置无效，必须填写不带路径的 HTTP(S) origin。')
  const requestId = randomRequestId()
  const perlerUrl = new URL('/', origin)
  perlerUrl.searchParams.set('handoff', requestId)
  const popup = window.open(perlerUrl.toString(), '_blank', 'width=1440,height=1000')
  if (!popup) throw new Error('浏览器阻止了 Perler 窗口，请允许弹出窗口后重试。')

  return new Promise<PerlerPatternResult>((resolve, reject) => {
    let settled = false
    let ready = false
    let sourceBytes: ArrayBuffer | null = null
    let mimeType = 'image/png'
    let timeout = 0
    const cleanup = () => {
      window.removeEventListener('message', onMessage)
      window.clearTimeout(timeout)
    }
    const finishError = (reason: unknown) => {
      if (settled) return
      settled = true
      cleanup()
      reject(reason instanceof Error ? reason : new Error(String(reason)))
    }
    const sendSource = () => {
      if (!ready || settled || !sourceBytes) return
      try {
        const transfer = sourceBytes
        sourceBytes = null
        popup.postMessage(
          {
            channel: MANUAL_CHANNEL,
            version: VERSION,
            type: 'IMPORT_IMAGE',
            requestId,
            context: {
              recordId: input.recordId,
              imageIndex: input.imageIndex,
              fileName: input.fileName || `redink-page-${input.imageIndex + 1}.png`,
            },
            image: transfer,
            mimeType,
            ...(input.settings ? { settings: { ...input.settings } } : {}),
          },
          origin,
          [transfer],
        )
      } catch (reason) {
        finishError(reason)
      }
    }
    const onMessage = (event: MessageEvent<unknown>) => {
      if (event.source !== popup || event.origin !== origin || !validMessage(event.data, MANUAL_CHANNEL)) return
      const message = event.data
      if (message.requestId !== requestId) return
      if (message.type === 'PERLER_READY') {
        ready = true
        sendSource()
        return
      }
      if (message.type === 'PERLER_ERROR') {
        finishError(new Error(typeof message.message === 'string' && message.message ? message.message : 'Perler 处理失败。'))
        return
      }
      if (message.type !== 'PATTERN_READY') return
      try {
        const result = patternResultFromMessage(message, requestId)
        settled = true
        cleanup()
        resolve(result)
      } catch (reason) {
        finishError(reason)
      }
    }
    window.addEventListener('message', onMessage)
    timeout = window.setTimeout(() => finishError(new Error('Perler 交接超时，请确认窗口仍然打开。')), HANDOFF_TIMEOUT_MS)
    void fetchSourceImage(input.imageUrl)
      .then(source => {
        sourceBytes = source.bytes
        mimeType = source.mimeType
        sendSource()
      })
      .catch(finishError)
  })
}

export function generatePatternAutomatically(input: {
  recordId: string
  imageUrl: string
  imageIndex: number
  fileName?: string
  settings: PerlerPatternSettings
  onReady?: () => void
  onProgress?: (progress: PerlerProgressUpdate) => void
}): PerlerAutoJob {
  validateBridgeInput(input)
  const origin = configuredPerlerOrigin()
  if (!origin) throw new Error('Perler 地址配置无效，必须填写不带路径的 HTTP(S) origin。')
  const requestId = randomRequestId()
  const perlerUrl = new URL('/', origin)
  perlerUrl.searchParams.set('mode', 'auto')
  perlerUrl.searchParams.set('handoff', requestId)

  const iframe = document.createElement('iframe')
  iframe.title = 'Perler 后台图纸生成器'
  iframe.setAttribute('aria-hidden', 'true')
  Object.assign(iframe.style, {
    position: 'fixed',
    left: '-10000px',
    top: '-10000px',
    width: '1px',
    height: '1px',
    border: '0',
    opacity: '0',
    pointerEvents: 'none',
  })
  document.body.appendChild(iframe)
  const perlerWindow = iframe.contentWindow
  if (!perlerWindow) {
    iframe.remove()
    throw new Error('无法创建 Perler 后台生成窗口。')
  }

  const abortController = new AbortController()
  let cancel: () => void = () => undefined
  const result = new Promise<PerlerPatternResult>((resolve, reject) => {
    let settled = false
    let ready = false
    let sent = false
    let sourceBytes: ArrayBuffer | null = null
    let sourceMimeType = 'image/png'
    let connectionTimeout = 0
    let totalTimeout = 0

    const cleanup = () => {
      window.removeEventListener('message', onMessage)
      window.clearTimeout(connectionTimeout)
      window.clearTimeout(totalTimeout)
      abortController.abort()
      iframe.remove()
      sourceBytes = null
    }
    const finishError = (reason: unknown) => {
      if (settled) return
      settled = true
      cleanup()
      reject(reason instanceof Error ? reason : new Error(String(reason)))
    }
    const finishSuccess = (pattern: PerlerPatternResult) => {
      if (settled) return
      settled = true
      cleanup()
      resolve(pattern)
    }
    const sendSource = () => {
      if (!ready || sent || settled || !sourceBytes) return
      try {
        sent = true
        const transfer = sourceBytes
        sourceBytes = null
        perlerWindow.postMessage(
          {
            channel: AUTO_CHANNEL,
            version: VERSION,
            type: 'AUTO_GENERATE',
            requestId,
            context: {
              recordId: input.recordId,
              imageIndex: input.imageIndex,
              fileName: input.fileName || `redink-page-${input.imageIndex + 1}.png`,
            },
            image: transfer,
            mimeType: sourceMimeType,
            settings: {
              ...input.settings,
              removeBorderBackground: true,
            },
          },
          origin,
          [transfer],
        )
      } catch (reason) {
        finishError(reason)
      }
    }
    const onMessage = (event: MessageEvent<unknown>) => {
      if (event.source !== perlerWindow || event.origin !== origin || !validMessage(event.data, AUTO_CHANNEL)) return
      const message = event.data
      if (message.requestId !== requestId) return
      if (message.type === 'AUTO_READY') {
        if (ready) return
        ready = true
        window.clearTimeout(connectionTimeout)
        input.onReady?.()
        sendSource()
        return
      }
      if (message.type === 'AUTO_ERROR') {
        if (typeof message.message !== 'string' || !message.message.trim()) {
          finishError(new Error('Perler 回传的错误信息无效。'))
          return
        }
        finishError(new Error(message.message))
        return
      }
      if (message.type === 'AUTO_PROGRESS') {
        if (!validProgress(message)) {
          finishError(new Error('Perler 回传的生成进度无效。'))
          return
        }
        input.onProgress?.({
          stage: message.stage,
          completed: message.completed,
          total: message.total,
        })
        return
      }
      if (message.type !== 'AUTO_PATTERN_READY') return
      try {
        finishSuccess(patternResultFromMessage(message, requestId))
      } catch (reason) {
        finishError(reason)
      }
    }

    cancel = () => finishError(new PerlerBridgeCancelledError())
    window.addEventListener('message', onMessage)
    iframe.src = perlerUrl.toString()
    connectionTimeout = window.setTimeout(
      () => finishError(new Error('连接 Perler 超时，请确认 Perler 已启动且允许 RedInk 嵌入。')),
      CONNECTION_TIMEOUT_MS,
    )
    totalTimeout = window.setTimeout(
      () => finishError(new Error('生成拼豆图纸超时，请重试或进入 Perler 手动生成。')),
      HANDOFF_TIMEOUT_MS,
    )
    void fetchSourceImage(input.imageUrl, abortController.signal)
      .then(source => {
        sourceBytes = source.bytes
        sourceMimeType = source.mimeType
        sendSource()
      })
      .catch(reason => {
        if (reason instanceof DOMException && reason.name === 'AbortError') return
        finishError(reason)
      })
  })

  return { requestId, result, cancel: () => cancel() }
}
