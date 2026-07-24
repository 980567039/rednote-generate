<template>
  <div class="container home-container">
    <!-- 图片网格轮播背景 -->
    <ShowcaseBackground />

    <!-- Hero Area -->
    <div class="hero-section">
      <div class="hero-content">
        <div class="brand-pill">
          <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" style="margin-right: 6px;"><path d="m12 3-1.912 5.813a2 2 0 0 1-1.275 1.275L3 12l5.813 1.912a2 2 0 0 1 1.275 1.275L12 21l1.912-5.813a2 2 0 0 1 1.275-1.275L21 12l-5.813-1.912a2 2 0 0 1-1.275-1.275L12 3Z"/></svg>
          AI 图文创作助手
        </div>
        <div class="platform-slogan">
          让传播不再需要门槛，让创作从未如此简单
        </div>
        <h1 class="page-title">灵感一触即发</h1>
        <p class="page-subtitle">输入你的创意主题，让 AI 帮你生成爆款标题、正文和封面图</p>
      </div>

      <!-- 主题输入组合框 -->
      <ComposerInput
        ref="composerRef"
        v-model="topic"
        v-model:creative-brief="creativeBrief"
        :loading="loading"
        @generate="handleGenerate"
        @imagesChange="handleImagesChange"
      />

      <div class="structure-selector" role="group" aria-label="页数与创作结构">
        <span class="structure-label">页数与结构</span>
        <button
          v-for="preset in structurePresets"
          :key="preset.id"
          class="structure-option"
          :class="{ active: selectedStructure === preset.id }"
          type="button"
          :aria-pressed="selectedStructure === preset.id"
          :disabled="loading"
          @click="selectedStructure = preset.id"
        >
          <span>{{ preset.label }}</span>
          <small>{{ preset.description }}</small>
        </button>
      </div>
    </div>

    <section class="inspiration-section" aria-labelledby="inspiration-title">
      <div class="inspiration-header">
        <div>
          <h2 id="inspiration-title">今日灵感</h2>
          <p>本地演示主题，用于验证选题与生成流程</p>
        </div>
        <button class="refresh-trends" type="button" @click="showNextTrends" :disabled="trends.length <= trendPageSize">
          换一批
        </button>
      </div>
      <div v-if="trendLoading" class="trend-loading">加载灵感中...</div>
      <div v-else class="trend-grid">
        <button
          v-for="trend in displayedTrends"
          :key="trend.rank"
          class="trend-card"
          type="button"
          @click="selectTrend(trend.topic)"
        >
          <span class="trend-rank">{{ trend.rank }}</span>
          <span class="trend-card-content">
            <span class="trend-category">{{ trend.category }}</span>
            <span class="trend-title">{{ trend.title }}</span>
          </span>
          <span class="trend-use">使用主题</span>
        </button>
      </div>
    </section>

    <ErrorCard
      v-if="error"
      class="home-error"
      :error="error"
      dismissible
      @dismiss="error = null"
    />
  </div>
</template>

<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import { useRouter } from 'vue-router'
import { useGeneratorStore } from '../stores/generator'
import { generateOutline, createHistory, getTrends, type TrendItem } from '../api'
import { normalizeApiError, type AppError } from '../utils/errors'

// 引入组件
import ShowcaseBackground from '../components/home/ShowcaseBackground.vue'
import ComposerInput from '../components/home/ComposerInput.vue'
import ErrorCard from '../components/common/ErrorCard.vue'

const router = useRouter()
const store = useGeneratorStore()

// 状态
const topic = ref('')
const creativeBrief = ref('')
const loading = ref(false)
const error = ref<AppError | null>(null)
const composerRef = ref<InstanceType<typeof ComposerInput> | null>(null)
type StructurePresetId = 'standard' | 'comparison_two' | 'comparison_four'

const selectedStructure = ref<StructurePresetId>('standard')
const structurePresets: Array<{
  id: StructurePresetId
  label: string
  description: string
  instruction: string
}> = [
  {
    id: 'standard',
    label: '默认 5 页',
    description: '封面 + 内容 + 总结',
    instruction: '按常规图文结构生成；用户未指定页数时默认生成 5 页，第一页为封面。'
  },
  {
    id: 'comparison_two',
    label: '前后对比 2 页',
    description: '之前 / 之后',
    instruction: '严格只生成 2 页，不生成封面、总结或额外页面。第 1 页呈现“之前”，第 2 页呈现“之后”；两页采用并列对比、统一风格。'
  },
  {
    id: 'comparison_four',
    label: '完整对比 4 页',
    description: '封面 + 前后 + 总结',
    instruction: '严格生成 4 页：第 1 页封面，第 2 页呈现“之前”，第 3 页呈现“之后”，第 4 页总结变化；不添加额外页面。'
  }
]
const trends = ref<TrendItem[]>([])
const trendLoading = ref(true)
const trendPage = ref(0)
const trendPageSize = 3

