import { isValidPerlerSettings, type PerlerPatternSettings } from './perlerSettings'
import { apiFetch } from '../api/client'
import { generatePatternLocally } from './localPerler'

const MANUAL_CHANNEL = 'redink-perler'
const VERSION = 1
const MAX_SOURCE_BYTES = 25 * 1024 * 1024
const MAX_PATTERN_BYTES = 20 * 1024 * 1024
const MAX_PREVIEW_BYTES = 10 * 1024 * 1024
const HANDOFF_TIMEOUT_MS = 5 * 60 * 1000
const ALLOWED_SOURCE_TYPES = new Set(['image/png', 'image/jpeg', 'image/webp'])

export interface PerlerPatternMetadata {
  columns: number
  rows: number
  usedColors: number
  profile?: 'shape' | 'balanced' | 'detail'
  algorithmVersion?: string
  sourceKind?: 'original' | 'bead-source'
}

export interface PerlerPatternResult {
  requestId: string
  pattern: Blob
  /** The exact cell matrix used to render the local outputs. */
  cells?: Uint16Array
  /** Cylindrical, un-ironed bead rendering. */
  beads?: Blob
  /** Flattened, heat-pressed rendering. */
  ironed?: Blob
  /** Legacy alias for the bead rendering returned by older Perler builds. */
  preview?: Blob
  metadata: PerlerPatternMetadata
}

export type PerlerAutoProgressStage =
  | 'prepare'
  | 'sample'
  | 'select'
  | 'map'
  | 'cleanup'
  | 'background'
  | 'refine'
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
  protocolVersion?: number
  type: string
  requestId?: string
  pattern?: ArrayBuffer
  cells?: ArrayBuffer
  grid?: { columns?: unknown; rows?: unknown }
  mimeType?: string
  beads?: ArrayBuffer
  beadsMimeType?: string
  ironed?: ArrayBuffer
  ironedMimeType?: string
  preview?: ArrayBuffer
  previewMimeType?: string
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

function randomRequestId(): string {
  return typeof crypto.randomUUID === 'function'
    ? crypto.randomUUID()
    : `${Date.now().toString(36)}-${Math.random().toString(36).slice(2)}`
}

function validateBridgeInput(input: {
  recordId: string
  imageUrl?: string
  source?: Blob
  imageIndex: number
  settings?: PerlerPatternSettings
  cells?: Uint16Array
  metadata?: PerlerPatternMetadata
}) {
  if (!input.recordId.trim()) throw new Error('缺少历史记录 ID，无法生成拼豆图纸。')
  if (!input.imageUrl?.trim() && !input.source) throw new Error('缺少原图，无法生成拼豆图纸。')
  if (!Number.isInteger(input.imageIndex) || input.imageIndex < 0) throw new Error('原图页码无效。')
  if (input.settings && !isValidPerlerSettings(input.settings)) throw new Error('拼豆图纸规格无效。')
  if (input.cells && input.metadata && input.cells.length !== input.metadata.columns * input.metadata.rows) {
    throw new Error('网格数据长度与图纸元数据不一致。')
  }
}

async function sourceImageBytes(input: { imageUrl?: string; source?: Blob }, signal?: AbortSignal): Promise<{
  bytes: ArrayBuffer
  mimeType: string
}> {
  if (!input.source) return fetchSourceImage(input.imageUrl || '', signal)
  const mimeType = input.source.type.split(';', 1)[0].toLowerCase() || 'image/png'
  if (input.source.size < 1 || input.source.size > MAX_SOURCE_BYTES) throw new Error('原图为空或超过 25MB。')
  if (!ALLOWED_SOURCE_TYPES.has(mimeType)) throw new Error('原图格式不受支持，仅支持 PNG、JPEG 和 WebP。')
  return { bytes: await input.source.arrayBuffer(), mimeType }
}

async function fetchSourceImage(imageUrl: string, signal?: AbortSignal): Promise<{
  bytes: ArrayBuffer
  mimeType: string
}> {
  const sourceUrl = new URL(imageUrl, window.location.origin)
  const response = await apiFetch(sourceUrl.toString(), { credentials: 'same-origin', signal })
  if (!response.ok) throw new Error(`读取原图失败：HTTP ${response.status}`)
  const bytes = await response.arrayBuffer()
  if (bytes.byteLength === 0 || bytes.byteLength > MAX_SOURCE_BYTES) throw new Error('原图为空或超过 25MB。')
  const mimeType = (response.headers.get('content-type') || 'image/png').split(';', 1)[0].toLowerCase()
  if (!ALLOWED_SOURCE_TYPES.has(mimeType)) throw new Error('原图格式不受支持，仅支持 PNG、JPEG 和 WebP。')
  return { bytes, mimeType }
}

