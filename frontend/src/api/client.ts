import axios from 'axios'
import type { AppError } from '../utils/errors'

export const API_BASE_URL = '/api'

export function getApiErrorPayload(error: unknown, fallback: string): {
  error: AppError | string
  error_message: string
} {
  if (axios.isAxiosError(error)) {
    if (error.code === 'ECONNABORTED') {
      return {
        error: '请求超时，请检查网络连接',
        error_message: '请求超时，请检查网络连接'
      }
    }
    if (!error.response) {
      return {
        error: '网络连接失败，请检查网络设置',
        error_message: '网络连接失败，请检查网络设置'
      }
    }
    const data = error.response.data || {}
    const message = data.error_message || fallback
    return {
      error: data.error || message,
      error_message: message
    }
  }

  return {
    error: fallback,
    error_message: fallback
  }
}

export async function readErrorResponse(response: Response, fallback: string) {
  try {
    return await response.json()
  } catch {
    return new Error(fallback)
  }
}

export class SseStreamError extends Error {
  code: string

  constructor(code: string, message: string) {
    super(message)
    this.name = 'SseStreamError'
    this.code = code
  }
}

interface ReadSseOptions {
  terminalEvents?: string[]
}

export async function readSseResponse(
  response: Response,
  handlers: Record<string, (data: any) => void>,
  options: ReadSseOptions = {}
) {
  const reader = response.body?.getReader()
  if (!reader) {
    throw new Error('无法读取响应流')
  }

  const decoder = new TextDecoder()
  let buffer = ''
  let terminalReceived = false

  const dispatchFrame = (frame: string) => {
    let eventType = 'message'
    const dataLines: string[] = []

    for (const line of frame.split(/\r\n|\r|\n/)) {
      if (!line || line.startsWith(':')) continue

      const separator = line.indexOf(':')
      const field = separator === -1 ? line : line.slice(0, separator)
      let value = separator === -1 ? '' : line.slice(separator + 1)
      if (value.startsWith(' ')) value = value.slice(1)

      if (field === 'event') eventType = value
      if (field === 'data') dataLines.push(value)
    }

    // 心跳注释、空事件以及服务端的 keep-alive 帧无需交给业务层。
    if (dataLines.length === 0) return

    const rawData = dataLines.join('\n')
    let data: unknown
    try {
      data = JSON.parse(rawData)
    } catch (cause) {
      throw new SseStreamError(
        'SSE_INVALID_DATA',
        `服务端返回了无法解析的流数据：${cause instanceof Error ? cause.message : String(cause)}`
      )
    }

    handlers[eventType]?.(data)
    if (options.terminalEvents?.includes(eventType)) terminalReceived = true
  }

  const drainFrames = () => {
    while (true) {
      const boundary = buffer.match(/\r\n\r\n|\n\n|\r\r/)
      if (!boundary || boundary.index === undefined) return
      const frame = buffer.slice(0, boundary.index)
      buffer = buffer.slice(boundary.index + boundary[0].length)
      dispatchFrame(frame)
    }
  }

  try {
    while (true) {
      const { done, value } = await reader.read()

      if (done) break

      buffer += decoder.decode(value, { stream: true })
      drainFrames()
    }

    buffer += decoder.decode()
    drainFrames()
    if (buffer.trim()) dispatchFrame(buffer)

    if (options.terminalEvents?.length && !terminalReceived) {
      throw new SseStreamError('STREAM_INCOMPLETE', '生成连接已中断，未收到任务完成状态')
    }
  } finally {
    reader.releaseLock()
  }
}
