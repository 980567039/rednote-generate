<template>
  <div v-if="visible" class="pattern-backdrop" @click.self="close">
    <section class="pattern-dialog" role="dialog" aria-modal="true" aria-labelledby="pattern-dialog-title">
      <header class="pattern-header">
        <div>
          <h2 id="pattern-dialog-title">生成第 {{ pageNumber }} 页的拼豆图纸和效果图</h2>
          <p v-if="step === 'config'">输入成品网格规格，系统将在本机后台生成。</p>
          <p v-else-if="step === 'progress'">正在本机处理原图，请保持当前页面打开。</p>
          <p v-else>确认后会保存方格图纸、拼豆实物和熨烫成品，并追加到最后一页。</p>
        </div>
        <button class="pattern-close" type="button" :disabled="busy" aria-label="关闭" @click="close">×</button>
      </header>

      <div v-if="step === 'config'" class="pattern-body">
        <div class="pattern-fields">
          <label>
            <span>列数（宽）</span>
            <input v-model="columns" type="number" min="1" max="300" step="1" inputmode="numeric" />
            <small>1–300 列</small>
          </label>
          <label>
            <span>行数（高）</span>
            <input v-model="rows" type="number" min="1" max="300" step="1" inputmode="numeric" />
            <small>1–300 行</small>
          </label>
          <label>
            <span>最大用色数</span>
            <input v-model="maxUsedColors" type="number" min="2" max="64" step="1" inputmode="numeric" />
            <small>2–64 色</small>
          </label>
        </div>
        <p class="pattern-note">默认 104 × 104、40 色；成功开始后会记住本次规格。</p>
        <p v-if="formError || errorMessage" class="pattern-error" role="alert">{{ formError || errorMessage }}</p>
        <footer class="pattern-actions">
          <button class="btn btn-secondary" type="button" @click="close">取消</button>
          <button class="btn btn-primary" type="button" @click="start">开始生成</button>
        </footer>
      </div>

      <div v-else-if="step === 'progress'" class="pattern-body pattern-progress" aria-live="polite">
        <span class="pattern-spinner" aria-hidden="true"></span>
        <strong>{{ progressLabel }}</strong>
        <p>{{ progressDetail }}</p>
        <div class="pattern-progress-track" role="progressbar" :aria-valuenow="progressPercent" aria-valuemin="0" aria-valuemax="100">
          <span :style="{ width: `${progressPercent}%` }"></span>
        </div>
        <footer class="pattern-actions">
          <button class="btn btn-secondary" type="button" @click="close">取消生成</button>
        </footer>
      </div>

      <div v-else class="pattern-body">
        <p v-if="errorMessage" class="pattern-error" role="alert">{{ errorMessage }}</p>
        <div class="pattern-preview-toolbar">
          <div class="pattern-preview-tabs" role="tablist" aria-label="拼豆输出类型">
            <button
              v-for="tab in previewTabs"
              :key="tab.key"
              class="pattern-preview-tab"
              :class="{ active: selectedPreview === tab.key }"
              type="button"
              role="tab"
              :aria-selected="selectedPreview === tab.key"
              @click="selectedPreview = tab.key"
            >
              {{ tab.label }}
            </button>
          </div>
          <div class="pattern-preview-tools">
            <span class="pattern-engine-badge">{{ activePreviewLabel }}</span>
            <button class="btn btn-secondary pattern-fullscreen-trigger" type="button" :disabled="!activePreviewUrl" @click="openFullscreen">
              全屏查看
            </button>
          </div>
        </div>
        <button
          v-if="activePreviewUrl"
          class="pattern-preview"
          type="button"
          :aria-label="`全屏查看${activePreviewLabel}`"
          @click="openFullscreen"
        >
          <img :src="activePreviewUrl" :alt="`拼豆 ${activePreviewLabel}`" />
          <span class="pattern-preview-hint">点击查看原始尺寸</span>
        </button>
        <div v-else class="pattern-preview pattern-preview-empty">
          暂无可预览的图纸
        </div>
        <p v-if="activePreviewUrl" class="pattern-preview-caption">三种图片来自同一份拼豆网格：方格图纸用于施工，另外两种用于预览制作前后的效果。</p>
        <dl v-if="metadata" class="pattern-metadata">
          <div><dt>实际规格</dt><dd>{{ metadata.columns }} × {{ metadata.rows }}</dd></div>
          <div><dt>实际用色</dt><dd>{{ metadata.usedColors }} 色</dd></div>
        </dl>
        <footer class="pattern-actions pattern-preview-actions">
          <button class="btn btn-secondary" type="button" :disabled="busy" @click="close">暂不追加</button>
          <button class="btn btn-secondary" type="button" :disabled="busy" @click="$emit('refine')">
            {{ isRefining ? '等待 Perler 回传…' : '在 Perler 中细调' }}
          </button>
          <button class="btn btn-primary" type="button" :disabled="busy" @click="$emit('append')">
            {{ isAppending ? '追加中…' : '确认追加' }}
          </button>
        </footer>
      </div>
    </section>
  </div>

  <Teleport to="body">
    <div v-if="fullscreenOpen" class="pattern-fullscreen" role="dialog" aria-modal="true" :aria-label="`全屏查看${activePreviewLabel}`">
      <header class="pattern-fullscreen-toolbar">
        <div class="pattern-fullscreen-title">
          <strong>{{ activePreviewLabel }}</strong>
          <span>{{ fullscreenFit ? '适应窗口' : `${zoomPercent}%` }}</span>
        </div>
        <div class="pattern-zoom-controls" aria-label="预览缩放控制">
          <button type="button" aria-label="缩小" title="缩小" @click="zoomOut">−</button>
          <input
            :value="zoomPercent"
            type="range"
            min="25"
            max="400"
            step="25"
            aria-label="缩放比例"
            @input="onZoomInput"
          />
          <button type="button" aria-label="放大" title="放大" @click="zoomIn">+</button>
          <button type="button" @click="setZoom(100)">100%</button>
          <button type="button" :class="{ active: fullscreenFit }" @click="fitFullscreen">适应窗口</button>
          <button class="pattern-fullscreen-close" type="button" aria-label="关闭全屏预览" title="关闭（Esc）" @click="closeFullscreen">×</button>
        </div>
      </header>
      <div class="pattern-fullscreen-canvas">
        <div class="pattern-fullscreen-stage" :class="{ fit: fullscreenFit }">
          <img
            v-if="activePreviewUrl"
            :key="activePreviewUrl"
            :src="activePreviewUrl"
            :alt="`拼豆 ${activePreviewLabel}全尺寸预览`"
            :style="fullscreenImageStyle"
            @load="captureFullscreenImageSize"
          />
        </div>
      </div>
    </div>
  </Teleport>
