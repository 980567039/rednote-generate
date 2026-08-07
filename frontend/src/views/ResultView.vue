<template>
  <div class="container">
    <div class="page-header">
      <div>
        <h1 class="page-title">创作完成</h1>
        <p class="page-subtitle">恭喜！你的小红书图文已生成完毕，共 {{ store.images.length }} 张</p>
      </div>
      <div class="result-actions-wrap">
        <div class="result-actions">
          <button class="btn btn-secondary result-back-btn" @click="startOver">
            再来一篇
          </button>
          <button class="btn btn-primary" @click="downloadAll">
            <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4"></path><polyline points="7 10 12 15 17 10"></polyline><line x1="12" y1="15" x2="12" y2="3"></line></svg>
            一键下载
          </button>
          <button
            class="btn btn-secondary publish-button"
            type="button"
            :disabled="!canPublish"
            :title="publishDisabledReason"
            @click="showPublishModal = true"
          >
            发布到小红书
          </button>
        </div>
        <p v-if="!canPublish" class="publish-disabled-hint">{{ publishDisabledReason }}</p>
      </div>
    </div>

    <ErrorCard
      v-if="error"
      :error="error"
      dismissible
      style="margin-bottom: 16px;"
      @dismiss="error = null"
    />

    <div class="card">
      <div class="grid-cols-4">
        <div v-for="image in store.images" :key="image.index" class="image-card group">
          <!-- Image Area -->
          <div
            v-if="image.url"
            style="position: relative; aspect-ratio: 3/4; overflow: hidden; cursor: pointer;"
            @click="viewImage(image.url)"
          >
            <img
              :src="image.url"
              :alt="`第 ${image.index + 1} 页`"
              style="width: 100%; height: 100%; object-fit: cover; transition: transform 0.3s;"
            />
            <!-- Regenerating Overlay -->
            <div v-if="regeneratingIndex === image.index" style="position: absolute; inset: 0; background: rgba(255,255,255,0.8); display: flex; flex-direction: column; align-items: center; justify-content: center; z-index: 10;">
               <div class="spinner" style="width: 24px; height: 24px; border-width: 2px; border-color: var(--primary); border-top-color: transparent;"></div>
               <span style="font-size: 12px; color: var(--primary); margin-top: 8px; font-weight: 600;">重绘中...</span>
            </div>

            <!-- Hover Overlay -->
            <div v-else class="hover-overlay">
              <button class="hover-action-btn" type="button" @click.stop="viewImage(image.url)">
                <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
                  <path d="M2 12s3.5-7 10-7 10 7 10 7-3.5 7-10 7S2 12 2 12z"></path>
                  <circle cx="12" cy="12" r="3"></circle>
                </svg>
                预览大图
              </button>
              <button class="hover-action-btn" type="button" @click.stop="openRegenerateDialog(image)">
                <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
                  <path d="M23 4v6h-6"></path>
                  <path d="M20.49 15a9 9 0 1 1-2.12-9.36L23 10"></path>
                </svg>
                重新生成
              </button>
              <button
                v-if="canCreatePattern(image)"
                class="hover-action-btn"
                type="button"
                :disabled="patternModalVisible || patternGeneratingIndex !== null"
                @click.stop="generatePattern(image)"
              >
                {{ patternGeneratingIndex === image.index ? '生成图纸中…' : '生成拼豆图纸' }}
              </button>
            </div>
          </div>
          <!-- Action Bar -->
          <div style="padding: 12px; border-top: 1px solid #f0f0f0; display: flex; justify-content: space-between; align-items: center;">
            <span style="font-size: 12px; color: var(--text-sub);">Page {{ image.index + 1 }}</span>
            <div style="display: flex; gap: 8px;">
              <button
                style="border: none; background: none; color: var(--text-sub); cursor: pointer; display: flex; align-items: center;"
                title="重新生成此图"
                @click="openRegenerateDialog(image)"
                :disabled="regeneratingIndex === image.index || isPatternImage(image)"
              >
                <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M23 4v6h-6"></path><path d="M1 20v-6h6"></path><path d="M3.51 9a9 9 0 0 1 14.85-3.36L23 10M1 14l4.64 4.36A9 9 0 0 0 20.49 15"></path></svg>
              </button>
              <button
                v-if="canCreatePattern(image)"
                style="border: none; background: none; color: var(--primary); cursor: pointer; font-size: 12px;"
                type="button"
                :disabled="patternModalVisible || patternGeneratingIndex !== null"
                @click="generatePattern(image)"
              >
                {{ patternGeneratingIndex === image.index ? '生成中…' : '拼豆图纸' }}
              </button>
              <button
                style="border: none; background: none; color: var(--primary); cursor: pointer; font-size: 12px;"
                @click="downloadOne(image)"
              >
                下载
              </button>
            </div>
          </div>
        </div>
      </div>
    </div>

    <!-- 标题、文案、标签生成区域 -->
    <ContentDisplay />

    <ImagePreviewModal
      :visible="Boolean(previewImage)"
      :src="previewImage?.src || ''"
      :alt="previewImage?.alt || ''"
      @close="previewImage = null"
    />
    <RegenerateImageModal
      :visible="Boolean(regenerateTarget)"
      :page-number="(regenerateTarget?.index ?? 0) + 1"
      :loading="regeneratingIndex !== null"
      @close="regenerateTarget = null"
      @confirm="confirmRegenerate"
    />
    <PublishModal
      :visible="showPublishModal"
      :record-id="store.recordId || ''"
      :titles="store.content.titles"
      :copywriting="store.content.copywriting"
      :tags="store.content.tags"
      :image-count="store.images.length"
      @close="showPublishModal = false"
    />
    <PatternGenerationModal
      :visible="patternModalVisible"
      :step="patternModalStep"
      :page-number="(patternTarget?.index ?? 0) + 1"
      :progress="patternProgress"
      :preview-url="patternPreviewUrl"
      :metadata="patternPending?.result.metadata ?? null"
      :error-message="patternErrorMessage"
      :is-refining="isRefiningPattern"
      :is-appending="isAppendingPattern"
      @close="cancelPatternFlow"
      @start="startAutomaticPattern"
      @refine="refinePatternWithPerler"
      @append="confirmPatternAppend"
    />
  </div>
