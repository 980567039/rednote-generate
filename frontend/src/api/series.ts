import axios from 'axios'
import { API_BASE_URL, getApiErrorPayload } from './client'
import type {
  CreateSeriesTemplateInput,
  SeriesApiResponse,
  SeriesContentMode,
  SeriesProjectItem,
  SeriesTopicSuggestion
} from './types'

function normalizeSeriesResponse(raw: any): SeriesApiResponse {
  const nested = raw?.data
  const response: SeriesApiResponse = nested && !Array.isArray(nested) && typeof nested === 'object'
    ? { ...raw, ...nested, success: raw.success !== false }
    : { ...raw, success: raw?.success !== false }
  if (Array.isArray(nested)) {
    if (nested.some(item => item?.page_structure)) response.templates = nested
    else response.projects = nested
  } else if (nested?.id && nested?.items && !response.project) {
    response.project = nested
  } else if (nested?.id && nested?.page_structure && !response.template) {
    response.template = nested
  }
  const rawSuggestions = response.suggestions || nested?.suggestions
  if (Array.isArray(rawSuggestions)) {
    response.suggestions = rawSuggestions.map((value: string | SeriesTopicSuggestion) => (
      typeof value === 'string' ? { topic: value } : value
    ))
  }
  const candidates = raw?.candidates || nested?.candidates
  if (!response.suggestions && Array.isArray(candidates)) {
    response.suggestions = candidates.map((value: string | SeriesTopicSuggestion) => (
      typeof value === 'string' ? { topic: value } : value
    ))
  }
  const pagination = raw?.pagination || nested?.pagination
  if (pagination && typeof pagination === 'object') {
    response.page = response.page ?? pagination.page
    response.page_size = response.page_size ?? pagination.page_size
    response.total = response.total ?? pagination.total
    response.total_pages = response.total_pages ?? pagination.total_pages
  }
  return response
}

export async function getSeriesTemplates(): Promise<SeriesApiResponse> {
  try {
    const response = await axios.get(`${API_BASE_URL}/series/templates`, { timeout: 10000 })
    return normalizeSeriesResponse(response.data)
  } catch (error) {
    return { success: false, templates: [], ...getApiErrorPayload(error, '加载系列模板失败') }
  }
}

export async function createSeriesTemplate(template: CreateSeriesTemplateInput): Promise<SeriesApiResponse> {
  try {
    const response = await axios.post(`${API_BASE_URL}/series/templates`, template, { timeout: 30000 })
    return normalizeSeriesResponse(response.data)
  } catch (error) {
    return { success: false, ...getApiErrorPayload(error, '创建系列模板失败') }
  }
}

export async function updateSeriesTemplate(
  templateId: string,
  template: Partial<CreateSeriesTemplateInput>
): Promise<SeriesApiResponse> {
  try {
    const response = await axios.put(
      `${API_BASE_URL}/series/templates/${encodeURIComponent(templateId)}`,
      template,
      { timeout: 20000 }
    )
    return normalizeSeriesResponse(response.data)
  } catch (error) {
    return { success: false, ...getApiErrorPayload(error, '更新系列模板失败') }
  }
}

export async function deleteSeriesTemplate(templateId: string): Promise<SeriesApiResponse> {
  try {
    const response = await axios.delete(
      `${API_BASE_URL}/series/templates/${encodeURIComponent(templateId)}`,
      { timeout: 10000 }
    )
    return normalizeSeriesResponse(response.data)
  } catch (error) {
    return { success: false, ...getApiErrorPayload(error, '删除系列模板失败') }
  }
}

export async function uploadSeriesTemplateReferences(
  templateId: string,
  images: File[]
): Promise<SeriesApiResponse> {
  const formData = new FormData()
  images.forEach(image => formData.append('images', image))
  try {
    const response = await axios.post(
      `${API_BASE_URL}/series/templates/${encodeURIComponent(templateId)}/references`,
      formData,
      { headers: { 'Content-Type': 'multipart/form-data' }, timeout: 60000 }
    )
    return normalizeSeriesResponse(response.data)
  } catch (error) {
    return { success: false, ...getApiErrorPayload(error, '上传系列参考图失败') }
  }
}

