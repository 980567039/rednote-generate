<template>
  <Teleport to="body">
    <div v-if="visible" class="publish-backdrop" @click.self="close">
      <section class="publish-dialog" role="dialog" aria-modal="true" aria-labelledby="publish-title">
        <header class="publish-header">
          <div>
            <h2 id="publish-title">发布到小红书</h2>
            <p>将 {{ imageCount }} 张成品图和下方内容交给本机浏览器发布助手。</p>
          </div>
          <button class="close-button" type="button" aria-label="关闭" @click="close">×</button>
        </header>

        <div v-if="initializing" class="initializing" role="status">
          <span class="modal-spinner" aria-hidden="true"></span>
          正在读取发布配置并检查登录状态…
        </div>

        <template v-else>
          <ErrorCard
            v-if="error"
            :error="error"
            dismissible
            class="publish-error"
            @dismiss="error = null"
          />

          <div class="login-row" :class="loginStateClass">
            <div>
              <strong>小红书登录</strong>
              <p>{{ loginMessage }}</p>
            </div>
            <div class="login-actions">
              <button
                class="btn btn-secondary compact-button"
                type="button"
                :disabled="checkingLogin || openingLogin || !publisherAvailable"
                @click="checkLogin"
              >
                {{ checkingLogin ? '检查中…' : '检查登录' }}
              </button>
              <button
                v-if="loggedIn !== true"
                class="btn btn-secondary compact-button"
                type="button"
                :disabled="openingLogin || !publisherAvailable"
                @click="openLogin"
              >
                {{ openingLogin ? '打开中…' : '打开登录页' }}
              </button>
            </div>
          </div>

          <form v-if="!task" class="publish-form" @submit.prevent="submit">
            <fieldset :disabled="submitting || !publisherAvailable">
              <legend class="sr-only">编辑小红书发布内容</legend>

              <label class="field-label" for="publish-title-select">标题</label>
              <select
                v-if="titles.length > 1"
                id="publish-title-select"
                v-model="selectedTitle"
                class="form-control"
              >
                <option v-for="(title, index) in titles" :key="`${index}-${title}`" :value="title">
                  {{ index === 0 ? '推荐' : `备选 ${index}` }}：{{ title }}
                </option>
              </select>
              <input
                v-model.trim="selectedTitle"
                class="form-control title-input"
                type="text"
                maxlength="100"
                placeholder="输入发布标题"
              />
              <p class="field-count" :class="{ invalid: titleWeight > 38 }">标题计数 {{ titleWeight }}/38（中文按 2 计）</p>

              <label class="field-label" for="publish-copywriting">正文</label>
              <textarea
                id="publish-copywriting"
                v-model="editableCopywriting"
                class="form-control copywriting-input"
                rows="7"
                maxlength="5000"
                placeholder="输入笔记正文"
              ></textarea>
              <p class="field-count">{{ editableCopywriting.length }}/5000</p>

              <label class="field-label" for="publish-tags">标签</label>
              <input
                id="publish-tags"
                v-model="editableTags"
                class="form-control"
                type="text"
                placeholder="#旅行攻略 #周末去哪儿（空格或逗号分隔）"
              />
              <p class="field-hint" :class="{ invalid: parsedTags.length > 10 }">将发布 {{ parsedTags.length }}/10 个标签，可在发布前继续修改。</p>

              <div class="mode-field">
                <span class="field-label">发布模式</span>
                <label class="mode-option" :class="{ active: mode === 'preview' }">
                  <input v-model="mode" type="radio" value="preview" />
                  <span>
                    <strong>预览确认（推荐）</strong>
                    <small>自动填好内容后暂停，等你在浏览器检查再发布。</small>
                  </span>
                </label>
                <label class="mode-option" :class="{ active: mode === 'auto' }">
                  <input v-model="mode" type="radio" value="auto" />
                  <span>
                    <strong>自动发布</strong>
                    <small>填充完成后直接点击发布，存在误发、重复发布或账号风控风险。</small>
                  </span>
                </label>
              </div>

              <label class="risk-confirmation">
                <input v-model="riskConfirmed" type="checkbox" />
                <span>我确认标题、正文、标签及 {{ imageCount }} 张图片均可发布，并知晓网页自动化可能失败、误发或触发平台风控。</span>
              </label>
            </fieldset>

            <footer class="publish-actions">
              <span v-if="!publisherAvailable" class="availability-warning">
                本机发布助手不可用，请先到系统设置检查路径。
              </span>
              <button class="btn btn-secondary" type="button" @click="close">取消</button>
              <button
                class="btn btn-primary"
                type="submit"
                :disabled="!canSubmit"
                :title="submitDisabledReason"
              >
                {{ submitting ? '正在创建任务…' : mode === 'preview' ? '填充到发布页' : '确认自动发布' }}
              </button>
            </footer>
          </form>

          <div v-else class="task-panel" aria-live="polite">
            <div class="task-summary">
              <span class="status-indicator" :class="`status-${task.status}`" aria-hidden="true"></span>
              <div>
                <strong>{{ statusTitle }}</strong>
                <p>{{ task.message || task.phase || statusDescription }}</p>
              </div>
            </div>

            <ol class="stage-list">
              <li
                v-for="stage in visibleStages"
                :key="stage.status"
                :class="stageClass(stage.status)"
              >
                <span class="stage-dot">{{ isStageDone(stage.status) ? '✓' : '' }}</span>
                <span>{{ stage.label }}</span>
              </li>
            </ol>

            <p class="task-id">任务 ID：{{ task.id }}</p>

            <a
              v-if="task.status === 'published' && task.note_url"
              class="note-link"
              :href="task.note_url"
              target="_blank"
              rel="noopener noreferrer"
            >
              查看已发布笔记
            </a>

            <div v-if="task.status === 'ready_for_review'" class="review-notice">
              <strong>请先切到浏览器逐项检查</strong>
              <p>确认图片顺序、标题、正文和标签无误后，再点击下方按钮。确认后不可撤销。</p>
              <button
                class="btn btn-primary"
                type="button"
                :disabled="confirming"
                @click="confirmAfterReview"
              >
                {{ confirming ? '正在确认…' : '我已在浏览器检查，确认发布' }}
              </button>
            </div>

            <footer class="publish-actions">
              <button
                v-if="isTerminal"
                class="btn btn-secondary"
                type="button"
                @click="resetTask"
              >
                {{ task.status === 'auth_required' ? '登录后返回编辑并重建任务' : '返回编辑' }}
              </button>
              <button class="btn btn-primary" type="button" @click="close">
                {{ isTerminal ? '完成' : '关闭并在后台继续' }}
              </button>
            </footer>
          </div>
        </template>
      </section>
    </div>
  </Teleport>