</template>

<style scoped>
/* 确保图片预览区域正确填充 */
.image-card > div:first-child {
  flex: 1;
  display: flex;
  flex-direction: column;
}

.image-card:hover .hover-overlay {
  opacity: 1;
}
.image-card:hover img {
  transform: scale(1.05);
}

.result-back-btn {
  border: 1px solid var(--border-color);
  background: var(--bg-control);
  color: var(--text-main);
}

.hover-overlay {
  position: absolute;
  inset: 0;
  display: flex;
  align-items: center;
  justify-content: center;
  flex-wrap: wrap;
  gap: 10px;
  padding: 16px;
  background: rgba(0, 0, 0, 0.45);
  opacity: 0;
  transition: opacity 0.2s;
}

.hover-action-btn {
  display: flex;
  align-items: center;
  gap: 6px;
  padding: 8px 14px;
  border: none;
  border-radius: 6px;
  background: var(--bg-control);
  color: var(--text-main);
  cursor: pointer;
  font-size: 13px;
  transition: background-color 0.2s, color 0.2s, transform 0.2s;
}

.hover-action-btn:hover {
  background: var(--primary);
  color: white;
  transform: translateY(-1px);
}

.publish-button { white-space: nowrap; }
.result-actions-wrap { display: grid; justify-items: end; gap: 6px; }
.result-actions { display: flex; flex-wrap: wrap; justify-content: flex-end; gap: 12px; }
.publish-disabled-hint { margin: 0; color: var(--text-secondary); font-size: 12px; }
</style>

<script setup lang="ts">
import { computed, onUnmounted, ref, shallowRef } from 'vue'
import { useRouter } from 'vue-router'
import { useGeneratorStore } from '../stores/generator'
import { appendPatternPage, regenerateImage } from '../api'
import ContentDisplay from '../components/result/ContentDisplay.vue'
import ErrorCard from '../components/common/ErrorCard.vue'
import ImagePreviewModal from '../components/common/ImagePreviewModal.vue'
import RegenerateImageModal from '../components/common/RegenerateImageModal.vue'
import PublishModal from '../components/result/PublishModal.vue'
import PatternGenerationModal from '../components/result/PatternGenerationModal.vue'
import { normalizeApiError, type AppError } from '../utils/errors'
import {
  generatePatternAutomatically,
  generatePatternWithPerler,
  PerlerBridgeCancelledError,
  type PerlerAutoJob,
  type PerlerPatternResult,
  type PerlerProgressUpdate,
} from '../integrations/perlerBridge'
import { DEFAULT_PERLER_SETTINGS, type PerlerPatternSettings } from '../integrations/perlerSettings'