const displayedTrends = computed(() => {
  if (trends.value.length === 0) return []
  const start = (trendPage.value * trendPageSize) % trends.value.length
  return Array.from({ length: Math.min(trendPageSize, trends.value.length) }, (_, offset) => (
    trends.value[(start + offset) % trends.value.length]
  ))
})

async function loadTrends() {
  trendLoading.value = true
  try {
    const response = await getTrends()
    if (response.success) trends.value = response.trends
  } catch {
    // 灵感区不应阻断创作流程；接口不可用时保持为空。
  } finally {
    trendLoading.value = false
  }
}

function showNextTrends() {
  trendPage.value = (trendPage.value + 1) % Math.ceil(trends.value.length / trendPageSize)
}

function selectTrend(selectedTopic: string) {
  topic.value = selectedTopic
}

function topicForSelectedStructure(rawTopic: string, brief: string) {
  const preset = structurePresets.find(item => item.id === selectedStructure.value)
  const creativeBrief = brief.trim()
  const briefInstruction = creativeBrief ? `\n\n【补充创作要求】${creativeBrief}` : ''
  return `${rawTopic}${briefInstruction}\n\n【创作结构要求】${preset?.instruction || structurePresets[0].instruction}`
}

onMounted(loadTrends)

// 上传的图片文件
const uploadedImageFiles = ref<File[]>([])

/**
 * 处理图片变化
 */
function handleImagesChange(images: File[]) {
  uploadedImageFiles.value = images
}

/**
 * 生成大纲
 */
async function handleGenerate() {
  if (!topic.value.trim()) return

  loading.value = true
  error.value = null

  try {
    const imageFiles = uploadedImageFiles.value

    const rawTopic = topic.value.trim()
    const result = await generateOutline(
      topicForSelectedStructure(rawTopic, creativeBrief.value),
      imageFiles.length > 0 ? imageFiles : undefined
    )

    if (result.success && result.pages) {
      // 设置主题和大纲到 store
      store.setTopic(rawTopic)
      store.setOutline(result.outline || '', result.pages)

      // 大纲生成成功后，立即创建历史记录
      // 这样即使用户刷新页面或关闭浏览器，大纲也不会丢失
      try {
        const historyResult = await createHistory(
          rawTopic,
          {
            raw: result.outline || '',
            pages: result.pages
          }
        )

        // 保存历史记录 ID 到 store，后续生成正文和图片时会使用
        if (historyResult.success && historyResult.record_id) {
          store.setRecordId(historyResult.record_id)
        } else {
          // 创建历史记录失败，记录错误但不阻断流程
          console.error('创建历史记录失败:', historyResult.error || '未知错误')
          store.setRecordId(null)
        }
      } catch (err: any) {
        // 创建历史记录异常，记录错误但不阻断流程
        console.error('创建历史记录异常:', err.message || err)
        store.setRecordId(null)
      }

      // 保存用户上传的图片到 store
      if (imageFiles.length > 0) {
        store.userImages = imageFiles
      } else {
        store.userImages = []
      }

      // 清理 ComposerInput 的预览
      composerRef.value?.clearPreviews()
      uploadedImageFiles.value = []

      router.push('/outline')
    } else {
      error.value = normalizeApiError(result.error || result.error_message || '生成大纲失败', '生成大纲失败')
    }
  } catch (err: any) {
    error.value = normalizeApiError(err, '生成大纲失败')
  } finally {
    loading.value = false
  }
}
</script>

<style scoped>
.home-container {
  max-width: 1100px;
  padding-top: 10px;
  position: relative;
  z-index: 1;
}

/* Hero Section */
.hero-section {
  text-align: center;
  margin-bottom: 40px;
  padding: 50px 60px;
  animation: fadeIn 0.6s ease-out;
  background: var(--bg-card);
  border-radius: 24px;
  box-shadow: var(--shadow-md);
  backdrop-filter: blur(10px);
}

.hero-content {
  margin-bottom: 36px;
}

.brand-pill {
  display: inline-block;
  padding: 6px 16px;
  background: rgba(255, 36, 66, 0.08);
  color: var(--primary);
  border-radius: 100px;
  font-size: 13px;
  font-weight: 600;
  margin-bottom: 20px;
  letter-spacing: 0.5px;
}

.platform-slogan {
  font-size: 20px;
  font-weight: 600;
  color: var(--text-main);
  margin-bottom: 24px;
  line-height: 1.6;
  letter-spacing: 0.5px;
}

.page-subtitle {
  font-size: 16px;
  color: var(--text-sub);
  margin-top: 12px;
}

/* Page Footer */
.page-footer {
  text-align: center;
  padding: 24px 0 16px;
  margin-top: 20px;
}

.footer-copyright {
  font-size: 15px;
  color: #333;
  font-weight: 500;
  margin-bottom: 6px;
}

