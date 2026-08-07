<template>
  <div v-if="visible" class="pattern-backdrop" @click.self="close">
    <section class="pattern-dialog" role="dialog" aria-modal="true" aria-labelledby="pattern-dialog-title">
      <header class="pattern-header">
        <div>
          <h2 id="pattern-dialog-title">生成第 {{ pageNumber }} 页的拼豆图纸</h2>
          <p v-if="step === 'config'">输入成品网格规格，Perler 将在后台自动生成。</p>
          <p v-else-if="step === 'progress'">正在后台处理原图，请保持当前页面打开。</p>
          <p v-else>图纸尚未写入历史记录，确认后才会追加到最后一页。</p>
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
        <div class="pattern-preview">
          <img v-if="previewUrl" :src="previewUrl" alt="生成的拼豆图纸预览" />
        </div>
        <dl v-if="metadata" class="pattern-metadata">
          <div><dt>实际规格</dt><dd>{{ metadata.columns }} × {{ metadata.rows }}</dd></div>
          <div><dt>实际用色</dt><dd>{{ metadata.usedColors }} 色</dd></div>
        </dl>
        <footer class="pattern-actions pattern-preview-actions">
          <button class="btn btn-secondary" type="button" :disabled="busy" @click="close">暂不追加</button>
          <button class="btn btn-secondary" type="button" :disabled="busy" @click="$emit('refine')">
            {{ isRefining ? '等待 Perler 回传…' : '进入 Perler 精修' }}
          </button>
          <button class="btn btn-primary" type="button" :disabled="busy" @click="$emit('append')">
            {{ isAppending ? '追加中…' : '确认追加' }}
          </button>
        </footer>
      </div>
    </section>
  </div>
</template>

<script setup lang="ts">
import { computed, ref, watch } from 'vue'
import {
  isValidPerlerSettings,
  loadPerlerSettings,
  savePerlerSettings,
  type PerlerPatternSettings,
} from '../../integrations/perlerSettings'
import type { PerlerPatternMetadata, PerlerProgressUpdate } from '../../integrations/perlerBridge'

type PatternStep = 'config' | 'progress' | 'preview'

const props = defineProps<{
  visible: boolean
  step: PatternStep
  pageNumber: number
  progress: PerlerProgressUpdate | null
  previewUrl: string
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
const busy = computed(() => props.isRefining || props.isAppending)

const stageLabels: Record<PerlerProgressUpdate['stage'], string> = {
  connect: '正在连接 Perler…',
  prepare: '正在准备原图…',
  sample: '正在采样像素…',
  select: '正在选择拼豆颜色…',
  map: '正在映射拼豆色号…',
  cleanup: '正在清理零碎色块…',
  background: '正在识别并移除背景…',
  render: '正在渲染母版图纸…',
}

const progressLabel = computed(() => stageLabels[props.progress?.stage ?? 'connect'])
const progressPercent = computed(() => {
  const progress = props.progress
  if (!progress || progress.total <= 0) return 0
  return Math.max(0, Math.min(100, Math.round((progress.completed / progress.total) * 100)))
})
const progressDetail = computed(() => {
  const progress = props.progress
  if (!progress || progress.stage === 'connect') return '首次连接最长等待 15 秒，整个任务最长等待 5 分钟。'
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
  },
  { immediate: true },
)

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
  emit('close')
}
</script>

<style scoped>
.pattern-backdrop { position: fixed; inset: 0; z-index: 110; display: grid; place-items: center; padding: 20px; background: rgba(15, 23, 42, 0.52); backdrop-filter: blur(3px); }
.pattern-dialog { width: min(620px, 100%); max-height: calc(100vh - 40px); overflow: auto; border: 1px solid var(--border-color); border-radius: 16px; background: var(--bg-card); box-shadow: 0 20px 70px rgba(15, 23, 42, 0.28); }
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
.pattern-preview { display: grid; min-height: 260px; max-height: 54vh; place-items: center; overflow: auto; border: 1px solid var(--border-color); border-radius: 10px; background: var(--bg-subtle); }
.pattern-preview img { display: block; max-width: 100%; max-height: 52vh; object-fit: contain; image-rendering: auto; }
.pattern-metadata { display: flex; flex-wrap: wrap; gap: 22px; margin: 16px 0 0; }
.pattern-metadata div { display: flex; align-items: baseline; gap: 7px; }
.pattern-metadata dt { color: var(--text-sub); font-size: 12px; }
.pattern-metadata dd { margin: 0; color: var(--text-main); font-size: 13px; font-weight: 600; }
@keyframes pattern-spin { to { transform: rotate(360deg); } }
@media (max-width: 620px) {
  .pattern-backdrop { padding: 10px; }
  .pattern-header, .pattern-body { padding: 18px; }
  .pattern-fields { grid-template-columns: 1fr; }
  .pattern-preview-actions .btn { width: 100%; }
}
</style>