function patternResultFromMessage(
  message: PerlerMessage,
  requestId: string,
  requirePreview = false,
  requireEffects = false,
): PerlerPatternResult {
  if (
    message.mimeType !== 'image/png'
    || !(message.pattern instanceof ArrayBuffer)
    || message.pattern.byteLength === 0
    || message.pattern.byteLength > MAX_PATTERN_BYTES
  ) throw new Error('Perler 回传的图纸不是有效 PNG，或文件超过 20MB。')
  if (!validMetadata(message.metadata)) throw new Error('Perler 回传的图纸元数据无效。')
  const beads = message.beadsMimeType === 'image/png'
    && message.beads instanceof ArrayBuffer
    && message.beads.byteLength > 0
    && message.beads.byteLength <= MAX_PREVIEW_BYTES
    ? new Blob([message.beads], { type: 'image/png' })
    : undefined
  const legacyPreview = message.previewMimeType === 'image/png'
    && message.preview instanceof ArrayBuffer
    && message.preview.byteLength > 0
    && message.preview.byteLength <= MAX_PREVIEW_BYTES
    ? new Blob([message.preview], { type: 'image/png' })
    : undefined
  const beadPreview = beads ?? legacyPreview
  const ironed = message.ironedMimeType === 'image/png'
    && message.ironed instanceof ArrayBuffer
    && message.ironed.byteLength > 0
    && message.ironed.byteLength <= MAX_PREVIEW_BYTES
    ? new Blob([message.ironed], { type: 'image/png' })
    : undefined
  if (requirePreview && !beadPreview) throw new Error('Perler 未回传有效的拼豆实物效果图。')
  if (requireEffects && (!beadPreview || !ironed)) {
    throw new Error('Perler 未回传完整的拼豆实物和熨烫成品效果图。')
  }
  let cells: Uint16Array | undefined
  if (message.cells instanceof ArrayBuffer) {
    const expectedBytes = message.metadata.columns * message.metadata.rows * 2
    if (message.cells.byteLength !== expectedBytes) throw new Error('Perler 回传的网格长度与元数据不一致。')
    const decoded = new Uint16Array(message.cells)
    for (const value of decoded) {
      if (value !== 0xffff && value >= 221) throw new Error('Perler 回传了未知色板索引。')
    }
    cells = decoded
  }
  return {
    requestId,
    ...(cells ? { cells } : {}),
    pattern: new Blob([message.pattern], { type: 'image/png' }),
    ...(beadPreview ? { beads: beadPreview, preview: beadPreview } : {}),
    ...(ironed ? { ironed } : {}),
    metadata: message.metadata,
  }
}

export async function generatePatternWithPerler(input: {
  recordId: string
  imageUrl?: string
  source?: Blob
  imageIndex: number
  fileName?: string
  settings?: PerlerPatternSettings
  /** Existing local matrix to open in Perler without recalculating it. */
  cells?: Uint16Array
  metadata?: PerlerPatternMetadata
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
        const matrix = input.cells ? input.cells.slice() : null
        const matrixBuffer = matrix ? matrix.buffer as ArrayBuffer : null
        const useMatrixImport = Boolean(matrixBuffer && input.metadata)
        popup.postMessage(
          {
            channel: MANUAL_CHANNEL,
            version: VERSION,
            type: useMatrixImport ? 'IMPORT_PATTERN' : 'IMPORT_IMAGE',
            requestId,
            context: {
              recordId: input.recordId,
              imageIndex: input.imageIndex,
              fileName: input.fileName || `redink-page-${input.imageIndex + 1}.png`,
            },
            image: transfer,
            mimeType,
            ...(input.settings ? { settings: { ...input.settings } } : {}),
            ...(useMatrixImport ? {
              cells: matrixBuffer,
              grid: {
                columns: input.metadata!.columns,
                rows: input.metadata!.rows,
              },
              metadata: { ...input.metadata },
            } : {}),
          },
          origin,
          matrixBuffer ? [transfer, matrixBuffer] : [transfer],
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
    void sourceImageBytes(input)
      .then(source => {
        sourceBytes = source.bytes
        mimeType = source.mimeType
        sendSource()
      })
      .catch(finishError)
  })
}

/** Generate the pattern locally with the same MVP algorithm as Perler. */
export function generatePatternAutomatically(input: {
  recordId: string
  imageUrl?: string
  source?: Blob
  imageIndex: number
  fileName?: string
  settings: PerlerPatternSettings
  onReady?: () => void
  onProgress?: (progress: PerlerProgressUpdate) => void
}): PerlerAutoJob {
  return generatePatternLocally(input)
}