.footer-copyright a {
  color: var(--primary);
  text-decoration: none;
  font-weight: 600;
}

.footer-copyright a:hover {
  text-decoration: underline;
}

.footer-license {
  font-size: 13px;
  color: #999;
}

.footer-license a {
  color: #666;
  text-decoration: none;
}

.footer-license a:hover {
  color: var(--primary);
}

.footer-tip {
  font-size: 14px;
  color: #666;
  margin-bottom: 12px;
}

.footer-tip a {
  color: var(--primary);
  text-decoration: none;
  font-weight: 600;
}

.footer-tip a:hover {
  text-decoration: underline;
}

.home-error {
  position: fixed;
  bottom: 32px;
  left: 50%;
  transform: translateX(-50%);
  width: min(720px, calc(100vw - 32px));
  z-index: 1000;
  animation: slideUp 0.3s ease-out;
}

.structure-selector {
  display: flex;
  align-items: stretch;
  justify-content: center;
  flex-wrap: wrap;
  gap: 8px;
  margin: 14px auto 0;
}

.structure-label {
  display: flex;
  align-items: center;
  padding-right: 4px;
  color: var(--text-sub);
  font-size: 13px;
}

.structure-option {
  display: flex;
  min-width: 126px;
  flex-direction: column;
  align-items: flex-start;
  gap: 2px;
  padding: 9px 12px;
  border: 1px solid var(--border-color);
  border-radius: 10px;
  color: var(--text-main);
  background: var(--bg-card);
  font: inherit;
  font-size: 13px;
  cursor: pointer;
  transition: border-color 0.2s ease, background 0.2s ease, color 0.2s ease;
}

.structure-option small {
  color: var(--text-secondary);
  font-size: 11px;
}

.structure-option:hover:not(:disabled),
.structure-option.active {
  border-color: var(--primary);
  background: var(--primary-light);
  color: var(--primary);
}

.structure-option:disabled {
  cursor: default;
  opacity: 0.65;
}

.inspiration-section {
  position: relative;
  margin: 0 auto 40px;
  padding: 24px;
  max-width: 920px;
  border: 1px solid var(--border-color);
  border-radius: 20px;
  background: var(--bg-card);
  box-shadow: var(--shadow-sm);
}

.inspiration-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 16px;
  margin-bottom: 18px;
}

.inspiration-header h2 {
  margin: 0 0 3px;
  font-size: 19px;
  color: var(--text-main);
}

.inspiration-header p,
.trend-loading {
  margin: 0;
  font-size: 13px;
  color: var(--text-sub);
}

.refresh-trends {
  padding: 7px 12px;
  border: 1px solid var(--border-color);
  border-radius: 8px;
  color: var(--text-sub);
  background: var(--bg-card);
  cursor: pointer;
}

.refresh-trends:disabled {
  opacity: 0.45;
  cursor: default;
}

.trend-grid {
  display: grid;
  grid-template-columns: repeat(3, minmax(0, 1fr));
  gap: 12px;
}

.trend-card {
  display: flex;
  min-width: 0;
  padding: 14px;
  gap: 10px;
  border: 1px solid var(--border-color);
  border-radius: 12px;
  text-align: left;
  color: var(--text-main);
  background: var(--bg-subtle, #fafafa);
  cursor: pointer;
  transition: transform 0.2s ease, border-color 0.2s ease, box-shadow 0.2s ease;
}

.trend-card:hover {
  transform: translateY(-2px);
  border-color: var(--primary);
  box-shadow: var(--shadow-sm);
}

.trend-rank {
  color: var(--primary);
  font-weight: 700;
  font-size: 18px;
  line-height: 1.2;
}

.trend-card-content {
  display: flex;
  min-width: 0;
  flex: 1;
  flex-direction: column;
  gap: 5px;
}

.trend-category {
  font-size: 12px;
  color: var(--primary);
}

.trend-title {
  display: -webkit-box;
  overflow: hidden;
  color: var(--text-main);
  font-size: 14px;
  line-height: 1.45;
  -webkit-box-orient: vertical;
  -webkit-line-clamp: 2;
}

.trend-use {
  align-self: flex-end;
  font-size: 12px;
  color: var(--text-secondary);
  white-space: nowrap;
}

@media (max-width: 760px) {
  .trend-grid { grid-template-columns: 1fr; }
  .inspiration-section { padding: 18px; }
  .structure-selector { justify-content: flex-start; }
  .structure-label { width: 100%; }
  .structure-option { flex: 1 1 140px; }
}

/* Animations */
@keyframes fadeIn {
  from { opacity: 0; transform: translateY(10px); }
  to { opacity: 1; transform: translateY(0); }
}

@keyframes slideUp {
  from { opacity: 0; transform: translateX(-50%) translateY(20px); }
  to { opacity: 1; transform: translateX(-50%) translateY(0); }
}
</style>