</template>

<script setup lang="ts">
import { computed, onBeforeUnmount, ref, watch } from 'vue'
import {
  isValidPerlerSettings,
  loadPerlerSettings,
  savePerlerSettings,
  type PerlerPatternSettings,
} from '../../integrations/perlerSettings'
import type { PerlerPatternMetadata, PerlerProgressUpdate } from '../../integrations/perlerBridge'

type PatternStep = 'config' | 'progress' | 'preview'
type PatternProgressUpdate = PerlerProgressUpdate
type PatternPreviewKind = 'pattern' | 'beads' | 'ironed'

const props = defineProps<{
  visible: boolean
  step: PatternStep
  pageNumber: number
  progress: PatternProgressUpdate | null
  previewUrls: Partial<Record<PatternPreviewKind, string>>
  metadata: PerlerPatternMetadata | null
  errorMessage: string
  isRefining: boolean
  isAppending: boolean
}>()

const emit = defineEmits<{
  close: []
  start: [settings: PerlerPatternSettings]
  refine: []
  append: []
}>()

const columns = ref('104')
const rows = ref('104')
const maxUsedColors = ref('40')
const formError = ref('')
const fullscreenOpen = ref(false)
const fullscreenFit = ref(true)
const zoomPercent = ref(100)
const fullscreenNaturalSize = ref({ width: 0, height: 0 })
const selectedPreview = ref<PatternPreviewKind>('beads')
const busy = computed(() => props.isRefining || props.isAppending)

const previewTabLabels: Record<PatternPreviewKind, string> = {
  pattern: '方格图纸',
  beads: '拼豆实物',
  ironed: '熨烫成品',
}
const previewTabs = computed(() => (
  (Object.keys(previewTabLabels) as PatternPreviewKind[])
    .filter(key => Boolean(props.previewUrls[key]))
    .map(key => ({ key, label: previewTabLabels[key] }))
))
const activePreviewUrl = computed(() => props.previewUrls[selectedPreview.value] || '')
const activePreviewLabel = computed(() => previewTabLabels[selectedPreview.value])

