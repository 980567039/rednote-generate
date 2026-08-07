import type { AppError } from '../utils/errors'

export interface Page {
  index: number
  type: 'cover' | 'content' | 'summary' | 'pattern'
  content: string
  pattern?: {
    source_image_index: number
    columns: number
    rows: number
    used_colors: number
  }
}

export interface OutlineResponse {
  success: boolean
  outline?: string
  pages?: Page[]
  error?: AppError | string
  error_message?: string
}

export interface ProgressEvent {
  index: number
  status: 'queued' | 'generating' | 'retrying' | 'done' | 'error' | 'interrupted'
  current?: number
  total?: number
  phase?: string
  attempt?: number
  image_url?: string
  message?: string
  error?: AppError | string
  retryable?: boolean
}

export interface AcceptedEvent {
  task_id: string
  record_id?: string | null
  status: 'queued' | 'running'
  phase?: string
  reused?: boolean
}

export interface FinishEvent {
  success: boolean
  task_id: string
  images: string[]
  total?: number
  completed?: number
  failed?: number
  failed_indices?: number[]
  failed_errors?: Record<string, AppError | string>
  cached?: boolean
}

export interface HistoryRecord {
  id: string
  title: string
  created_at: string
  updated_at: string
  status: string
  thumbnail: string | null
  page_count: number
  task_id: string | null
  series_id?: string | null
  series_template_id?: string | null
  series_project_id?: string | null
  series_item_id?: string | null
  series_item_index?: number | null
  series_item_title?: string | null
  series_content_mode?: SeriesContentMode | string | null
}

export interface HistoryDetail {
  id: string
  title: string
  created_at: string
  updated_at: string
  outline: {
    raw: string
    pages: Page[]
  }
  images: {
    task_id: string | null
    generated: string[]
    errors?: Record<string, AppError | string>
  }
  content?: {
    titles: string[]
    copywriting: string
    tags: string[]
    status: 'idle' | 'generating' | 'done' | 'error'
    error?: string
  }
  status: string
  thumbnail: string | null
  series_id?: string | null
  series_template_id?: string | null
  series_project_id?: string | null
  series_item_id?: string | null
  series_item_index?: number | null
  series_item_title?: string | null
  series_content_mode?: SeriesContentMode | string | null
}

export interface CreateHistoryParams {
  topic: string
  outline: { raw: string; pages: Page[] }
  task_id?: string
  series_id?: string
  series_template_id?: string
  series_project_id?: string
  series_item_id?: string
  series_item_index?: number
  series_item_title?: string
}

export interface UpdateHistoryParams {
  outline?: { raw: string; pages: Page[] }
  images?: { task_id: string | null; generated: string[] }
  content?: {
    titles: string[]
    copywriting: string
    tags: string[]
    status?: 'idle' | 'generating' | 'done' | 'error'
    error?: string
  }
  status?: string
  thumbnail?: string
}

export interface Config {
  text_generation: {
    active_provider: string
    providers: Record<string, any>
  }
  image_generation: {
    active_provider: string
    providers: Record<string, any>
  }
}

export interface ContentResponse {
  success: boolean
  titles?: string[]
  copywriting?: string
  tags?: string[]
  error?: AppError | string
  error_message?: string
}

export interface SeriesRequestContext {
  record_id?: string
  series_id?: string
  series_template_id?: string
  series_project_id?: string
  series_item_id?: string
  series_item_index?: number
  series_item_title?: string
  content_mode?: SeriesContentMode
}

export type PublishMode = 'preview' | 'auto'

export type PublishTaskStatus =
  | 'queued'
  | 'validating'
  | 'checking_auth'
  | 'auth_required'
  | 'launching_browser'
  | 'opening_browser'
  | 'uploading'
  | 'filling'
  | 'ready_for_review'
  | 'submitting'
  | 'submitted'
  | 'published'
  | 'failed'
  | 'unknown'
  | 'cancelled'

export interface PublishConfig {
  account: string
  port: number
  headless: boolean
  default_mode: PublishMode
  publisher_available: boolean
  publisher_dir: string
}

export interface PublishTask {
  id: string
  task_id?: string
  status: PublishTaskStatus
  phase?: string
  message?: string
  mode?: PublishMode
  created_at?: string
  updated_at?: string
  error?: AppError | string
  error_message?: string
  note_url?: string | null
  output?: string
  record_id?: string
  authenticated?: boolean
}

export interface PublishApiResponse {
  success: boolean
  message?: string
  logged_in?: boolean
  authenticated?: boolean
  login_started?: boolean
  login_url?: string
  qrcode_data_url?: string
  mime_type?: string
  output?: string
  returncode?: number
  config?: PublishConfig
  task?: PublishTask
  error?: AppError | string
  error_message?: string
}

export type SeriesStructurePreset = 'standard' | 'comparison_two' | 'comparison_four'

export interface SeriesPageStructure {
  preset: SeriesStructurePreset
  page_count: number
}

export interface SeriesTemplate {
  id: string
  name: string
  description: string
  visual_style: string
  palette: string
  composition: string
  character_bible: string
  copy_tone: string
  prohibited_elements: string | string[]
  page_structure: SeriesPageStructure
  ip_notice: string
  reference_images: string[]
  revision?: number
  created_at?: string
  updated_at?: string
}

export type SeriesTemplateSnapshot = Omit<SeriesTemplate, 'created_at' | 'updated_at'> & {
  captured_at?: string
}

export interface SeriesProjectItem {
  id: string
  index: number
  topic: string
  content_mode?: SeriesContentMode
  character_names?: string[]
  topic_source?: 'user' | 'system' | 'user_modified_system' | string
  ip_acknowledged?: boolean
  record_id: string | null
  outline: string
  pages: Page[]
  status: string
  outline_status?: string
  content_status?: string
  image_status?: string
  template_revision?: number
  template_snapshot?: SeriesTemplateSnapshot
  error?: AppError | string
  error_message?: string
  failed_indices?: number[]
  image_errors?: Record<string, AppError | string>
  progress?: SeriesProjectProgress | number
}

export type SeriesContentMode = 'story' | 'character_sheet'

export interface SeriesProjectProgress {
  current: number
  total: number
  percent?: number
  message?: string
}

export interface SeriesProject {
  id: string
  name: string
  template_id: string
  topics: string[]
  items: SeriesProjectItem[]
  content_mode?: SeriesContentMode
  status: string
  progress: SeriesProjectProgress | number
  template?: SeriesTemplate
  item_count?: number
  status_counts?: Record<string, number>
  created_at?: string
  updated_at?: string
}

export interface SeriesApiResponse {
  success: boolean
  template?: SeriesTemplate
  templates?: SeriesTemplate[]
  project?: SeriesProject
  projects?: SeriesProject[]
  message?: string
  error?: AppError | string
  error_message?: string
  tasks?: Array<Record<string, unknown>>
  item?: SeriesProjectItem
  deleted_item?: SeriesProjectItem
  items?: SeriesProjectItem[]
  suggestions?: SeriesTopicSuggestion[]
  page?: number
  page_size?: number
  total?: number
  total_pages?: number
  status_counts?: Record<string, number>
  source?: 'model' | 'fallback' | string
  warning?: string | null
}

export interface SeriesTopicSuggestion {
  topic: string
  reason?: string
  uses_ip?: boolean
}

export type CreateSeriesTemplateInput = Omit<SeriesTemplate, 'id' | 'created_at' | 'updated_at'>
