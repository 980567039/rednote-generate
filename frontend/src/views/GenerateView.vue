<template>
  <div class="container">
    <div class="page-header">
      <div>
        <h1 class="page-title">生成结果</h1>
        <p class="page-subtitle">
          <span v-if="isGenerating">{{ generationMessage }}</span>
          <span v-else-if="interruptedCount > 0">状态连接已中断，任务可能仍在后台运行</span>
          <span v-else-if="hasFailedImages">{{ failedCount }} 张图片生成失败，可点击重试</span>
          <span v-else>全部 {{ store.progress.total }} 张图片生成完成</span>
        </p>
      </div>
      <div style="display: flex; gap: 10px;">
        <button
          v-if="hasFailedImages && !isGenerating"
          class="btn btn-primary"
          @click="retryAllFailed"
          :disabled="isRetrying"
        >
          {{ isRetrying ? '补全中...' : '一键补全失败图片' }}
        </button>
        <button class="btn" @click="router.push('/outline')" style="border:1px solid var(--border-color)">
          返回大纲
        </button>
      </div>
    </div>

    <div class="card">
      <div style="margin-bottom: 20px; display: flex; justify-content: space-between; align-items: center;">
        <span style="font-weight: 600;">生成进度</span>
        <span style="color: var(--primary); font-weight: 600;">{{ Math.round(progressPercent) }}%</span>
      </div>
      <div class="progress-container">
        <div class="progress-bar" :style="{ width: progressPercent + '%' }" />
      </div>

      <div class="generation-summary">
        <span>阶段：{{ phaseText }}</span>
        <span>成功 {{ completedCount }}</span>
        <span>失败 {{ failedCount }}</span>
        <span v-if="activeCount > 0">处理中 {{ activeCount }}</span>
        <span v-if="queuedCount > 0">排队 {{ queuedCount }}</span>
        <span v-if="interruptedCount > 0">待确认 {{ interruptedCount }}</span>
      </div>

      <ErrorCard
        v-if="error"
        :error="error"
        dismissible
        style="margin-top: 18px;"
        @dismiss="error = null"
      />

      <div class="grid-cols-4" style="margin-top: 40px;">
        <div v-for="image in store.images" :key="image.index" class="image-card">
          <!-- 图片展示区域 -->
          <div
            v-if="image.url && image.status === 'done'"
            class="image-preview"
            @click="openImagePreview(image.url, image.index)"
          >
            <img :src="image.url" :alt="`第 ${image.index + 1} 页`" />
            <!-- 图片操作（悬停显示） -->
            <div class="image-overlay">
              <button
                class="overlay-btn"
                type="button"
                @click.stop="openImagePreview(image.url, image.index)"
              >
                <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
                  <path d="M2 12s3.5-7 10-7 10 7 10 7-3.5 7-10 7S2 12 2 12z"></path>
                  <circle cx="12" cy="12" r="3"></circle>
                </svg>
                预览大图
              </button>
              <button
                class="overlay-btn"
                type="button"
                @click.stop="regenerateImage(image.index)"
              >
                <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
                  <path d="M23 4v6h-6"></path>
                  <path d="M20.49 15a9 9 0 1 1-2.12-9.36L23 10"></path>
                </svg>
                重新生成
              </button>
            </div>
          </div>

          <!-- 生成中/重试中状态 -->
          <div v-else-if="image.status === 'generating' || image.status === 'retrying'" class="image-placeholder">
            <div class="spinner"></div>
            <div class="status-text">{{ image.status === 'retrying' ? '重试中...' : '生成中...' }}</div>
          </div>

          <!-- 排队状态：只有服务端开始处理该页后才显示生成中 -->
          <div v-else-if="image.status === 'queued'" class="image-placeholder queued-placeholder">
            <div class="queue-icon">···</div>
            <div class="status-text">排队中</div>
          </div>

          <!-- 失败状态 -->
          <div v-else-if="image.status === 'error'" class="image-placeholder error-placeholder">
            <div class="error-icon">!</div>
            <div class="status-text">生成失败</div>
            <div v-if="image.error" class="image-error-text">{{ image.error }}</div>
            <button
              class="retry-btn"
              @click="retrySingleImage(image.index)"
              :disabled="isRetrying"
            >
              点击重试
            </button>
          </div>

          <div v-else-if="image.status === 'interrupted'" class="image-placeholder interrupted-placeholder">
            <div class="interrupted-icon">?</div>
            <div class="status-text">状态待确认</div>
            <div v-if="image.error" class="image-error-text">{{ image.error }}</div>
          </div>

          <!-- 等待中状态 -->
          <div v-else class="image-placeholder">
            <div class="status-text">等待中</div>
          </div>

          <!-- 底部信息栏 -->
          <div class="image-footer">
            <span class="page-label">Page {{ image.index + 1 }}</span>
            <span class="status-badge" :class="image.status">
              {{ getStatusText(image.status) }}
            </span>
          </div>
        </div>
      </div>
    </div>

    <ImagePreviewModal
      :visible="Boolean(previewImage)"
      :src="previewImage?.src || ''"
      :alt="previewImage?.alt || ''"
      @close="previewImage = null"
    />
  </div>
