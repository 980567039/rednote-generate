import axios from 'axios'
import { API_BASE_URL, getApiErrorPayload } from './client'
import type {
  PublishApiResponse,
  PublishConfig,
  PublishMode
} from './types'

function normalizePublishResponse(data: PublishApiResponse): PublishApiResponse {
  if (data.authenticated === true && data.logged_in === undefined) data.logged_in = true
  if (data.task && !data.task.id && data.task.task_id) data.task.id = data.task.task_id
  return data
}

function normalizePublishRequestError(
  error: unknown,
  fallback: string,
  timeoutMessage?: string
): PublishApiResponse {
  if (timeoutMessage && axios.isAxiosError(error) && error.code === 'ECONNABORTED') {
    return {
      success: false,
      error: timeoutMessage,
      error_message: timeoutMessage
    }
  }
  return { success: false, ...getApiErrorPayload(error, fallback) }
}

export async function getPublishConfig(): Promise<PublishApiResponse> {
  try {
    const response = await axios.get(`${API_BASE_URL}/publish/config`, { timeout: 10000 })
    return normalizePublishResponse(response.data)
  } catch (error) {
    return { success: false, ...getApiErrorPayload(error, '加载小红书发布配置失败') }
  }
}

export async function updatePublishConfig(
  config: Pick<PublishConfig, 'account' | 'port' | 'headless' | 'default_mode'>
): Promise<PublishApiResponse> {
  try {
    const response = await axios.put(`${API_BASE_URL}/publish/config`, config, { timeout: 10000 })
    return normalizePublishResponse(response.data)
  } catch (error) {
    return { success: false, ...getApiErrorPayload(error, '保存小红书发布配置失败') }
  }
}

export async function checkPublishLogin(): Promise<PublishApiResponse> {
  try {
    const response = await axios.post(`${API_BASE_URL}/publish/auth/check`, {}, { timeout: 65000 })
    return normalizePublishResponse(response.data)
  } catch (error) {
    return normalizePublishRequestError(
      error,
      '检查小红书登录状态失败',
      '登录状态检查超过 65 秒未完成，发布助手可能正在启动 Chrome。请稍后重新检查。'
    )
  }
}

export async function openPublishLogin(): Promise<PublishApiResponse> {
  try {
    const response = await axios.post(`${API_BASE_URL}/publish/auth/login`, {}, { timeout: 30000 })
    return normalizePublishResponse(response.data)
  } catch (error) {
    return normalizePublishRequestError(
      error,
      '打开小红书登录页失败',
      'Chrome 登录页超过 30 秒仍未打开。请检查是否已弹出登录窗口；如未弹出，请到系统设置检查发布助手。'
    )
  }
}

export async function createPublishTask(
  recordId: string,
  payload: {
    title: string
    copywriting: string
    tags: string[]
    mode: PublishMode
    confirm: true
  }
): Promise<PublishApiResponse> {
  try {
    const response = await axios.post(
      `${API_BASE_URL}/history/${encodeURIComponent(recordId)}/publish`,
      payload,
      { timeout: 20000 }
    )
    return normalizePublishResponse(response.data)
  } catch (error) {
    return { success: false, ...getApiErrorPayload(error, '创建小红书发布任务失败') }
  }
}

export async function getPublishTask(taskId: string): Promise<PublishApiResponse> {
  try {
    const response = await axios.get(
      `${API_BASE_URL}/publish/tasks/${encodeURIComponent(taskId)}`,
      { timeout: 10000 }
    )
    return normalizePublishResponse(response.data)
  } catch (error) {
    return { success: false, ...getApiErrorPayload(error, '获取小红书发布状态失败') }
  }
}

export async function confirmPublishTask(taskId: string): Promise<PublishApiResponse> {
  try {
    const response = await axios.post(
      `${API_BASE_URL}/publish/tasks/${encodeURIComponent(taskId)}/confirm`,
      { confirm: true },
      { timeout: 20000 }
    )
    return normalizePublishResponse(response.data)
  } catch (error) {
    return { success: false, ...getApiErrorPayload(error, '确认小红书发布失败') }
  }
}

export async function cancelPublishTask(taskId: string): Promise<PublishApiResponse> {
  try {
    const response = await axios.post(
      `${API_BASE_URL}/publish/tasks/${encodeURIComponent(taskId)}/cancel`,
      {},
      { timeout: 10000 }
    )
    return normalizePublishResponse(response.data)
  } catch (error) {
    return { success: false, ...getApiErrorPayload(error, '停止发布任务失败') }
  }
}
