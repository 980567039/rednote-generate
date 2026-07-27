import type { ComputedRef } from 'vue'
import { ref } from 'vue'
import { useRouter } from 'vue-router'
import { useGeneratorStore } from '../stores/generator'
import { generateImagesPost } from '../api'
import { formatErrorMessage, normalizeApiError, type AppError } from '../utils/errors'
import { useGenerationRestore } from './useGenerationRestore'

export function useGenerationRunner(
  hasFailedImages: ComputedRef<boolean>,
  setError: (error: AppError | null) => void
) {
  const router = useRouter()
  const store = useGeneratorStore()
  const { ensureRecord, restoreFromHistory } = useGenerationRestore()
  const redirectTimer = ref<number | null>(null)
  let isUnmounted = false
  let runToken = 0
  let runningPromise: Promise<void> | null = null
  let abortController: AbortController | null = null

  function startGenerationFlow(): Promise<void> {
    if (runningPromise) return runningPromise

    isUnmounted = false
    const token = ++runToken
    abortController = new AbortController()
    const isCurrentRun = () => !isUnmounted && token === runToken

    runningPromise = (async () => {
      if (store.outline.pages.length === 0) {
        await router.push('/')
        return
      }

      const force = store.consumeFreshImageGeneration()
      if ((!force && await restoreFromHistory()) || !isCurrentRun()) return

      await ensureRecord()
      if (!isCurrentRun()) return

      store.startGeneration()
      setError(null)

      await generateImagesPost(
        store.outline.pages,
        null,
        store.outline.raw,
        (event) => {
          if (!isCurrentRun()) return
          store.setTaskId(event.task_id)
          if (event.record_id && !store.recordId) store.setRecordId(event.record_id)
          store.setGenerationMessage(
            event.reused ? '已连接到正在进行的任务' : '任务已创建，正在等待图片服务处理',
            event.phase || event.status
          )
        },
        (event) => {
          if (!isCurrentRun()) return
          if (typeof event.total === 'number') store.progress.total = event.total
          if (typeof event.current === 'number') {
            store.progress.current = Math.min(event.current, store.progress.total)
          }
          store.setGenerationMessage(event.message, event.phase)

          if (event.index < 0) return
          const status = event.status === 'retrying' || event.phase?.includes('retry')
            ? 'retrying'
            : event.status === 'queued'
              ? 'queued'
              : 'generating'
          store.updateProgress(event.index, status)
        },
        (event) => {
          if (!isCurrentRun()) return
          if (event.image_url) store.updateProgress(event.index, 'done', event.image_url)
          store.setGenerationMessage(event.message, event.phase)
          if (typeof event.current === 'number') {
            store.progress.current = Math.min(event.current, store.progress.total)
          }
        },
        (event) => {
          if (!isCurrentRun()) return
          store.updateProgress(
            event.index,
            'error',
            undefined,
            formatErrorMessage(event.error || event.message || '图片生成失败', '图片生成失败')
          )
          store.setGenerationMessage(event.message, event.phase)
          if (typeof event.current === 'number') {
            store.progress.current = Math.min(event.current, store.progress.total)
          }
        },
        (event) => {
          if (!isCurrentRun()) return
          for (const image of store.images) {
            if (['queued', 'generating', 'retrying'].includes(image.status)) {
              store.updateProgress(image.index, 'error', undefined, '任务已结束，但该图片未生成')
            }
          }
          store.finishGeneration(event.task_id, event.failed || 0)

          if (!hasFailedImages.value) {
            redirectTimer.value = window.setTimeout(() => {
              if (isCurrentRun()) router.push('/result')
            }, 1000)
          }
        },
        (err) => {
          if (!isCurrentRun()) return

          const conflict = err as {
            existing_task_id?: string
            task_state?: { status?: string; phase?: string }
          }
          if (conflict?.existing_task_id) {
            store.setTaskId(conflict.existing_task_id)
            store.interruptPendingImages('已有图片任务正在后台进行，本页面未重复创建任务')
            const existingStatus = conflict.task_state?.phase || conflict.task_state?.status || '运行中'
            store.setGenerationMessage(
              `已有任务进行中（${existingStatus}），请稍后查看结果`,
              'existing_task'
            )
            setError(normalizeApiError(err, '已有任务进行中'))
            return
          }

          const streamCode = (err as { code?: string })?.code
          const normalized = normalizeApiError(err, '图片生成连接中断')
          store.interruptPendingImages(
            streamCode === 'STREAM_INCOMPLETE'
              ? '生成连接提前中断，任务可能仍在后台运行'
              : '无法继续获取生成状态，请稍后确认任务结果'
          )
          setError(normalized)
        },
        store.userImages.length > 0 ? store.userImages : undefined,
        store.topic,
        store.recordId,
        force,
        abortController.signal
      )
    })().finally(() => {
      if (token === runToken) {
        runningPromise = null
        abortController = null
      }
    })

    return runningPromise
  }

  function cleanupGenerationRunner() {
    isUnmounted = true
    runToken++
    abortController?.abort()
    abortController = null
    runningPromise = null
    if (redirectTimer.value !== null) {
      clearTimeout(redirectTimer.value)
      redirectTimer.value = null
    }
  }

  return {
    cleanupGenerationRunner,
    startGenerationFlow
  }
}