function syncSelectedPreview() {
  if (props.previewUrls[selectedPreview.value]) return
  const fallback = (['beads', 'pattern', 'ironed'] as PatternPreviewKind[])
    .find(key => Boolean(props.previewUrls[key]))
  if (fallback) selectedPreview.value = fallback
}

const stageLabels: Record<PerlerProgressUpdate['stage'], string> = {
  connect: '正在准备本地生成…',
  prepare: '正在准备原图…',
  sample: '正在采样像素…',
  select: '正在选择拼豆颜色…',
  map: '正在映射拼豆色号…',
  cleanup: '正在清理零碎色块…',
  background: '正在识别并移除背景…',
  refine: '正在精简颜色与清理边缘…',
  render: '正在渲染三种拼豆输出…',
}

const progressLabel = computed(() => stageLabels[props.progress?.stage ?? 'connect'])
const progressPercent = computed(() => {
  const progress = props.progress
  if (!progress || progress.total <= 0) return 0
  return Math.max(0, Math.min(100, Math.round((progress.completed / progress.total) * 100)))
})
const progressDetail = computed(() => {
  const progress = props.progress
  if (!progress || progress.stage === 'connect') return '图片只在本机处理；完成后可选择在 Perler 中继续细调。'
  return `${progress.completed} / ${progress.total}`
})

function resetForm() {
  const settings = loadPerlerSettings()
  columns.value = String(settings.columns)
  rows.value = String(settings.rows)
  maxUsedColors.value = String(settings.maxUsedColors)
  formError.value = ''
}

watch(
  () => [props.visible, props.step] as const,
  ([visible, step], previous) => {
    if (visible && step === 'config' && (!previous || !previous[0] || previous[1] !== 'config')) resetForm()
    if (visible && step === 'preview') syncSelectedPreview()
    if (!visible || step !== 'preview') closeFullscreen()
  },
  { immediate: true },
)

watch(() => props.previewUrls, () => {
  fullscreenNaturalSize.value = { width: 0, height: 0 }
  syncSelectedPreview()
}, { deep: true })

const fullscreenImageStyle = computed(() => {
  if (fullscreenFit.value) {
    return {
      width: 'auto',
      height: 'auto',
      maxWidth: '100%',
      maxHeight: '100%',
      imageRendering: 'auto' as const,
    }
  }

  const { width, height } = fullscreenNaturalSize.value
  const scale = zoomPercent.value / 100
  return {
    width: width ? `${Math.round(width * scale)}px` : 'auto',
    height: height ? `${Math.round(height * scale)}px` : 'auto',
    maxWidth: 'none',
    maxHeight: 'none',
    imageRendering: zoomPercent.value >= 100 ? 'pixelated' as const : 'auto' as const,
  }
})

function openFullscreen() {
  if (!activePreviewUrl.value) return
  fullscreenFit.value = true
  fullscreenOpen.value = true
}

function closeFullscreen() {
  fullscreenOpen.value = false
}

function setZoom(value: number) {
  zoomPercent.value = Math.max(25, Math.min(400, Math.round(value / 25) * 25))
  fullscreenFit.value = false
}

function zoomIn() {
  setZoom(fullscreenFit.value ? 125 : zoomPercent.value + 25)
}

function zoomOut() {
  setZoom(fullscreenFit.value ? 75 : zoomPercent.value - 25)
}

function fitFullscreen() {
  fullscreenFit.value = true
}

function onZoomInput(event: Event) {
  setZoom(Number((event.target as HTMLInputElement).value))
}

function captureFullscreenImageSize(event: Event) {
  const image = event.target as HTMLImageElement
  fullscreenNaturalSize.value = { width: image.naturalWidth, height: image.naturalHeight }
}

function onFullscreenKeydown(event: KeyboardEvent) {
  if (event.key === 'Escape') closeFullscreen()
}

watch(fullscreenOpen, (open) => {
  if (open) window.addEventListener('keydown', onFullscreenKeydown)
  else window.removeEventListener('keydown', onFullscreenKeydown)
})

onBeforeUnmount(() => {
  window.removeEventListener('keydown', onFullscreenKeydown)
})

function start() {
  const settings = {
    columns: Number(columns.value),
    rows: Number(rows.value),
    maxUsedColors: Number(maxUsedColors.value),
  }
  if (!isValidPerlerSettings(settings)) {
    formError.value = '请输入整数：列数和行数为 1–300，最大用色数为 2–64。'
    return
  }
  formError.value = ''
  savePerlerSettings(settings)
  emit('start', settings)
}