const router = useRouter()
const store = useGeneratorStore()
const regeneratingIndex = ref<number | null>(null)
const error = ref<AppError | null>(null)
const previewImage = ref<{ src: string; alt: string } | null>(null)
const regenerateTarget = ref<any | null>(null)
const showPublishModal = ref(false)
const patternGeneratingIndex = ref<number | null>(null)
const isAppendingPattern = ref(false)
const isRefiningPattern = ref(false)
const patternPending = ref<{ sourceImageIndex: number; result: PerlerPatternResult } | null>(null)
const patternTarget = ref<{ index: number; url: string } | null>(null)
const patternModalStep = ref<'config' | 'progress' | 'preview'>('config')
const patternProgress = ref<PerlerProgressUpdate | null>(null)
const patternPreviewUrl = ref('')
const patternErrorMessage = ref('')
const patternSettings = ref<PerlerPatternSettings>({ ...DEFAULT_PERLER_SETTINGS })
const activeAutoPatternJob = shallowRef<PerlerAutoJob | null>(null)
const patternModalVisible = computed(() => patternTarget.value !== null)
const canPublish = computed(() => Boolean(
  store.recordId
  && store.content.status === 'done'
  && store.images.length > 0
  && store.images.every(image => image.status === 'done' && Boolean(image.url))
))

const publishDisabledReason = computed(() => {
  if (!store.recordId) return '当前作品还没有历史记录，无法发布'
  if (store.content.status !== 'done') return '请先生成标题、正文和标签'
  if (!store.images.length || !store.images.every(image => image.status === 'done' && Boolean(image.url))) return '请等待全部图片生成完成'
  return ''
})

function isPatternImage(image: { index: number }) {
  return store.outline.pages.find(page => page.index === image.index)?.type === 'pattern'
}

function canCreatePattern(image: { index: number; url: string }) {
  return Boolean(store.recordId && image.url && !isPatternImage(image))
}

const viewImage = (url: string) => {
  const image = store.images.find(item => item.url === url)
  previewImage.value = {
    src: url,
    alt: image ? `第 ${image.index + 1} 页大图` : '图片大图预览'
  }
}

const startOver = () => {
  store.reset()
  router.push('/')
}

const downloadOne = (image: any) => {
  if (image.url) {
    const link = document.createElement('a')
    const baseUrl = image.url.split('?')[0]
    link.href = baseUrl + '?thumbnail=false'
    link.download = `rednote_page_${image.index + 1}.png`
    link.click()
  }
}

const downloadAll = () => {
  if (store.recordId) {
    const link = document.createElement('a')
    link.href = `/api/history/${store.recordId}/download`
    link.click()
  } else {
    store.images.forEach((image, index) => {
      if (image.url) {
        setTimeout(() => {
          const link = document.createElement('a')
          const baseUrl = image.url.split('?')[0]
          link.href = baseUrl + '?thumbnail=false'
          link.download = `rednote_page_${image.index + 1}.png`
          link.click()
        }, index * 300)
      }
    })
  }
}

const generatePattern = (image: { index: number; url: string }) => {
  if (
    !store.recordId
    || !canCreatePattern(image)
    || patternGeneratingIndex.value !== null
    || patternModalVisible.value
  ) return
  patternTarget.value = image
  patternModalStep.value = 'config'
  patternProgress.value = null
  patternErrorMessage.value = ''
}

function revokePatternPreview() {
  if (!patternPreviewUrl.value) return
  URL.revokeObjectURL(patternPreviewUrl.value)
  patternPreviewUrl.value = ''
}

function setPatternPreview(result: PerlerPatternResult) {
  revokePatternPreview()
  patternPreviewUrl.value = URL.createObjectURL(result.pattern)
}

const startAutomaticPattern = async (settings: PerlerPatternSettings) => {
  const target = patternTarget.value
  if (!target || !store.recordId || activeAutoPatternJob.value || isRefiningPattern.value) return
  patternSettings.value = { ...settings }
  patternModalStep.value = 'progress'
  patternProgress.value = { stage: 'connect', completed: 0, total: 1 }
  patternGeneratingIndex.value = target.index
  patternErrorMessage.value = ''
  error.value = null
  let job: PerlerAutoJob | null = null
  try {
    job = generatePatternAutomatically({
      recordId: store.recordId,
      imageIndex: target.index,
      imageUrl: `${target.url.split('?')[0]}?thumbnail=false`,
      fileName: `redink-page-${target.index + 1}.png`,
      settings,
      onReady: () => {
        patternProgress.value = { stage: 'prepare', completed: 0, total: 1 }
      },
      onProgress: progress => {
        patternProgress.value = progress
      },
    })
    activeAutoPatternJob.value = job
    const result = await job.result
    if (activeAutoPatternJob.value !== job || patternTarget.value?.index !== target.index) return
    patternPending.value = { sourceImageIndex: target.index, result }
    setPatternPreview(result)
    patternModalStep.value = 'preview'
  } catch (reason: unknown) {
    if (reason instanceof PerlerBridgeCancelledError) return
    if (job && activeAutoPatternJob.value !== job) return
    patternModalStep.value = 'config'
    patternErrorMessage.value = reason instanceof Error ? reason.message : '生成拼豆图纸失败。'
    error.value = normalizeApiError(reason, '生成拼豆图纸失败')
  } finally {
    if (!job || activeAutoPatternJob.value === job) {
      activeAutoPatternJob.value = null
      patternGeneratingIndex.value = null
    }
  }
}