export async function createSeriesProject(
  templateId: string,
  topics: string[] = [],
  name?: string
): Promise<SeriesApiResponse> {
  try {
    const response = await axios.post(
      `${API_BASE_URL}/series/projects`,
      { template_id: templateId, topics, name: name?.trim() || undefined },
      { timeout: 20000 }
    )
    return normalizeSeriesResponse(response.data)
  } catch (error) {
    return { success: false, ...getApiErrorPayload(error, '创建系列项目失败') }
  }
}

export async function getSeriesProjectItems(
  projectId: string,
  options: { page?: number; pageSize?: number; query?: string; status?: string } = {}
): Promise<SeriesApiResponse> {
  try {
    const response = await axios.get(
      `${API_BASE_URL}/series/projects/${encodeURIComponent(projectId)}/items`,
      {
        params: {
          page: options.page || 1,
          page_size: options.pageSize || 10,
          q: options.query || undefined,
          status: options.status || undefined
        },
        timeout: 10000
      }
    )
    return normalizeSeriesResponse(response.data)
  } catch (error) {
    return { success: false, items: [], ...getApiErrorPayload(error, '加载合集子主题失败') }
  }
}

export async function appendSeriesProjectItems(
  projectId: string,
  topics: string[],
  topicSource: 'user' | 'system' | 'user_modified_system' = 'user',
  ipAcknowledged: boolean = false,
  contentMode: SeriesContentMode = 'story'
): Promise<SeriesApiResponse> {
  try {
    const response = await axios.post(
      `${API_BASE_URL}/series/projects/${encodeURIComponent(projectId)}/items`,
      { topics, topic_source: topicSource, ip_acknowledged: ipAcknowledged, content_mode: contentMode },
      { timeout: 20000 }
    )
    return normalizeSeriesResponse(response.data)
  } catch (error) {
    return { success: false, ...getApiErrorPayload(error, '追加合集子主题失败') }
  }
}

export async function getSeriesTopicSuggestions(
  projectId: string,
  allowIp: boolean = false
): Promise<SeriesApiResponse> {
  try {
    const response = await axios.post(
      `${API_BASE_URL}/series/projects/${encodeURIComponent(projectId)}/topic-suggestions`,
      { allow_third_party_ip: allowIp },
      { timeout: 60000 }
    )
    return normalizeSeriesResponse(response.data)
  } catch (error) {
    return { success: false, suggestions: [], ...getApiErrorPayload(error, '获取子主题候选失败') }
  }
}

export async function getSeriesProjects(): Promise<SeriesApiResponse> {
  try {
    const response = await axios.get(`${API_BASE_URL}/series/projects`, { timeout: 10000 })
    return normalizeSeriesResponse(response.data)
  } catch (error) {
    return { success: false, projects: [], ...getApiErrorPayload(error, '加载系列合集失败') }
  }
}

export async function getSeriesProject(projectId: string): Promise<SeriesApiResponse> {
  try {
    const response = await axios.get(
      `${API_BASE_URL}/series/projects/${encodeURIComponent(projectId)}`,
      { timeout: 10000 }
    )
    return normalizeSeriesResponse(response.data)
  } catch (error) {
    return { success: false, ...getApiErrorPayload(error, '加载系列项目失败') }
  }
}

export async function generateSeriesItemOutline(projectId: string, itemId: string): Promise<SeriesApiResponse> {
  try {
    const response = await axios.post(
      `${API_BASE_URL}/series/projects/${encodeURIComponent(projectId)}/items/${encodeURIComponent(itemId)}/outline`,
      {},
      { timeout: 120000 }
    )
    return normalizeSeriesResponse(response.data)
  } catch (error) {
    return { success: false, ...getApiErrorPayload(error, '批量生成系列大纲失败') }
  }
}