</template>

<script setup lang="ts">
import { ref, computed, onMounted, onUnmounted } from 'vue'
import { useRouter } from 'vue-router'
import { useGeneratorStore } from '../stores/generator'
import ErrorCard from '../components/common/ErrorCard.vue'
import ImagePreviewModal from '../components/common/ImagePreviewModal.vue'
import { useGenerationRunner } from '../composables/useGenerationRunner'
import { useImageRetry } from '../composables/useImageRetry'
import type { AppError } from '../utils/errors'

const router = useRouter()
const store = useGeneratorStore()

const error = ref<AppError | null>(null)
const previewImage = ref<{ src: string; alt: string } | null>(null)

function openImagePreview(src: string, index: number) {
  previewImage.value = {
    src,
    alt: `第 ${index + 1} 页大图`
  }
}

const isGenerating = computed(() => store.progress.status === 'generating')

const progressPercent = computed(() => {
  if (store.progress.total === 0) return 0
  return ((completedCount.value + failedCount.value) / store.progress.total) * 100
})

const hasFailedImages = computed(() => store.images.some(img => img.status === 'error'))

const failedCount = computed(() => store.images.filter(img => img.status === 'error').length)
const completedCount = computed(() => store.images.filter(img => img.status === 'done').length)
const queuedCount = computed(() => store.images.filter(img => img.status === 'queued').length)
const activeCount = computed(() => store.images.filter(img => ['generating', 'retrying'].includes(img.status)).length)
const interruptedCount = computed(() => store.images.filter(img => img.status === 'interrupted').length)

const phaseText = computed(() => {
  const labels: Record<string, string> = {
    accepted: '任务已接收',
    queued: '等待处理',
    cover: '生成封面',
    content: '生成内容页',
    circuit_breaker: '已停止剩余页面',
    cached: '读取已有结果',
    waiting: '等待处理',
    rate_limit_wait: '等待请求额度',
    generating: '请求图片模型',
    requesting: '请求图片模型',
    upstream: '图片模型处理中',
    retrying: '自动重试',
    saving: '保存图片',
    finished: '已结束',
    interrupted: '连接中断',
    existing_task: '已有任务运行中'
  }
  return labels[store.progress.phase || ''] || store.progress.phase || (isGenerating.value ? '处理中' : '已结束')
})

const generationMessage = computed(() => store.progress.message || '任务处理中，请稍候')

const getStatusText = (status: string) => {
  const texts: Record<string, string> = {
    generating: '生成中',
    done: '已完成',
    error: '失败',
    retrying: '重试中',
    queued: '排队中',
    interrupted: '待确认'
  }
  return texts[status] || '等待中'
}

function setError(nextError: AppError | null) {
  error.value = nextError
}

const {
  isRetrying,
  regenerateImage,
  retryAllFailed,
  retrySingleImage
} = useImageRetry(setError)

const {
  cleanupGenerationRunner,
  startGenerationFlow
} = useGenerationRunner(hasFailedImages, setError)

onMounted(startGenerationFlow)
onUnmounted(cleanupGenerationRunner)
</script>