const cancelPatternFlow = () => {
  if (isAppendingPattern.value || isRefiningPattern.value) return
  activeAutoPatternJob.value?.cancel()
  activeAutoPatternJob.value = null
  patternGeneratingIndex.value = null
  patternPending.value = null
  patternTarget.value = null
  patternModalStep.value = 'config'
  patternProgress.value = null
  patternErrorMessage.value = ''
  revokePatternPreview()
}

const refinePatternWithPerler = async () => {
  const pending = patternPending.value
  const target = patternTarget.value
  if (!pending || !target || !store.recordId || isRefiningPattern.value || isAppendingPattern.value) return
  isRefiningPattern.value = true
  patternGeneratingIndex.value = target.index
  patternErrorMessage.value = ''
  error.value = null
  try {
    const result = await generatePatternWithPerler({
      recordId: store.recordId,
      imageIndex: target.index,
      imageUrl: `${target.url.split('?')[0]}?thumbnail=false`,
      fileName: `redink-page-${target.index + 1}.png`,
      settings: patternSettings.value,
    })
    if (patternTarget.value?.index !== target.index) return
    patternPending.value = { sourceImageIndex: target.index, result }
    setPatternPreview(result)
  } catch (reason: unknown) {
    patternErrorMessage.value = reason instanceof Error ? reason.message : 'Perler 精修失败，自动生成的预览已保留。'
    error.value = normalizeApiError(reason, 'Perler 精修失败，自动生成的预览已保留')
  } finally {
    isRefiningPattern.value = false
    patternGeneratingIndex.value = null
  }
}

const confirmPatternAppend = async () => {
  const pending = patternPending.value
  if (!pending || !store.recordId || isAppendingPattern.value) return
  isAppendingPattern.value = true
  error.value = null
  try {
    const response = await appendPatternPage(store.recordId, {
      requestId: pending.result.requestId,
      sourceImageIndex: pending.sourceImageIndex,
      columns: pending.result.metadata.columns,
      rows: pending.result.metadata.rows,
      usedColors: pending.result.metadata.usedColors,
      pattern: pending.result.pattern
    })
    if (!response.success || !response.filename || !response.record?.outline.pages) {
      error.value = normalizeApiError(response.error || response.error_message || '服务器未确认追加', '追加拼豆图纸失败')
      return
    }
    const page = response.record.outline.pages[response.page_index ?? response.record.outline.pages.length - 1]
    if (!page || page.type !== 'pattern') {
      error.value = normalizeApiError('服务器返回的图纸页面无效', '追加拼豆图纸失败')
      return
    }
    store.appendPatternImage(page, response.filename)
    error.value = null
    patternPending.value = null
    patternTarget.value = null
    patternModalStep.value = 'config'
    patternProgress.value = null
    patternErrorMessage.value = ''
    revokePatternPreview()
  } catch (reason: any) {
    error.value = normalizeApiError(reason, '追加拼豆图纸失败')
  } finally {
    isAppendingPattern.value = false
  }
}

onUnmounted(() => {
  activeAutoPatternJob.value?.cancel()
  activeAutoPatternJob.value = null
  revokePatternPreview()
})

const openRegenerateDialog = (image: any) => {
  if (regeneratingIndex.value === null) regenerateTarget.value = image
}

const confirmRegenerate = async (revisionRequest: string) => {
  if (regenerateTarget.value) await handleRegenerate(regenerateTarget.value, revisionRequest)
}

const handleRegenerate = async (image: any, revisionRequest = '') => {
  if (regeneratingIndex.value !== null) return
  if (!store.taskId) {
    error.value = normalizeApiError('缺少图片任务信息，无法重新生成。', '无法重新生成')
    regenerateTarget.value = null
    return
  }

  regeneratingIndex.value = image.index
  try {
    // Find the page content from outline
    const pageContent = store.outline.pages.find(p => p.index === image.index)
    if (!pageContent) {
       error.value = normalizeApiError('无法找到对应页面的内容', '无法重新生成')
       return
    }

    // 构建上下文信息
    const context = {
      fullOutline: store.outline.raw || '',
      userTopic: store.topic || '',
      recordId: store.recordId,
      revisionRequest,
      series: store.getSeriesRequestContext()
    }

    const result = await regenerateImage(store.taskId, pageContent, true, context)
    if (result.success && result.image_url) {
       const newUrl = result.image_url
       store.updateImage(image.index, newUrl)
    } else {
       error.value = normalizeApiError(result.error || result.error_message || '重绘失败', '重绘失败')
    }
  } catch (e: any) {
    error.value = normalizeApiError(e, '重绘失败')
  } finally {
    regeneratingIndex.value = null
    regenerateTarget.value = null
  }
}
</script>
