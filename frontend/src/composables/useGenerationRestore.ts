import { useGeneratorStore, type GeneratedImage } from '../stores/generator'
import {
  createHistory,
  getHistory,
  getImageUrl,
  type HistoryDetail,
  type SeriesRequestContext
} from '../api'

export function seriesContextFromHistory(
  record: HistoryDetail,
  overrides: SeriesRequestContext = {}
): SeriesRequestContext {
  const values: SeriesRequestContext = {
    series_id: record.series_id || undefined,
    series_template_id: record.series_template_id || undefined,
    series_project_id: record.series_project_id || record.series_id || undefined,
    series_item_id: record.series_item_id || undefined,
    series_item_index: record.series_item_index ?? undefined,
    series_item_title: record.series_item_title || undefined,
    content_mode: record.series_content_mode === 'character_sheet' || record.series_content_mode === 'story'
      ? record.series_content_mode
      : undefined,
    ...overrides
  }
  return Object.fromEntries(
    Object.entries(values).filter(([, value]) => value !== undefined && value !== null && value !== '')
  ) as SeriesRequestContext
}

export function useGenerationRestore() {
  const store = useGeneratorStore()

  function hasGeneratedImages(record: HistoryDetail): boolean {
    return !!record.images?.task_id && (record.images.generated || []).some(Boolean)
  }

  function hydrateFromHistory(record: HistoryDetail) {
    const taskId = record.images.task_id
    const generated = record.images.generated || []
    const pages = record.outline.pages || []
    const doneCount = pages.reduce((count, page, idx) => {
      const filename = generated[page.index] || generated[idx]
      return filename ? count + 1 : count
    }, 0)

    const images: GeneratedImage[] = pages.map((page, idx) => {
      const filename = generated[page.index] || generated[idx] || ''
      return {
        index: page.index,
        url: filename && taskId ? getImageUrl(taskId, filename) : '',
        status: filename ? 'done' : 'error',
        retryable: !filename
      }
    })
    store.replaceWork({
      topic: record.title,
      outline: record.outline,
      recordId: record.id,
      seriesContext: seriesContextFromHistory(record),
      taskId,
      images,
      progress: {
        current: doneCount,
        total: pages.length,
        status: doneCount >= pages.length ? 'done' : 'error'
      },
      stage: doneCount >= pages.length ? 'result' : 'generating',
      content: record.content
    })
  }

  async function restoreFromHistory(): Promise<boolean> {
    if (!store.recordId) return false

    const res = await getHistory(store.recordId)
    if (!res.success || !res.record) return false

    if (!hasGeneratedImages(res.record)) return false

    hydrateFromHistory(res.record)
    return true
  }

  async function ensureRecord() {
    if (store.recordId) return

    console.warn('警告: recordId 不存在，尝试创建历史记录作为兜底')
    try {
      const result = await createHistory(store.topic, {
        raw: store.outline.raw,
        pages: store.outline.pages
      }, undefined, store.seriesContext)
      if (result.success && result.record_id) {
        store.setRecordId(result.record_id)
        console.log('兜底创建历史记录成功:', store.recordId)
      }
    } catch (e) {
      console.error('兜底创建历史记录失败:', e)
    }
  }

  return {
    ensureRecord,
    restoreFromHistory
  }
}
