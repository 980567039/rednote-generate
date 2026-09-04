import { apiFetch } from '../api/client'
import type {
  PerlerAutoJob,
  PerlerPatternResult,
  PerlerProgressUpdate,
} from './perlerBridge'
import { PerlerBridgeCancelledError } from './perlerBridge'
import type { PerlerPatternSettings } from './perlerSettings'

const MAX_SOURCE_BYTES = 25 * 1024 * 1024
const MAX_SOURCE_PIXELS = 40_000_000
const ALLOWED_SOURCE_TYPES = new Set(['image/png', 'image/jpeg', 'image/webp'])

interface LocalWorkerProgress {
  type: 'PROGRESS'
  jobId: string
  stage: 'prepare' | 'sample' | 'map' | 'background' | 'refine' | 'render'
  completed: number
  total: number
}

interface LocalWorkerResult {
  type: 'RESULT'
  jobId: string
  grid: { columns: number; rows: number }
  cells: ArrayBuffer
  counts: Array<{ colorId: string; paletteIndex: number; count: number }>
  totalBeads: number
  selectedPaletteIndices: number[]
  pattern: Blob
  beads: Blob
  ironed: Blob
  metadata: PerlerPatternResult['metadata']
}

interface LocalWorkerError {
  type: 'ERROR'
  jobId: string
  message: string
}

type LocalWorkerResponse = LocalWorkerProgress | LocalWorkerResult | LocalWorkerError

function randomRequestId(): string {
  return typeof crypto.randomUUID === 'function'
    ? crypto.randomUUID()
    : `${Date.now().toString(36)}-${Math.random().toString(36).slice(2)}`
}

function validateInput(input: {
  recordId: string
  imageUrl?: string
  source?: Blob
  imageIndex: number
  settings: PerlerPatternSettings
}): void {
  if (!input.recordId.trim()) throw new Error('缺少历史记录 ID，无法生成拼豆图纸。')
  if (!input.imageUrl?.trim() && !input.source) throw new Error('缺少原图，无法生成拼豆图纸。')
  if (!Number.isInteger(input.imageIndex) || input.imageIndex < 0) throw new Error('原图页码无效。')
  if (!Number.isInteger(input.settings.columns) || input.settings.columns < 1 || input.settings.columns > 300) {
    throw new Error('图纸列数必须是 1–300 的整数。')
  }
  if (!Number.isInteger(input.settings.rows) || input.settings.rows < 1 || input.settings.rows > 300) {
    throw new Error('图纸行数必须是 1–300 的整数。')
  }
  if (!Number.isInteger(input.settings.maxUsedColors) || input.settings.maxUsedColors < 2 || input.settings.maxUsedColors > 64) {
    throw new Error('最大用色数必须是 2–64 的整数。')
  }
}

async function loadSource(input: { imageUrl?: string; source?: Blob }, signal: AbortSignal): Promise<{ blob: Blob; mimeType: string }> {
  let blob: Blob
  if (input.source) {
    blob = input.source
  } else {
    const response = await apiFetch(new URL(input.imageUrl!, window.location.origin).toString(), {
      credentials: 'same-origin',
      signal,
    })
    if (!response.ok) throw new Error(`读取原图失败：HTTP ${response.status}`)
    blob = await response.blob()
  }
  const mimeType = (blob.type || 'image/png').split(';', 1)[0].toLowerCase()
  if (blob.size < 1 || blob.size > MAX_SOURCE_BYTES) throw new Error('原图为空或超过 25MB。')
  if (!ALLOWED_SOURCE_TYPES.has(mimeType)) throw new Error('原图格式不受支持，仅支持 PNG、JPEG 和 WebP。')
  return { blob, mimeType }
}

async function decodeSource(blob: Blob): Promise<ImageBitmap> {
  let bitmap: ImageBitmap
  try {
    bitmap = await createImageBitmap(blob, { imageOrientation: 'from-image' })
  } catch {
    throw new Error('源图片无法解码。')
  }
  if (bitmap.width < 1 || bitmap.height < 1 || bitmap.width * bitmap.height > MAX_SOURCE_PIXELS) {
    bitmap.close()
    throw new Error('图片解码后超过 4000 万像素，请先缩小。')
  }
  return bitmap
}