export async function updateSeriesProjectItem(
  projectId: string,
  itemId: string,
  item: Partial<Pick<SeriesProjectItem, 'outline' | 'pages' | 'content_mode'>>
): Promise<SeriesApiResponse> {
  try {
    const response = await axios.put(
      `${API_BASE_URL}/series/projects/${encodeURIComponent(projectId)}/items/${encodeURIComponent(itemId)}`,
      item,
      { timeout: 20000 }
    )
    return normalizeSeriesResponse(response.data)
  } catch (error) {
    return { success: false, ...getApiErrorPayload(error, '保存子主题大纲失败') }
  }
}

export async function deleteSeriesProjectItem(projectId: string, itemId: string): Promise<SeriesApiResponse> {
  try {
    const response = await axios.delete(
      `${API_BASE_URL}/series/projects/${encodeURIComponent(projectId)}/items/${encodeURIComponent(itemId)}`,
      { timeout: 20000 }
    )
    return normalizeSeriesResponse(response.data)
  } catch (error) {
    return { success: false, ...getApiErrorPayload(error, '删除合集子主题失败') }
  }
}

export async function confirmSeriesProjectItem(projectId: string, itemId: string): Promise<SeriesApiResponse> {
  try {
    const response = await axios.post(
      `${API_BASE_URL}/series/projects/${encodeURIComponent(projectId)}/items/${encodeURIComponent(itemId)}/confirm`,
      { confirm: true },
      { timeout: 20000 }
    )
    return normalizeSeriesResponse(response.data)
  } catch (error) {
    return { success: false, ...getApiErrorPayload(error, '确认子主题大纲失败') }
  }
}

export async function generateSeriesProjectItem(projectId: string, itemId: string): Promise<SeriesApiResponse> {
  try {
    const response = await axios.post(
      `${API_BASE_URL}/series/projects/${encodeURIComponent(projectId)}/items/${encodeURIComponent(itemId)}/generate`,
      { confirm: true },
      { timeout: 30000 }
    )
    return normalizeSeriesResponse(response.data)
  } catch (error) {
    return { success: false, ...getApiErrorPayload(error, '启动子主题生成失败') }
  }
}

export async function retrySeriesProjectItemImages(projectId: string, itemId: string): Promise<SeriesApiResponse> {
  try {
    const response = await axios.post(
      `${API_BASE_URL}/series/projects/${encodeURIComponent(projectId)}/items/${encodeURIComponent(itemId)}/retry-failed`,
      {},
      { timeout: 20000 }
    )
    return normalizeSeriesResponse(response.data)
  } catch (error) {
    return { success: false, ...getApiErrorPayload(error, '补全失败图片失败') }
  }
}

export async function getSeriesProjectTasks(projectId: string): Promise<SeriesApiResponse> {
  try {
    const response = await axios.get(
      `${API_BASE_URL}/series/projects/${encodeURIComponent(projectId)}/tasks`,
      { timeout: 10000 }
    )
    return normalizeSeriesResponse(response.data)
  } catch (error) {
    return { success: false, ...getApiErrorPayload(error, '获取系列生成任务失败') }
  }
}

async function runSeriesBulkAction(
  projectId: string,
  action: 'outlines' | 'confirm' | 'generate',
  itemIds: string[]
): Promise<SeriesApiResponse> {
  try {
    const response = await axios.post(
      `${API_BASE_URL}/series/projects/${encodeURIComponent(projectId)}/${action}`,
      { item_ids: itemIds },
      { timeout: 30000 }
    )
    return normalizeSeriesResponse(response.data)
  } catch (error) {
    const labels = { outlines: '批量生成大纲失败', confirm: '批量确认大纲失败', generate: '批量生成作品失败' }
    return { success: false, ...getApiErrorPayload(error, labels[action]) }
  }
}

export function generateSeriesOutlines(projectId: string, itemIds: string[]): Promise<SeriesApiResponse> {
  return runSeriesBulkAction(projectId, 'outlines', itemIds)
}

export function confirmSeriesProject(projectId: string, itemIds: string[]): Promise<SeriesApiResponse> {
  return runSeriesBulkAction(projectId, 'confirm', itemIds)
}

export function generateSeriesImages(projectId: string, itemIds: string[]): Promise<SeriesApiResponse> {
  return runSeriesBulkAction(projectId, 'generate', itemIds)
}
