import type { AppError } from '../utils/errors'

export interface Page {
  index: number
  type: 'cover' | 'content' | 'summary'
  content: string
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
}

export interface CreateHistoryParams {
  topic: string
  outline: { raw: string; pages: Page[] }
  task_id?: string
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
  output?: string
  returncode?: number
  config?: PublishConfig
  task?: PublishTask
  error?: AppError | string
  error_message?: string
}