</template>

<script setup lang="ts">
import { computed, onMounted, onUnmounted, ref, watch } from 'vue'
import {
  checkPublishLogin,
  confirmPublishTask,
  createPublishTask,
  getPublishConfig,
  getPublishTask,
  openPublishLogin,
  type PublishMode,
  type PublishTask,
  type PublishTaskStatus
} from '../../api'
import ErrorCard from '../common/ErrorCard.vue'
import { normalizeApiError, type AppError } from '../../utils/errors'

const props = defineProps<{
  visible: boolean
  recordId: string
  titles: string[]
  copywriting: string
  tags: string[]
  imageCount: number
}>()

const emit = defineEmits<{
  (e: 'close'): void
}>()

const initializing = ref(false)
const publisherAvailable = ref(false)
const selectedTitle = ref('')
const editableCopywriting = ref('')
const editableTags = ref('')
const mode = ref<PublishMode>('preview')
const riskConfirmed = ref(false)
const loggedIn = ref<boolean | null>(null)
const checkingLogin = ref(false)
const openingLogin = ref(false)
const loginMessage = ref('尚未检查登录状态。')
const submitting = ref(false)
const confirming = ref(false)
const task = ref<PublishTask | null>(null)
const error = ref<AppError | null>(null)
let pollTimer: number | null = null
let pollInFlight = false

const stages: Array<{ status: PublishTaskStatus; label: string }> = [
  { status: 'queued', label: '任务排队' },
  { status: 'validating', label: '校验内容' },
  { status: 'checking_auth', label: '检查登录' },
  { status: 'launching_browser', label: '打开浏览器' },
  { status: 'uploading', label: '上传图片' },
  { status: 'filling', label: '填写内容' },
  { status: 'ready_for_review', label: '人工检查' },
  { status: 'submitting', label: '提交发布' },
  { status: 'published', label: '发布完成' }
]

const terminalStatuses = new Set<PublishTaskStatus>(['published', 'submitted', 'failed', 'unknown', 'auth_required'])

