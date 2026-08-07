import { API_BASE_URL, readErrorResponse } from './client'
import type { PerlerPatternSettings } from '../integrations/perlerSettings'

const MAX_SOURCE_BYTES = 25 * 1024 * 1024
const ALLOWED_IMAGE_TYPES = new Set(['image/png', 'image/jpeg', 'image/webp'])

function normalizedMimeType(blob: Blob): string {
  return blob.type.split(';', 1)[0].trim().toLowerCase() || 'image/png'
}

function assertPatternImage(blob: Blob, label: string, maxBytes = MAX_SOURCE_BYTES) {
  const mimeType = normalizedMimeType(blob)
  if (blob.size < 1 || blob.size > maxBytes) throw new Error(`${label}为空或超过大小限制。`)
  if (!ALLOWED_IMAGE_TYPES.has(mimeType)) throw new Error(`${label}格式不受支持，仅支持 PNG、JPEG 和 WebP。`)
}

async function responseError(response: Response, fallback: string): Promise<Error> {
  const payload = await readErrorResponse(response, fallback)
  if (payload instanceof Error) return payload
  if (payload && typeof payload === 'object') {
    const data = payload as {
      error_message?: unknown
      message?: unknown
      error?: unknown
    }
    const structuredError = data.error && typeof data.error === 'object'
      ? data.error as { detail?: unknown; suggestion?: unknown; title?: unknown }
      : null
    const message = [
      structuredError?.detail,
      structuredError?.suggestion,
      structuredError?.title,
      data.error_message,
      data.message,
      data.error,
    ]
      .find(value => typeof value === 'string' && value.trim())
    if (typeof message === 'string') return new Error(message)
  }
  return new Error(fallback)
}

export async function fetchPatternSource(imageUrl: string, signal?: AbortSignal): Promise<Blob> {
  const sourceUrl = new URL(imageUrl, window.location.origin)
  const response = await fetch(sourceUrl.toString(), { credentials: 'same-origin', signal })
  if (!response.ok) throw await responseError(response, `读取原图失败：HTTP ${response.status}`)
  const blob = await response.blob()
  assertPatternImage(blob, '原图')
  return blob
}

export async function refinePatternImageWithAi(input: {
  stage: 'source' | 'pattern'
  source: Blob
  patternPreview?: Blob
  settings: PerlerPatternSettings
  signal?: AbortSignal
}): Promise<Blob> {
  assertPatternImage(input.source, '原图')
  if (input.stage === 'pattern') {
    if (!input.patternPreview) throw new Error('缺少104精细基础效果图，无法执行第二阶段AI精修。')
    assertPatternImage(input.patternPreview, '拼豆效果图', 10 * 1024 * 1024)
  }

  const form = new FormData()
  form.append('stage', input.stage)
  form.append('columns', String(input.settings.columns))
  form.append('rows', String(input.settings.rows))
  form.append('max_used_colors', String(input.settings.maxUsedColors))
  form.append('source', input.source, `pattern-source.${normalizedMimeType(input.source).split('/')[1] || 'png'}`)
  if (input.patternPreview) form.append('pattern_preview', input.patternPreview, 'pattern-preview.png')

  const response = await fetch(`${API_BASE_URL}/pattern/ai-refine`, {
    method: 'POST',
    body: form,
    signal: input.signal,
  })
  if (!response.ok) {
    throw await responseError(response, `AI精修失败：HTTP ${response.status}`)
  }
  const result = await response.blob()
  if (result.type !== 'image/png' || result.size < 1 || result.size > MAX_SOURCE_BYTES) {
    throw new Error('AI精修返回的图片无效。')
  }
  return result
}
