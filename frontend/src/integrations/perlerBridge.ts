const CHANNEL = 'redink-perler'
const VERSION = 1
const MAX_SOURCE_BYTES = 25 * 1024 * 1024
const MAX_PATTERN_BYTES = 20 * 1024 * 1024
const HANDOFF_TIMEOUT_MS = 5 * 60 * 1000
const ALLOWED_SOURCE_TYPES = new Set(['image/png', 'image/jpeg', 'image/webp'])

export interface PerlerPatternResult {
  requestId: string
  pattern: Blob
  metadata: {
    columns: number
    rows: number
    usedColors: number
  }
}

interface PerlerMessage {
  channel: typeof CHANNEL
  version: typeof VERSION
  type: string
  requestId?: string
  pattern?: ArrayBuffer
  mimeType?: string
  metadata?: PerlerPatternResult['metadata']
  message?: string
}

function configuredPerlerOrigin(): string | null {
  const configured = import.meta.env.VITE_PERLER_ORIGIN?.trim() || 'http://localhost:5174'
  try {
    const parsed = new URL(configured)
    if (
      !['http:', 'https:'].includes(parsed.protocol) ||
      parsed.username ||
      parsed.password ||
      parsed.pathname !== '/' ||
      parsed.search ||
      parsed.hash
    ) return null
    return parsed.origin
  } catch {
    return null
  }
}

function validMessage(value: unknown): value is PerlerMessage {
  if (!value || typeof value !== 'object') return false
  const message = value as Partial<PerlerMessage>
  return message.channel === CHANNEL && message.version === VERSION && typeof message.type === 'string'
}

function validMetadata(value: unknown): value is PerlerPatternResult['metadata'] {
  if (!value || typeof value !== 'object') return false
  const metadata = value as Partial<PerlerPatternResult['metadata']>
  return (
    Number.isInteger(metadata.columns) && metadata.columns! >= 1 && metadata.columns! <= 300 &&
    Number.isInteger(metadata.rows) && metadata.rows! >= 1 && metadata.rows! <= 300 &&
    Number.isInteger(metadata.usedColors) && metadata.usedColors! >= 1 && metadata.usedColors! <= 64
  )
}

function randomRequestId(): string {
  return typeof crypto.randomUUID === 'function'
    ? crypto.randomUUID()
    : `${Date.now().toString(36)}-${Math.random().toString(36).slice(2)}`
}

export async function generatePatternWithPerler(input: {
  recordId: string
  imageUrl: string
  imageIndex: number
  fileName?: string
}): Promise<PerlerPatternResult> {
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
      if (!settled && !popup.closed) popup.close()
    }
    const finishError = (reason: unknown) => {
      if (settled) return
      settled = true
      cleanup()
      reject(reason instanceof Error ? reason : new Error(String(reason)))
    }
    const sendSource = () => {
      if (!ready || settled || !sourceBytes) return
      popup.postMessage(
        {
          channel: CHANNEL,
          version: VERSION,
          type: 'IMPORT_IMAGE',
          requestId,
          context: {
            recordId: input.recordId,
            imageIndex: input.imageIndex,
            fileName: input.fileName || `redink-page-${input.imageIndex + 1}.png`,
          },
          image: sourceBytes,
          mimeType,
        },
        origin,
        [sourceBytes],
      )
    }
    const onMessage = (event: MessageEvent<unknown>) => {
      if (event.source !== popup || event.origin !== origin || !validMessage(event.data)) return
      const message = event.data
      if (message.requestId !== requestId) return
      if (message.type === 'PERLER_READY') {
        ready = true
        sendSource()
        return
      }
      if (message.type === 'PERLER_ERROR') {
        finishError(new Error(message.message || 'Perler 处理失败。'))
        return
      }
      if (message.type !== 'PATTERN_READY') return
      if (message.mimeType !== 'image/png' || !(message.pattern instanceof ArrayBuffer) || message.pattern.byteLength === 0 || message.pattern.byteLength > MAX_PATTERN_BYTES) {
        finishError(new Error('Perler 回传的图纸不是有效 PNG。'))
        return
      }
      if (!validMetadata(message.metadata)) {
        finishError(new Error('Perler 回传的图纸元数据无效。'))
        return
      }
      settled = true
      cleanup()
      resolve({ requestId, pattern: new Blob([message.pattern], { type: 'image/png' }), metadata: message.metadata })
    }
    window.addEventListener('message', onMessage)
    timeout = window.setTimeout(() => finishError(new Error('Perler 交接超时，请确认窗口仍然打开。')), HANDOFF_TIMEOUT_MS)
    void fetch(new URL(input.imageUrl, window.location.origin).toString(), { credentials: 'same-origin' })
      .then(async response => {
        if (!response.ok) throw new Error(`读取原图失败：HTTP ${response.status}`)
        const bytes = await response.arrayBuffer()
        if (bytes.byteLength === 0 || bytes.byteLength > MAX_SOURCE_BYTES) throw new Error('原图为空或超过 25MB。')
        const detectedMime = (response.headers.get('content-type') || 'image/png').split(';', 1)[0].toLowerCase()
        if (!ALLOWED_SOURCE_TYPES.has(detectedMime)) throw new Error('原图格式不受支持。')
        sourceBytes = bytes
        mimeType = detectedMime
        sendSource()
      })
      .catch(finishError)
  })
}