function validPng(blob: unknown): blob is Blob {
  return blob instanceof Blob && blob.type === 'image/png' && blob.size > 0
}

/**
 * Generate locally with the exact MVP sampler used by perler-to-perfect.
 * Perler is deliberately not opened in this path; it is only used by the
 * explicit "在 Perler 中编辑" action.
 */
export function generatePatternLocally(input: {
  recordId: string
  imageUrl?: string
  source?: Blob
  imageIndex: number
  fileName?: string
  settings: PerlerPatternSettings
  onReady?: () => void
  onProgress?: (progress: PerlerProgressUpdate) => void
}): PerlerAutoJob {
  validateInput(input)
  const requestId = randomRequestId()
  const abortController = new AbortController()
  let worker: Worker | null = null
  let bitmap: ImageBitmap | null = null
  let settled = false
  let rejectTask: ((reason?: unknown) => void) | null = null
  let resolveTask: ((result: PerlerPatternResult) => void) | null = null

  const promise = new Promise<PerlerPatternResult>((resolve, reject) => {
    resolveTask = resolve
    rejectTask = reject
  })

  const cleanup = () => {
    abortController.abort()
    worker?.terminate()
    worker = null
    bitmap?.close()
    bitmap = null
  }
  const finishError = (reason: unknown) => {
    if (settled) return
    settled = true
    cleanup()
    rejectTask?.(reason instanceof Error ? reason : new Error(String(reason)))
    rejectTask = null
    resolveTask = null
  }
  const finishSuccess = (result: PerlerPatternResult) => {
    if (settled) return
    settled = true
    cleanup()
    resolveTask?.(result)
    rejectTask = null
    resolveTask = null
  }

  const start = async () => {
    try {
      input.onProgress?.({ stage: 'connect', completed: 1, total: 1 })
      const source = await loadSource(input, abortController.signal)
      bitmap = await decodeSource(source.blob)
      if (settled) {
        bitmap.close()
        bitmap = null
        return
      }
      input.onReady?.()
      input.onProgress?.({ stage: 'prepare', completed: 0, total: 1 })
      if (typeof Worker === 'undefined' || typeof OffscreenCanvas === 'undefined') {
        throw new Error('当前浏览器不支持本地拼豆生成，请使用最新版 Chrome、Edge 或 Safari。')
      }
      const activeBitmap = bitmap
      bitmap = null
      try {
        worker = new Worker(new URL('./perler-core/localGeneration.worker.ts', import.meta.url), { type: 'module' })
      } catch (reason) {
        activeBitmap.close()
        throw reason
      }
      worker.onmessage = (event: MessageEvent<LocalWorkerResponse>) => {
        const message = event.data
        if (message.jobId !== requestId || settled) return
        if (message.type === 'PROGRESS') {
          input.onProgress?.({
            stage: message.stage,
            completed: message.completed,
            total: Math.max(1, message.total),
          })
          return
        }
        if (message.type === 'ERROR') {
          finishError(new Error(message.message))
          return
        }
        if (
          !validPng(message.pattern)
          || !validPng(message.beads)
          || !validPng(message.ironed)
          || !(message.cells instanceof ArrayBuffer)
        ) {
          finishError(new Error('本地生成器回传了无效的 PNG 或网格数据。'))
          return
        }
        finishSuccess({
          requestId,
          cells: new Uint16Array(message.cells),
          pattern: message.pattern,
          beads: message.beads,
          preview: message.beads,
          ironed: message.ironed,
          metadata: message.metadata,
        })
      }
      worker.onerror = event => finishError(new Error(event.message || '本地生成 Worker 发生错误。'))
      try {
        worker.postMessage({
          type: 'GENERATE',
          jobId: requestId,
          bitmap: activeBitmap,
          settings: {
            ...input.settings,
            profile: 'balanced',
            sourceKind: 'original',
            sourceImageIndex: input.imageIndex,
            removeBorderBackground: true,
          },
        }, [activeBitmap])
      } catch (reason) {
        activeBitmap.close()
        throw reason
      }
    } catch (reason) {
      if (reason instanceof DOMException && reason.name === 'AbortError') return
      finishError(reason)
    }
  }
  void start()

  return {
    requestId,
    result: promise,
    cancel: () => finishError(new PerlerBridgeCancelledError()),
  }
}