<style scoped>
.image-preview {
  aspect-ratio: 3/4;
  overflow: hidden;
  position: relative;
  cursor: pointer;
  flex: 1; /* 填充卡片剩余空间 */
}

.image-preview img {
  width: 100%;
  height: 100%;
  object-fit: cover;
}

.image-overlay {
  position: absolute;
  top: 0;
  left: 0;
  right: 0;
  bottom: 0;
  background: rgba(0, 0, 0, 0.5);
  display: flex;
  align-items: center;
  justify-content: center;
  flex-wrap: wrap;
  gap: 10px;
  opacity: 0;
  transition: opacity 0.2s;
}

.image-preview:hover .image-overlay {
  opacity: 1;
}

.overlay-btn {
  display: flex;
  align-items: center;
  gap: 6px;
  padding: 8px 16px;
  background: white;
  border: none;
  border-radius: 6px;
  cursor: pointer;
  font-size: 13px;
  color: #333;
  transition: all 0.2s;
}

.overlay-btn:hover {
  background: var(--primary);
  color: white;
}

.overlay-btn:disabled {
  opacity: 0.5;
  cursor: not-allowed;
}

.image-placeholder {
  aspect-ratio: 3/4;
  background: #f9f9f9;
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  gap: 10px;
  flex: 1; /* 填充卡片剩余空间 */
  min-height: 240px; /* 确保有最小高度 */
}

.error-placeholder {
  background: #fff5f5;
}

.queued-placeholder {
  background: #fafafa;
}

.queue-icon {
  color: var(--primary);
  font-size: 24px;
  font-weight: 700;
  letter-spacing: 3px;
}

.interrupted-placeholder {
  background: #fffbe6;
}

.interrupted-icon {
  width: 40px;
  height: 40px;
  border-radius: 50%;
  background: #faad14;
  color: white;
  display: flex;
  align-items: center;
  justify-content: center;
  font-size: 22px;
  font-weight: bold;
}

.error-icon {
  width: 40px;
  height: 40px;
  border-radius: 50%;
  background: #ff4d4f;
  color: white;
  display: flex;
  align-items: center;
  justify-content: center;
  font-size: 24px;
  font-weight: bold;
}

.status-text {
  font-size: 13px;
  color: var(--text-sub);
}

.image-error-text {
  max-width: 85%;
  color: #991b1b;
  font-size: 12px;
  line-height: 1.45;
  display: -webkit-box;
  -webkit-line-clamp: 3;
  -webkit-box-orient: vertical;
  overflow: hidden;
}

.retry-btn {
  margin-top: 8px;
  padding: 6px 16px;
  background: var(--primary);
  color: white;
  border: none;
  border-radius: 4px;
  cursor: pointer;
  font-size: 12px;
  transition: all 0.2s;
}

.retry-btn:hover {
  opacity: 0.9;
  transform: translateY(-1px);
}

.retry-btn:disabled {
  opacity: 0.5;
  cursor: not-allowed;
  transform: none;
}

.image-footer {
  padding: 12px;
  border-top: 1px solid #f0f0f0;
  display: flex;
  justify-content: space-between;
  align-items: center;
}

.page-label {
  font-size: 12px;
  color: var(--text-sub);
}

.status-badge {
  font-size: 10px;
  padding: 2px 6px;
  border-radius: 4px;
}

.status-badge.done {
  background: #E6F7ED;
  color: #52C41A;
}

.status-badge.generating,
.status-badge.retrying {
  background: #E6F4FF;
  color: #1890FF;
}

.status-badge.error {
  background: #FFF1F0;
  color: #FF4D4F;
}

.status-badge.queued {
  background: #F5F5F5;
  color: #666;
}

.status-badge.interrupted {
  background: #FFFBE6;
  color: #D48806;
}

.generation-summary {
  margin-top: 12px;
  display: flex;
  flex-wrap: wrap;
  gap: 8px 18px;
  color: var(--text-sub);
  font-size: 12px;
}

.spinner {
  width: 24px;
  height: 24px;
  border: 2px solid var(--primary);
  border-top-color: transparent;
  border-radius: 50%;
  animation: spin 1s linear infinite;
}

@keyframes spin {
  to {
    transform: rotate(360deg);
  }
}
</style>