const parsedTags = computed(() => editableTags.value
  .split(/[\s,，]+/)
  .map(tag => tag.trim().replace(/^#+/, ''))
  .filter((tag, index, list) => Boolean(tag) && list.indexOf(tag) === index))

const titleWeight = computed(() => Array.from(selectedTitle.value)
  .reduce((total, char) => total + (/^[\u4e00-\u9fff\u3000-\u303f\uff00-\uffef]$/.test(char) ? 2 : 1), 0))

const canSubmit = computed(() => Boolean(
  publisherAvailable.value
  && props.recordId
  && loggedIn.value === true
  && selectedTitle.value.trim()
  && titleWeight.value <= 38
  && editableCopywriting.value.trim()
  && parsedTags.value.length <= 10
  && riskConfirmed.value
  && !submitting.value
))

const submitDisabledReason = computed(() => {
  if (!publisherAvailable.value) return '本机发布助手不可用'
  if (loggedIn.value !== true) return '请先登录小红书并检查登录状态'
  if (!selectedTitle.value.trim()) return '请填写标题'
  if (titleWeight.value > 38) return '标题过长，请缩短到 38 个计数单位以内'
  if (!editableCopywriting.value.trim()) return '请填写正文'
  if (parsedTags.value.length > 10) return '标签最多 10 个'
  if (!riskConfirmed.value) return '请先确认发布风险'
  return ''
})

const loginStateClass = computed(() => ({
  success: loggedIn.value === true,
  warning: loggedIn.value === false
}))

const isTerminal = computed(() => task.value ? terminalStatuses.has(task.value.status) : false)

const statusTitle = computed(() => {
  const labels: Record<PublishTaskStatus, string> = {
    queued: '任务已创建',
    validating: '正在校验发布内容',
    checking_auth: '正在检查登录',
    auth_required: '需要登录小红书',
    launching_browser: '正在打开浏览器',
    opening_browser: '正在打开浏览器',
    uploading: '正在上传图片',
    filling: '正在填写发布内容',
    ready_for_review: '等待你检查并确认',
    submitting: '正在提交发布',
    submitted: '已提交，等待平台确认',
    published: '发布成功',
    failed: '发布失败',
    unknown: '发布结果未知'
  }
  return task.value ? labels[task.value.status] || '正在处理发布任务' : ''
})

const statusDescription = computed(() => {
  if (!task.value) return ''
  const descriptions: Partial<Record<PublishTaskStatus, string>> = {
    queued: '发布任务正在等待执行。',
    ready_for_review: '浏览器中已填好发布内容，请人工检查。',
    auth_required: '任务已停止。请登录小红书，检查登录成功后返回编辑并重新创建任务。',
    submitted: '操作已提交，但尚未取得平台最终成功凭据，请到小红书确认。',
    published: '平台已确认发布成功。',
    failed: '任务已停止，不会自动重试，避免重复发布。',
    unknown: '无法判断是否发布成功，请先到小红书检查，勿立即重试。'
  }
  return descriptions[task.value.status] || '发布助手正在执行，请保持浏览器开启。'
})

const visibleStages = computed(() => mode.value === 'preview'
  ? stages
  : stages.filter(stage => stage.status !== 'ready_for_review'))

function resetForm() {
  selectedTitle.value = props.titles[0] || ''
  editableCopywriting.value = props.copywriting || ''
  editableTags.value = props.tags.map(tag => `#${tag.replace(/^#+/, '')}`).join(' ')
  riskConfirmed.value = false
  loggedIn.value = null
  loginMessage.value = '尚未检查登录状态。'
  task.value = null
  error.value = null
}

async function initialize() {
  stopPolling()
  resetForm()
  publisherAvailable.value = false
  initializing.value = true
  try {
    const result = await getPublishConfig()
    if (!props.visible) return
    if (!result.success || !result.config) {
      error.value = normalizeApiError(result.error || result.error_message || '读取发布配置失败', '读取发布配置失败')
      return
    }
    publisherAvailable.value = result.config.publisher_available
    mode.value = result.config.default_mode || 'preview'
    await restoreRememberedTask()
    if (!publisherAvailable.value) {
      loginMessage.value = '本机发布助手不可用，请到系统设置检查发布器目录。'
      loggedIn.value = false
      return
    }
    if (!task.value || task.value.status === 'auth_required') await checkLogin()
  } finally {
    if (props.visible) initializing.value = false
  }
}

async function checkLogin() {
  checkingLogin.value = true
  try {
    const result = await checkPublishLogin()
    if (!props.visible) return
    if (result.success) {
      loggedIn.value = result.logged_in === true || result.authenticated === true
      loginMessage.value = result.message || (loggedIn.value ? '已登录，可以开始发布。' : '当前未登录，请打开登录页扫码。')
    } else {
      loggedIn.value = false
      loginMessage.value = result.error_message || '登录状态检查失败。'
      error.value = normalizeApiError(result.error || result.error_message || '检查登录状态失败', '检查登录状态失败')
    }
  } finally {
    checkingLogin.value = false
  }
}

async function openLogin() {
  openingLogin.value = true
  error.value = null
  try {
    const result = await openPublishLogin()
    if (!props.visible) return
    if (result.success) {
      loginMessage.value = result.message || (result.login_started ? '登录页已打开，请在浏览器完成登录后重新检查。' : '请在浏览器完成登录后重新检查。')
    } else {
      error.value = normalizeApiError(result.error || result.error_message || '打开登录页失败', '打开登录页失败')
    }
  } finally {
    openingLogin.value = false
  }
}

async function submit() {
  if (!canSubmit.value) return
  submitting.value = true
  error.value = null
  try {
    const result = await createPublishTask(props.recordId, {
      title: selectedTitle.value.trim(),
      copywriting: editableCopywriting.value.trim(),
      tags: parsedTags.value,
      mode: mode.value,
      confirm: true
    })
    if (!result.success || !result.task) {
      error.value = normalizeApiError(result.error || result.error_message || '创建发布任务失败', '创建发布任务失败')
      return
    }
    task.value = result.task
    handleTaskState()
  } finally {
    submitting.value = false
  }
}

function schedulePoll(delay = 1000) {
  stopPolling()
  if (!props.visible || !task.value || isTerminal.value || task.value.status === 'ready_for_review') return
  pollTimer = window.setTimeout(pollTask, delay)
}

async function pollTask() {
  if (!props.visible || !task.value || pollInFlight) return
  pollInFlight = true
  try {
    const result = await getPublishTask(task.value.id)
    if (!props.visible || !task.value) return
    if (result.success && result.task) {
      task.value = result.task
      handleTaskState()
      return
    }
    error.value = normalizeApiError(result.error || result.error_message || '刷新发布状态失败', '刷新发布状态失败')
    schedulePoll(3000)
  } finally {
    pollInFlight = false
  }
}

function handleTaskState() {
  if (!task.value) return
  rememberTask(task.value.id)
  if (task.value.status === 'failed' || task.value.status === 'unknown' || task.value.status === 'auth_required') {
    const fallback = task.value.status === 'failed'
      ? '发布任务失败'
      : task.value.status === 'auth_required'
        ? '需要登录小红书'
        : '无法确认发布结果'
    error.value = normalizeApiError(task.value.error || task.value.error_message || task.value.message || fallback, fallback)
  }
  schedulePoll()
}

async function confirmAfterReview() {
  if (!task.value || confirming.value) return
  confirming.value = true
  error.value = null
  try {
    const result = await confirmPublishTask(task.value.id)
    if (!result.success) {
      error.value = normalizeApiError(result.error || result.error_message || '确认发布失败', '确认发布失败')
      return
    }
    if (result.task) task.value = result.task
    else task.value = { ...task.value, status: 'submitting', message: result.message || '已确认，正在提交发布。' }
    handleTaskState()
  } finally {
    confirming.value = false
  }
}

function statusRank(status: PublishTaskStatus) {
  const normalized = canonicalStatus(status)
  return stages.findIndex(stage => stage.status === normalized)
}

function canonicalStatus(status: PublishTaskStatus): PublishTaskStatus {
  if (status === 'auth_required') return 'checking_auth'
  if (status === 'opening_browser') return 'launching_browser'
  if (status === 'submitted') return 'published'
  return status
}

function isStageDone(status: PublishTaskStatus) {
  if (!task.value || ['failed', 'unknown'].includes(task.value.status)) return false
  return statusRank(task.value.status) > statusRank(status)
    || ['published', 'submitted'].includes(task.value.status) && status === 'published'
}

function stageClass(status: PublishTaskStatus) {
  if (!task.value) return {}
  return {
    active: canonicalStatus(task.value.status) === status,
    done: isStageDone(status),
    failed: ['failed', 'unknown'].includes(task.value.status) && statusRank(status) === Math.max(0, statusRank(task.value.status))
  }
}

function resetTask() {
  stopPolling()
  forgetTask()
  task.value = null
  error.value = null
  riskConfirmed.value = false
}

function taskStorageKey() {
  return `xhs-publish-task:${props.recordId}`
}

function rememberTask(taskId: string) {
  if (props.recordId && taskId) localStorage.setItem(taskStorageKey(), taskId)
}

function forgetTask() {
  if (props.recordId) localStorage.removeItem(taskStorageKey())
}

async function restoreRememberedTask() {
  if (!props.recordId) return
  const taskId = localStorage.getItem(taskStorageKey())
  if (!taskId) return
  const result = await getPublishTask(taskId)
  if (result.success && result.task) {
    task.value = result.task
    if (result.task.mode) mode.value = result.task.mode
    handleTaskState()
    return
  }
  const restoreError = normalizeApiError(result.error || result.error_message || '恢复发布任务失败', '恢复发布任务失败')
  if (restoreError.status === 404 || restoreError.code === 'NOT_FOUND' || restoreError.code === 'RESOURCE_NOT_FOUND') {
    forgetTask()
    return
  }
  error.value = restoreError
}

function stopPolling() {
  if (pollTimer !== null) {
    window.clearTimeout(pollTimer)
    pollTimer = null
  }
}

function close() {
  stopPolling()
  emit('close')
}

function handleKeydown(event: KeyboardEvent) {
  if (props.visible && event.key === 'Escape') close()
}

watch(() => props.visible, visible => {
  if (visible) void initialize()
  else stopPolling()
})

onMounted(() => window.addEventListener('keydown', handleKeydown))
onUnmounted(() => {
  stopPolling()
  window.removeEventListener('keydown', handleKeydown)
})
</script>

<style scoped>
.publish-backdrop {
  position: fixed;
  inset: 0;
  z-index: 1200;
  display: flex;
  align-items: center;
  justify-content: center;
  padding: 20px;
  background: color-mix(in srgb, var(--text-main) 60%, transparent);
  backdrop-filter: blur(4px);
}

.publish-dialog {
  width: min(100%, 680px);
  max-height: calc(100vh - 40px);
  overflow-y: auto;
  padding: 24px;
  border: 1px solid var(--border-color);
  border-radius: 18px;
  background: var(--bg-card);
  color: var(--text-main);
  box-shadow: var(--shadow-lg);
}

.publish-header,
.login-row,
.publish-actions,
.task-summary {
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  gap: 16px;
}

.publish-header { margin-bottom: 20px; }
.publish-header h2 { margin: 0 0 4px; font-size: 20px; }
.publish-header p,
.login-row p,
.task-summary p,
.review-notice p { margin: 0; color: var(--text-sub); font-size: 13px; line-height: 1.55; }

.close-button {
  flex: 0 0 auto;
  width: 30px;
  height: 30px;
  border: 0;
  border-radius: 8px;
  background: transparent;
  color: var(--text-sub);
  cursor: pointer;
  font-size: 24px;
  line-height: 1;
}
.close-button:hover { background: var(--bg-muted); color: var(--text-main); }

.initializing {
  display: flex;
  align-items: center;
  justify-content: center;
  gap: 10px;
  min-height: 180px;
  color: var(--text-sub);
}

.modal-spinner {
  width: 20px;
  height: 20px;
  border: 2px solid var(--border-color);
  border-top-color: var(--primary);
  border-radius: 50%;
  animation: spin 0.8s linear infinite;
}

@keyframes spin { to { transform: rotate(360deg); } }

.publish-error { margin-bottom: 14px; }

.login-row {
  align-items: center;
  margin-bottom: 20px;
  padding: 12px 14px;
  border: 1px solid var(--border-color);
  border-radius: 12px;
  background: var(--bg-muted);
}
.login-row.success { border-color: color-mix(in srgb, var(--primary) 38%, var(--border-color)); }
.login-row.warning { border-color: color-mix(in srgb, var(--primary) 48%, var(--border-color)); }
.login-row strong { font-size: 14px; }
.login-actions { display: flex; flex-wrap: wrap; justify-content: flex-end; gap: 8px; }
.compact-button { padding: 7px 12px; font-size: 13px; }

.publish-form fieldset { min-width: 0; padding: 0; border: 0; }
.field-label { display: block; margin: 15px 0 7px; color: var(--text-main); font-size: 14px; font-weight: 600; }
.form-control {
  box-sizing: border-box;
  width: 100%;
  padding: 10px 12px;
  border: 1px solid var(--border-color);
  border-radius: 10px;
  outline: none;
  background: var(--bg-control);
  color: var(--text-main);
  font: inherit;
}
.form-control:focus { border-color: var(--primary); box-shadow: 0 0 0 3px var(--primary-fade); }
.form-control::placeholder { color: var(--text-placeholder); }
.title-input { margin-top: 8px; }
.copywriting-input { resize: vertical; line-height: 1.6; }
.field-count,
.field-hint { margin: 5px 0 0; color: var(--text-secondary); font-size: 12px; text-align: right; }
.field-hint { text-align: left; }
.field-count.invalid,
.field-hint.invalid { color: var(--primary); }

.mode-field { display: grid; gap: 8px; margin-top: 18px; }
.mode-field > .field-label { margin: 0 0 1px; }
.mode-option {
  display: flex;
  align-items: flex-start;
  gap: 10px;
  padding: 11px 12px;
  border: 1px solid var(--border-color);
  border-radius: 10px;
  background: var(--bg-control);
  cursor: pointer;
}
.mode-option.active { border-color: var(--primary); background: var(--primary-fade); }
.mode-option input { margin-top: 3px; accent-color: var(--primary); }
.mode-option span { display: grid; gap: 2px; }
.mode-option strong { font-size: 14px; }
.mode-option small { color: var(--text-sub); line-height: 1.45; }

.risk-confirmation {
  display: flex;
  align-items: flex-start;
  gap: 10px;
  margin-top: 16px;
  padding: 11px 12px;
  border-radius: 10px;
  background: var(--bg-muted);
  color: var(--text-sub);
  font-size: 12px;
  line-height: 1.55;
  cursor: pointer;
}
.risk-confirmation input { margin-top: 3px; accent-color: var(--primary); }

.publish-actions { align-items: center; justify-content: flex-end; margin-top: 20px; }
.availability-warning { margin-right: auto; color: var(--primary); font-size: 12px; }

.task-panel { display: grid; gap: 18px; }
.task-summary { justify-content: flex-start; padding: 14px; border-radius: 12px; background: var(--bg-muted); }
.status-indicator { flex: 0 0 auto; width: 12px; height: 12px; margin-top: 5px; border-radius: 50%; background: var(--text-secondary); box-shadow: 0 0 0 4px var(--border-color); }
.status-published,
.status-submitted { background: var(--primary); box-shadow: 0 0 0 4px var(--primary-fade); }
.status-failed,
.status-unknown { background: var(--primary-active); box-shadow: 0 0 0 4px var(--primary-fade); }

.stage-list { display: grid; grid-template-columns: repeat(4, minmax(0, 1fr)); gap: 10px; list-style: none; padding: 0; margin: 0; }
.stage-list li { display: flex; align-items: center; gap: 7px; color: var(--text-secondary); font-size: 12px; }
.stage-dot { display: inline-flex; align-items: center; justify-content: center; flex: 0 0 auto; width: 20px; height: 20px; border: 1px solid var(--border-color); border-radius: 50%; background: var(--bg-control); font-size: 11px; }
.stage-list li.active { color: var(--text-main); font-weight: 600; }
.stage-list li.active .stage-dot { border-color: var(--primary); box-shadow: 0 0 0 3px var(--primary-fade); }
.stage-list li.done { color: var(--text-sub); }
.stage-list li.done .stage-dot { border-color: var(--primary); background: var(--primary); color: var(--bg-card); }
.task-id { margin: -8px 0 0; color: var(--text-secondary); font-size: 11px; word-break: break-all; }
.note-link { display: inline-flex; width: fit-content; color: var(--primary); font-size: 14px; font-weight: 600; text-decoration: none; }
.note-link:hover { color: var(--primary-hover); text-decoration: underline; }

.review-notice { padding: 14px; border: 1px solid var(--primary); border-radius: 12px; background: var(--primary-fade); }
.review-notice p { margin: 4px 0 12px; }
.review-notice .btn { width: 100%; }

.sr-only { position: absolute; width: 1px; height: 1px; overflow: hidden; clip: rect(0, 0, 0, 0); white-space: nowrap; }

@media (max-width: 640px) {
  .publish-dialog { padding: 18px; }
  .login-row { align-items: flex-start; flex-direction: column; }
  .login-actions { justify-content: flex-start; }
  .stage-list { grid-template-columns: repeat(2, minmax(0, 1fr)); }
  .publish-actions { flex-wrap: wrap; }
  .availability-warning { width: 100%; }
}
</style>