function close() {
  if (busy.value) return
  closeFullscreen()
  emit('close')
}
</script>

<style scoped>
.pattern-backdrop { position: fixed; inset: 0; z-index: 110; display: grid; place-items: center; padding: 20px; background: rgba(15, 23, 42, 0.52); backdrop-filter: blur(3px); }
.pattern-dialog { width: min(1080px, 100%); max-height: calc(100vh - 40px); overflow: auto; border: 1px solid var(--border-color); border-radius: 16px; background: var(--bg-card); box-shadow: 0 20px 70px rgba(15, 23, 42, 0.28); }
.pattern-header { display: flex; align-items: flex-start; justify-content: space-between; gap: 18px; padding: 22px 24px 18px; border-bottom: 1px solid var(--border-color); }
.pattern-header h2 { margin: 0; color: var(--text-main); font-size: 19px; }
.pattern-header p { margin: 6px 0 0; color: var(--text-sub); font-size: 13px; line-height: 1.5; }
.pattern-close { flex: 0 0 auto; width: 32px; height: 32px; border: 0; border-radius: 8px; background: transparent; color: var(--text-sub); cursor: pointer; font-size: 24px; line-height: 1; }
.pattern-close:hover:not(:disabled) { background: var(--bg-subtle); color: var(--text-main); }
.pattern-close:disabled { cursor: not-allowed; opacity: 0.45; }
.pattern-body { padding: 24px; }
.pattern-fields { display: grid; grid-template-columns: repeat(3, minmax(0, 1fr)); gap: 14px; }
.pattern-fields label { display: grid; gap: 7px; color: var(--text-main); font-size: 13px; font-weight: 600; }
.pattern-fields input { width: 100%; box-sizing: border-box; padding: 10px 11px; border: 1px solid var(--border-color); border-radius: 8px; outline: none; background: var(--bg-control); color: var(--text-main); font: inherit; }
.pattern-fields input:focus { border-color: var(--primary); box-shadow: 0 0 0 3px var(--primary-fade); }
.pattern-fields small { color: var(--text-sub); font-size: 11px; font-weight: 400; }
.pattern-note { margin: 16px 0 0; color: var(--text-sub); font-size: 12px; }
.pattern-error { margin: 14px 0 0; padding: 10px 12px; border-radius: 8px; background: color-mix(in srgb, #ef4444 10%, var(--bg-card)); color: #dc2626; font-size: 12px; line-height: 1.5; }
.pattern-actions { display: flex; flex-wrap: wrap; justify-content: flex-end; gap: 10px; margin-top: 24px; }
.pattern-progress { display: grid; justify-items: center; padding-top: 38px; text-align: center; }
.pattern-progress strong { margin-top: 16px; color: var(--text-main); font-size: 16px; }
.pattern-progress p { margin: 7px 0 0; color: var(--text-sub); font-size: 12px; }
.pattern-spinner { width: 38px; height: 38px; border: 3px solid var(--border-color); border-top-color: var(--primary); border-radius: 50%; animation: pattern-spin 0.8s linear infinite; }
.pattern-progress-track { width: min(380px, 100%); height: 8px; margin-top: 22px; overflow: hidden; border-radius: 999px; background: var(--bg-subtle); }
.pattern-progress-track span { display: block; height: 100%; border-radius: inherit; background: var(--primary); transition: width 0.25s ease; }
.pattern-progress .pattern-actions { width: 100%; }
.pattern-preview-toolbar { display: flex; align-items: center; justify-content: space-between; gap: 12px; margin-bottom: 12px; }
.pattern-preview-tabs { display: flex; flex-wrap: wrap; gap: 6px; }
.pattern-preview-tab { min-height: 30px; padding: 0 11px; border: 1px solid var(--border-color); border-radius: 7px; background: var(--bg-control); color: var(--text-sub); cursor: pointer; font: inherit; font-size: 12px; }
.pattern-preview-tab:hover, .pattern-preview-tab.active { border-color: var(--primary); background: var(--primary-fade); color: var(--primary); }
.pattern-preview-tools { display: flex; align-items: center; gap: 9px; margin-left: auto; }
.pattern-engine-badge { display: inline-flex; align-items: center; min-height: 26px; padding: 0 9px; border: 1px solid color-mix(in srgb, var(--primary) 35%, var(--border-color)); border-radius: 999px; background: color-mix(in srgb, var(--primary) 9%, var(--bg-card)); color: var(--primary); font-size: 11px; font-weight: 600; }
.pattern-fullscreen-trigger { padding: 7px 11px; font-size: 12px; }
.pattern-preview { position: relative; display: grid; width: 100%; min-height: 320px; max-height: 58vh; padding: 0; place-items: center; overflow: auto; border: 1px solid var(--border-color); border-radius: 10px; outline: none; background: var(--bg-subtle); cursor: zoom-in; }
.pattern-preview:hover, .pattern-preview:focus-visible { border-color: var(--primary); box-shadow: 0 0 0 3px var(--primary-fade); }
.pattern-preview img { display: block; max-width: 100%; max-height: 56vh; object-fit: contain; image-rendering: auto; }
.pattern-preview-hint { position: absolute; right: 12px; bottom: 12px; padding: 6px 9px; border-radius: 999px; background: rgba(15, 23, 42, 0.76); color: #fff; font-size: 11px; pointer-events: none; }
.pattern-preview-empty { color: var(--text-sub); cursor: default; font-size: 13px; }
.pattern-preview-empty:hover { border-color: var(--border-color); box-shadow: none; }
.pattern-preview-caption { margin: 9px 0 0; color: var(--text-sub); font-size: 12px; line-height: 1.5; }
.pattern-metadata { display: flex; flex-wrap: wrap; gap: 22px; margin: 16px 0 0; }
.pattern-metadata div { display: flex; align-items: baseline; gap: 7px; }
.pattern-metadata dt { color: var(--text-sub); font-size: 12px; }
.pattern-metadata dd { margin: 0; color: var(--text-main); font-size: 13px; font-weight: 600; }
.pattern-fullscreen { position: fixed; inset: 0; z-index: 300; display: grid; grid-template-rows: auto minmax(0, 1fr); background: #111827; }
.pattern-fullscreen-toolbar { display: flex; align-items: center; gap: 14px; min-height: 60px; padding: 9px 16px; border-bottom: 1px solid rgba(255, 255, 255, 0.14); background: rgba(17, 24, 39, 0.98); color: #fff; }
.pattern-fullscreen-title { display: flex; flex-direction: column; min-width: 125px; gap: 2px; }
.pattern-fullscreen-title strong { font-size: 13px; }
.pattern-fullscreen-title span { color: #9ca3af; font-size: 11px; }
.pattern-zoom-controls { display: flex; align-items: center; gap: 6px; margin-left: auto; }
.pattern-zoom-controls button { min-height: 34px; padding: 0 10px; border: 1px solid rgba(255, 255, 255, 0.18); border-radius: 7px; background: rgba(255, 255, 255, 0.08); color: #fff; cursor: pointer; font: inherit; font-size: 12px; }
.pattern-zoom-controls button:hover, .pattern-zoom-controls button.active { background: rgba(255, 255, 255, 0.2); }
.pattern-zoom-controls input { width: 132px; accent-color: var(--primary); }
.pattern-zoom-controls .pattern-fullscreen-close { width: 36px; padding: 0; font-size: 23px; line-height: 1; }
.pattern-fullscreen-canvas { min-width: 0; min-height: 0; overflow: auto; overscroll-behavior: contain; }
.pattern-fullscreen-stage { display: grid; width: max-content; min-width: 100%; min-height: 100%; padding: 32px; box-sizing: border-box; place-items: center; }
.pattern-fullscreen-stage.fit { width: 100%; height: 100%; }
.pattern-fullscreen-stage img { display: block; flex: none; object-fit: contain; }
@keyframes pattern-spin { to { transform: rotate(360deg); } }
@media (max-width: 760px) {
  .pattern-backdrop { padding: 10px; }
  .pattern-header, .pattern-body { padding: 18px; }
  .pattern-fields { grid-template-columns: 1fr; }
  .pattern-preview-toolbar { align-items: stretch; flex-direction: column; }
  .pattern-preview-tabs { width: 100%; }
  .pattern-preview-tools { justify-content: space-between; width: 100%; margin-left: 0; }
  .pattern-preview { min-height: 220px; }
  .pattern-preview-actions .btn { width: 100%; }
  .pattern-fullscreen-toolbar { align-items: stretch; flex-wrap: wrap; padding: 9px 10px; }
  .pattern-fullscreen-title { min-width: 0; }
  .pattern-zoom-controls { flex-wrap: wrap; margin-left: auto; }
  .pattern-zoom-controls input { width: 90px; }
  .pattern-fullscreen-stage { padding: 14px; }
}
</style>
