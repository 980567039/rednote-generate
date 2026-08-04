<template>
  <div class="container series-page">
    <header class="page-header series-header">
      <div>
        <button class="back-link" type="button" @click="router.push('/series')">← 返回合集列表</button>
        <h1 class="page-title">{{ project?.name || project?.template?.name || '系列合集工作台' }}</h1>
        <p class="page-subtitle">持续追加选题，每篇独立审核和生成；一次批量最多处理 10 篇。</p>
      </div>
      <div class="header-actions">
        <button class="btn btn-secondary" type="button" :disabled="!project?.template" @click="toggleTemplateEditor">
          {{ templateEditorVisible ? '收起系列规则' : '编辑系列规则' }}
        </button>
        <button class="btn btn-secondary" type="button" :disabled="refreshing" @click="refreshAll">
          {{ refreshing ? '刷新中…' : '刷新状态' }}
        </button>
      </div>
    </header>

    <ErrorCard v-if="error" :error="error" dismissible class="series-error" @dismiss="error = null" />
    <div v-if="hasActiveProjectTask" class="active-task-notice" role="status">
      合集任务正在后台顺序执行。为避免覆盖进度，完成前暂时停用追加、编辑和其他生成操作。
    </div>

    <div v-if="loading" class="loading-card card">
      <span class="series-spinner"></span>
      正在加载系列合集…
    </div>

    <template v-else-if="project">
      <section class="count-grid" aria-label="合集状态统计">
        <div v-for="count in statusSummary" :key="count.key" class="count-card" :class="count.tone">
          <strong>{{ count.value }}</strong>
          <span>{{ count.label }}</span>
        </div>
      </section>

      <section v-if="templateEditorVisible && project.template" class="card template-editor">
        <div class="section-heading template-editor-heading">
          <div>
            <h2>编辑系列规则</h2>
            <p>修改模板修订版，用于后续新加入的子主题。</p>
          </div>
          <span>当前修订：{{ project.template.revision ?? '未标记' }}</span>
        </div>
        <div class="snapshot-notice">
          <strong>规则更新不会追溯旧主题</strong>
          <p>只影响此后新加入的主题；旧主题继续使用创建时保存的模板快照，重新生成时也不会自动套用新规则。</p>
        </div>
        <div v-if="templateSavedMessage" class="template-success" role="status">{{ templateSavedMessage }}</div>
        <form @submit.prevent="saveTemplateRules">
          <div class="template-field-grid">
            <label>
              <span>视觉风格</span>
              <textarea v-model.trim="templateForm.visual_style" rows="3" maxlength="500"></textarea>
            </label>
            <label>
              <span>色板</span>
              <textarea v-model.trim="templateForm.palette" rows="3" maxlength="300"></textarea>
            </label>
            <label>
              <span>构图规则</span>
              <textarea v-model.trim="templateForm.composition" rows="3" maxlength="500"></textarea>
            </label>
            <label>
              <span>文案语气</span>
              <textarea v-model.trim="templateForm.copy_tone" rows="3" maxlength="300"></textarea>
            </label>
          </div>
          <label class="template-full-field">
            <span>角色设定（Character Bible）</span>
            <textarea v-model.trim="templateForm.character_bible" rows="4" maxlength="1500"></textarea>
          </label>
          <label class="template-full-field">
            <span>禁止元素</span>
            <textarea v-model.trim="templateForm.prohibited_elements" rows="3" maxlength="800"></textarea>
          </label>
          <label class="template-full-field">
            <span>版权与 IP 备注</span>
            <textarea v-model.trim="templateForm.ip_notice" rows="3" maxlength="800"></textarea>
          </label>
          <div class="locked-structure">
            <div>
              <strong>页面结构</strong>
              <span>{{ project.template.page_structure.page_count }} 页 · {{ structureLabel(project.template.page_structure.preset) }}</span>
            </div>
            <p>{{ collectionItemCount > 0 ? '合集已有子主题，为避免旧快照和新规则产生歧义，暂不允许修改页面结构。' : '页面结构暂在创建模板时设置。' }}</p>
          </div>
          <div class="template-editor-actions">
            <button class="btn btn-secondary" type="button" :disabled="savingTemplate" @click="toggleTemplateEditor">取消</button>
            <button class="btn btn-primary" type="submit" :disabled="savingTemplate || !templateRulesValid">
              {{ savingTemplate ? '保存中…' : '保存系列规则' }}
            </button>
          </div>
        </form>
      </section>

      <section class="card topic-manager">
        <div class="section-heading">
          <div>
            <h2>追加子主题</h2>
            <p>可输入一个或多行主题；合集不会因一次生成结束，之后仍可继续追加。</p>
          </div>
          <span>{{ appendTopics.length }} 个待添加</span>
        </div>
        <textarea
          v-model="appendText"
          class="control topic-textarea"
          rows="4"
          :disabled="hasActiveProjectTask"
          :placeholder="contentMode === 'character_sheet' ? '每行一个主题，例如：\n海贼王：路飞、娜美、索隆、山治\n蜡笔小新：小新、妈妈、向日葵' : '每行一个主题，例如：\n第一次用 Codex 接手旧项目\nCodex 帮我定位线上故障'"
        ></textarea>
        <div class="append-actions">
          <span :class="{ invalid: appendTopics.length > 10 }">单次最多追加 10 个，重复主题会自动去除。</span>
          <div class="append-submit-controls">
            <label class="content-mode-control">
              <span>内容模式</span>
              <select v-model="contentMode" class="control" :disabled="hasActiveProjectTask || addingItems">
                <option value="story">剧情小故事</option>
                <option value="character_sheet">精细角色图</option>
              </select>
            </label>
            <span v-if="contentMode === 'character_sheet'" class="content-mode-hint">请用“作品：角色A、角色B”填写；每个角色各生成 1 张独立图。</span>
            <button class="btn btn-primary small-btn" type="button" :disabled="hasActiveProjectTask || addingItems || !appendTopics.length || appendTopics.length > 10" @click="appendItems(appendTopics)">
              {{ addingItems ? '添加中…' : '添加到合集' }}
            </button>
          </div>
        </div>

        <div class="suggestion-panel">
          <div class="suggestion-header">
            <div>
              <strong>不知道下一篇做什么？</strong>
              <p>系统每次给出 5 个候选，默认只推荐原创方向。</p>
            </div>
            <label class="ip-switch">
              <input v-model="allowIpSuggestions" type="checkbox" />
              <span>允许第三方 IP 方向</span>
            </label>
            <button class="btn btn-secondary small-btn" type="button" :disabled="loadingSuggestions || (allowIpSuggestions && !ipRightsConfirmed)" @click="loadSuggestions">
              {{ loadingSuggestions ? '推荐中…' : '获取 5 个候选' }}
            </button>
          </div>
          <ErrorCard
            v-if="suggestionError"
            :error="suggestionError"
            dismissible
            class="suggestion-error"
            @dismiss="suggestionError = null"
          />
          <div v-if="suggestions.length" class="suggestion-list">
            <p v-if="suggestionNotice" class="suggestion-notice">{{ suggestionNotice }}</p>
            <div v-for="suggestion in suggestions" :key="suggestion.id" class="suggestion-option" :class="{ selected: selectedSuggestions.has(suggestion.id) }">
              <input
                type="checkbox"
                :checked="selectedSuggestions.has(suggestion.id)"
                @change="toggleSuggestion(suggestion.id)"
              />
              <span>
                <input v-model.trim="suggestion.topic" class="suggestion-topic-input" maxlength="200" aria-label="编辑候选主题" />
                <small v-if="suggestion.reason">{{ suggestion.reason }}</small>
              </span>
              <em v-if="suggestion.uses_ip">含 IP</em>
            </div>
            <button class="btn btn-secondary small-btn suggestion-add" type="button" :disabled="hasActiveProjectTask || !selectedSuggestions.size || addingItems || (selectedSuggestionNeedsRights && !ipRightsConfirmed)" @click="appendSelectedSuggestions">
              添加所选 {{ selectedSuggestions.size }} 个候选
            </button>
          </div>
          <div v-if="allowIpSuggestions || selectedSuggestionNeedsRights" class="ip-warning">
            <p>涉及动漫、影视、游戏、品牌或真实人物时，请自行确认授权与平台规则，候选不代表可直接商用。</p>
            <label><input v-model="ipRightsConfirmed" type="checkbox" /> 我确认所选及修改后的主题只会使用原创、已获授权或符合合理使用边界的内容。</label>
          </div>
        </div>
      </section>

      <section class="card collection-toolbar">
        <div class="search-row">
          <div class="search-control">
            <input v-model.trim="searchQuery" class="control" type="search" placeholder="搜索子主题" @keyup.enter="applyFilters" />
            <button type="button" @click="applyFilters">搜索</button>
          </div>
          <select v-model="statusFilter" class="control status-filter" @change="applyFilters">
            <option value="">全部状态</option>
            <option value="draft">待生成大纲</option>
            <option value="outline_ready">大纲待确认</option>
            <option value="confirmed">待生成作品</option>
            <option value="generating">生成中</option>
            <option value="completed">已完成</option>
            <option value="failed">失败</option>
          </select>
          <span class="result-count">共 {{ totalItems }} 个子主题</span>
        </div>

        <div v-if="selectedIds.size" class="bulk-toolbar">
          <strong>已选 {{ selectedIds.size }}/10 项</strong>
          <span>批量操作只作用于当前选择，不影响合集里的其他内容。</span>
          <div>
            <button class="btn btn-secondary small-btn" type="button" :disabled="bulkWorking || !bulkCanOutline" @click="runBulk('outlines')">批量生成大纲</button>
            <button class="btn btn-secondary small-btn" type="button" :disabled="bulkWorking || !bulkCanConfirm" @click="runBulk('confirm')">批量确认大纲</button>
            <button class="btn btn-primary small-btn" type="button" :disabled="bulkWorking || !bulkCanGenerate" @click="runBulk('generate')">批量生成作品</button>
          </div>
        </div>
      </section>

      <div v-if="itemsLoading" class="loading-card card"><span class="series-spinner"></span>正在加载子主题…</div>
      <section v-else-if="!items.length" class="empty-card card">
        <h2>{{ searchQuery || statusFilter ? '没有符合筛选条件的子主题' : '这个合集还没有子主题' }}</h2>
        <p>{{ searchQuery || statusFilter ? '调整搜索或状态筛选后再试。' : '在上方输入主题，或让系统推荐 5 个原创候选。' }}</p>
      </section>
      <div v-else class="item-list">
        <article v-for="item in items" :key="item.id" class="card item-card" :class="{ selected: selectedIds.has(item.id) }">
          <header class="item-header">
            <label class="item-select" :title="selectedIds.size >= 10 && !selectedIds.has(item.id) ? '一次最多选择 10 项' : '选择此项'">
              <input
                type="checkbox"
                :checked="selectedIds.has(item.id)"
                :disabled="selectedIds.size >= 10 && !selectedIds.has(item.id)"
                @change="toggleItem(item.id)"
              />
            </label>
            <div class="item-index">{{ item.index + 1 }}</div>
            <div class="item-title">
              <h2>{{ item.topic }}</h2>
              <p>{{ item.pages?.length || itemPageCount(item) }} 页<span v-if="itemProgressText(item)"> · {{ itemProgressText(item) }}</span></p>
            </div>
            <span class="content-mode-badge">{{ contentModeLabel(item.content_mode || 'story') }}</span>
            <span class="status-badge" :class="statusTone(item.status)">{{ itemStatusLabel(item.status) }}</span>
            <button
              class="item-collapse-toggle"
              type="button"
              :aria-expanded="!isItemCollapsed(item.id)"
              :aria-label="`${isItemCollapsed(item.id) ? '展开' : '收起'}子主题：${item.topic}`"
              @click="toggleItemCollapsed(item.id)"
            >
              {{ isItemCollapsed(item.id) ? '展开' : '收起' }}
            </button>
            <button
              class="item-delete-button"
              type="button"
              :disabled="itemBusy(item.id) || !canDeleteItem(item)"
              :title="canDeleteItem(item) ? '从合集移除（历史成品仍保留）' : (hasActiveProjectTask ? '合集有任务执行中，暂不能删除' : '生成中的子主题不能删除')"
              @click="deleteItem(item)"
            >
              {{ itemBusy(item.id) ? '处理中…' : '删除' }}
            </button>
          </header>

          <div class="item-mode-row">
            <label>
              <span>内容方向</span>
              <select
                :value="item.content_mode || 'story'"
                class="control"
                :disabled="!canChangeMode(item) || itemBusy(item.id)"
                @change="changeItemMode(item, $event)"
              >
                <option value="story">剧情小故事</option>
                <option value="character_sheet">精细角色图（每个角色一张，不生成故事）</option>
              </select>
            </label>
            <small v-if="!canChangeMode(item)">开始生成后不能切换内容方向</small>
          </div>

          <div v-if="!isItemCollapsed(item.id) && ['outline_ready', 'confirmed'].includes(item.status)" class="item-next-step">
            <ol class="item-step-track" aria-label="当前子主题制作步骤">
              <li class="done"><span>✓</span>大纲已生成</li>
              <li :class="{ active: item.status === 'outline_ready', done: item.status === 'confirmed' }"><span>{{ item.status === 'confirmed' ? '✓' : '2' }}</span>确认大纲</li>
              <li :class="{ active: item.status === 'confirmed' }"><span>3</span>生成作品</li>
            </ol>
            <div class="next-step-action">
              <div v-if="item.status === 'outline_ready'">
                <strong>{{ changedIds.has(item.id) ? '修改已保留，确认时会先自动保存' : '大纲已生成，请检查后确认' }}</strong>
                <p>确认大纲不会立即生成图片；确认完成后，下一步按钮会切换为“生成这篇作品”。</p>
              </div>
              <div v-else>
                <strong>大纲已确认，可以开始生成作品</strong>
                <p>将按此子主题创建图片、标题、正文和标签，不会影响合集中的其他主题。</p>
              </div>
              <button
                v-if="item.status === 'outline_ready'"
                class="btn btn-primary small-btn next-step-button"
                type="button"
                :disabled="itemBusy(item.id) || !canConfirmItem(item)"
                @click="runItemAction(item, 'confirm')"
              >
                {{ itemBusy(item.id) ? '确认中…' : '确认大纲，进入下一步' }}
              </button>
              <button
                v-else
                class="btn btn-primary small-btn next-step-button"
                type="button"
                :disabled="itemBusy(item.id) || !canGenerateItem(item)"
                @click="runItemAction(item, 'generate')"
              >
                {{ itemBusy(item.id) ? '启动中…' : '生成这篇作品' }}
              </button>
            </div>
          </div>

          <div v-if="!isItemCollapsed(item.id) && item.pages?.length" class="page-editor-list">
            <label v-for="page in item.pages" :key="page.index" class="page-editor">
              <span>第 {{ page.index + 1 }} 页 · {{ pageTypeLabel(page.type) }}</span>
              <textarea
                v-model="page.content"
                rows="3"
                :disabled="!canEditItem(item)"
                @input="markChanged(item.id)"
              ></textarea>
            </label>
          </div>
          <label v-else-if="!isItemCollapsed(item.id) && item.outline" class="raw-outline-editor">
            <span>大纲内容</span>
            <textarea v-model="item.outline" rows="7" :disabled="!canEditItem(item)" @input="markChanged(item.id)"></textarea>
          </label>
          <div v-else-if="!isItemCollapsed(item.id)" class="outline-placeholder">尚未生成大纲，可单独生成或勾选后批量生成。</div>

          <footer v-if="!isItemCollapsed(item.id)" class="item-actions">
            <span v-if="changedIds.has(item.id)" class="changed-hint">大纲已修改，尚未保存</span>
            <div>
              <button v-if="canOutlineItem(item)" class="btn btn-secondary small-btn" type="button" :disabled="itemBusy(item.id)" @click="runItemAction(item, 'outline')">生成大纲</button>
              <button v-if="canEditItem(item) && changedIds.has(item.id)" class="btn btn-secondary small-btn" type="button" :disabled="itemBusy(item.id)" @click="saveItem(item)">保存修改</button>
              <button v-if="canConfirmItem(item) && item.status !== 'outline_ready'" class="btn btn-secondary small-btn" type="button" :disabled="itemBusy(item.id)" @click="runItemAction(item, 'confirm')">确认大纲，进入下一步</button>
              <button v-if="canGenerateItem(item) && item.status !== 'confirmed'" class="btn btn-primary small-btn" type="button" :disabled="itemBusy(item.id)" @click="runItemAction(item, 'generate')">{{ item.status === 'failed' ? '重试生成' : '生成作品' }}</button>
              <button v-if="item.record_id" class="btn btn-secondary small-btn" type="button" :disabled="openingRecordId === item.record_id" @click="openResult(item)">
                {{ openingRecordId === item.record_id ? '打开中…' : '打开成品' }}
              </button>
            </div>
          </footer>
          <p v-if="!isItemCollapsed(item.id) && (item.error || item.error_message)" class="item-error">{{ itemErrorText(item) }}</p>
        </article>
      </div>

      <nav v-if="totalPages > 1" class="pagination" aria-label="子主题分页">
        <button class="btn btn-secondary small-btn" type="button" :disabled="currentPage <= 1" @click="changePage(currentPage - 1)">上一页</button>
        <span>第 {{ currentPage }} / {{ totalPages }} 页</span>
        <button class="btn btn-secondary small-btn" type="button" :disabled="currentPage >= totalPages" @click="changePage(currentPage + 1)">下一页</button>
      </nav>

      <section class="ip-notice">
        <strong>版权与长期运营提醒</strong>
        <p>{{ project.template?.ip_notice || '请仅使用原创或已获授权的角色、品牌和参考素材。长期系列中的每个子主题都应在发布前单独复核版权与平台合规风险。' }}</p>
      </section>
    </template>
  </div>
</template>

<script setup lang="ts">
import { computed, onMounted, onUnmounted, ref, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import {
  appendSeriesProjectItems,
  confirmSeriesProject,
  confirmSeriesProjectItem,
  deleteSeriesProjectItem,
  generateSeriesImages,
  generateSeriesItemOutline,
  generateSeriesOutlines,
  generateSeriesProjectItem,
  getHistory,
  getImageUrl,
  getSeriesProject,
  getSeriesProjectItems,
  getSeriesTopicSuggestions,
  updateSeriesProjectItem,
  updateSeriesTemplate,
  type Page,
  type SeriesContentMode,
  type SeriesProject,
  type SeriesProjectItem,
  type SeriesTopicSuggestion
} from '../api'
import { useGeneratorStore, type GeneratedImage } from '../stores/generator'
import ErrorCard from '../components/common/ErrorCard.vue'
import { normalizeApiError, type AppError } from '../utils/errors'
import { seriesContextFromHistory } from '../composables/useGenerationRestore'

type BulkAction = 'outlines' | 'confirm' | 'generate'
type ItemAction = 'outline' | 'confirm' | 'generate'
interface SuggestionDraft extends SeriesTopicSuggestion { id: string; originalTopic: string }

const route = useRoute()
const router = useRouter()
const store = useGeneratorStore()
const project = ref<SeriesProject | null>(null)
const items = ref<SeriesProjectItem[]>([])
const loading = ref(true)
const itemsLoading = ref(false)
const refreshing = ref(false)
const addingItems = ref(false)
const loadingSuggestions = ref(false)
const bulkWorking = ref(false)
const busyItemIds = ref(new Set<string>())
const changedIds = ref(new Set<string>())
const selectedIds = ref(new Set<string>())
const collapsedItemIds = ref(new Set<string>())
const openingRecordId = ref<string | null>(null)
const error = ref<AppError | null>(null)
const templateEditorVisible = ref(false)
const savingTemplate = ref(false)
const templateSavedMessage = ref('')
const templateForm = ref({
  visual_style: '',
  palette: '',
  composition: '',
  character_bible: '',
  copy_tone: '',
  prohibited_elements: '',
  ip_notice: ''
})
const appendText = ref('')
const contentMode = ref<SeriesContentMode>('story')
const contentModeInitialized = ref(false)
const suggestions = ref<SuggestionDraft[]>([])
const suggestionNotice = ref('')
const suggestionError = ref<AppError | null>(null)
const selectedSuggestions = ref(new Set<string>())
const allowIpSuggestions = ref(false)
const ipRightsConfirmed = ref(false)
const searchQuery = ref('')
const statusFilter = ref('')
const currentPage = ref(1)
const pageSize = 10
const totalItems = ref(0)
const totalPages = ref(1)
let pollTimer: number | null = null

const projectId = computed(() => String(route.params.id || ''))
const appendTopics = computed(() => uniqueTopics(appendText.value))
const selectedItems = computed(() => items.value.filter(item => selectedIds.value.has(item.id)))
const selectedSuggestionNeedsRights = computed(() => suggestions.value.some(suggestion => (
  selectedSuggestions.value.has(suggestion.id)
  && (Boolean(suggestion.uses_ip) || suggestion.topic !== suggestion.originalTopic)
)))
const bulkCanOutline = computed(() => selectedItems.value.length > 0 && selectedItems.value.every(canOutlineItem))
const bulkCanConfirm = computed(() => selectedItems.value.length > 0 && selectedItems.value.every(canConfirmItem) && selectedItems.value.every(item => !changedIds.value.has(item.id)))
const bulkCanGenerate = computed(() => selectedItems.value.length > 0 && selectedItems.value.every(canGenerateItem))
const templateRulesValid = computed(() => Boolean(
  templateForm.value.visual_style
  && templateForm.value.palette
  && templateForm.value.composition
  && templateForm.value.copy_tone
))

const counts = computed(() => {
  const fromProject = project.value?.status_counts
  if (fromProject && Object.keys(fromProject).length) return fromProject
  return items.value.reduce<Record<string, number>>((result, item) => {
    result[item.status] = (result[item.status] || 0) + 1
    return result
  }, {})
})
const hasActiveProjectTask = computed(() => ['queued', 'outlining', 'generating', 'running', 'processing']
  .some(status => (counts.value[status] || 0) > 0))
const collectionItemCount = computed(() => project.value?.item_count ?? (sumCounts(counts.value) || totalItems.value))
const statusSummary = computed(() => [
  { key: 'total', label: '全部主题', value: collectionItemCount.value, tone: '' },
  { key: 'draft', label: '待生成大纲', value: countStatuses(['draft']), tone: '' },
  { key: 'review', label: '大纲待确认', value: countStatuses(['outline_ready']), tone: 'review' },
  { key: 'confirmed', label: '待生成作品', value: countStatuses(['confirmed']), tone: 'confirmed' },
  { key: 'active', label: '生成中', value: countStatuses(['queued', 'outlining', 'generating', 'running', 'processing']), tone: 'active' },
  { key: 'completed', label: '已完成', value: countStatuses(['completed', 'done']), tone: 'success' },
  { key: 'failed', label: '失败', value: countStatuses(['failed', 'error']), tone: 'error' }
])

function uniqueTopics(text: string) {
  return text.split(/\r?\n/).map(value => value.trim()).filter((value, index, list) => Boolean(value) && list.indexOf(value) === index)
}
function sumCounts(value: Record<string, number>) { return Object.values(value).reduce((sum, count) => sum + count, 0) }
function countStatuses(statuses: string[]) { return statuses.reduce((sum, status) => sum + (counts.value[status] || 0), 0) }
function structureLabel(preset: string) {
  const labels: Record<string, string> = {
    standard: '标准结构',
    comparison_two: '前后对比',
    comparison_four: '完整对比'
  }
  return labels[preset] || preset
}

function fillTemplateForm() {
  const template = project.value?.template
  if (!template) return
  templateForm.value = {
    visual_style: template.visual_style || '',
    palette: template.palette || '',
    composition: template.composition || '',
    character_bible: template.character_bible || '',
    copy_tone: template.copy_tone || '',
    prohibited_elements: Array.isArray(template.prohibited_elements)
      ? template.prohibited_elements.join('、')
      : template.prohibited_elements || '',
    ip_notice: template.ip_notice || ''
  }
}
function toggleTemplateEditor() {
  templateEditorVisible.value = !templateEditorVisible.value
  templateSavedMessage.value = ''
  if (templateEditorVisible.value) fillTemplateForm()
}
async function saveTemplateRules() {
  const template = project.value?.template
  if (!template || !templateRulesValid.value) return
  savingTemplate.value = true
  error.value = null
  templateSavedMessage.value = ''
  try {
    const result = await updateSeriesTemplate(template.id, { ...templateForm.value })
    if (!result.success) {
      error.value = normalizeApiError(result.error || result.error_message || '保存系列规则失败', '保存系列规则失败')
      return
    }
    await refreshProject()
    fillTemplateForm()
    templateSavedMessage.value = result.message || '系列规则已更新；此后新加入的主题将使用新修订版。'
  } finally {
    savingTemplate.value = false
  }
}

async function refreshProject() {
  const result = await getSeriesProject(projectId.value)
  if (result.success && result.project) {
    project.value = result.project
    if (!contentModeInitialized.value && result.project.content_mode) {
      contentMode.value = result.project.content_mode
      contentModeInitialized.value = true
    }
  }
  else error.value = normalizeApiError(result.error || result.error_message || '加载系列合集失败', '加载系列合集失败')
}

async function refreshItems(showLoading = true) {
  if (showLoading) itemsLoading.value = true
  try {
    const result = await getSeriesProjectItems(projectId.value, {
      page: currentPage.value,
      pageSize,
      query: searchQuery.value,
      status: statusFilter.value
    })
    if (result.success) {
      const freshItems = cloneItems(result.items || [])
      items.value = freshItems.map(fresh => {
        if (!changedIds.value.has(fresh.id)) return fresh
        const local = items.value.find(item => item.id === fresh.id)
        return local ? { ...fresh, outline: local.outline, pages: local.pages } : fresh
      })
      totalItems.value = result.total ?? items.value.length
      totalPages.value = Math.max(1, result.total_pages || Math.ceil(totalItems.value / pageSize))
      selectedIds.value = new Set(Array.from(selectedIds.value).filter(id => items.value.some(item => item.id === id)))
      schedulePolling()
    } else {
      error.value = normalizeApiError(result.error || result.error_message || '加载合集子主题失败', '加载合集子主题失败')
    }
  } finally {
    itemsLoading.value = false
  }
}

async function refreshAll() {
  refreshing.value = true
  error.value = null
  try { await Promise.all([refreshProject(), refreshItems(false)]) } finally { refreshing.value = false; loading.value = false }
}

async function appendItems(
  topics: string[],
  source: 'user' | 'system' | 'user_modified_system' = 'user',
  refresh = true,
  ipAcknowledged = false
): Promise<boolean> {
  if (!topics.length) return false
  addingItems.value = true
  error.value = null
  try {
    const result = await appendSeriesProjectItems(projectId.value, topics, source, ipAcknowledged, contentMode.value)
    if (!result.success) {
      error.value = normalizeApiError(result.error || result.error_message || '追加子主题失败', '追加子主题失败')
      return false
    }
    if (source === 'user') appendText.value = ''
    if (refresh) {
      selectedSuggestions.value = new Set()
      currentPage.value = 1
      await refreshAll()
    }
    return true
  } finally { addingItems.value = false }
}

async function loadSuggestions() {
  loadingSuggestions.value = true
  suggestionError.value = null
  try {
    const result = await getSeriesTopicSuggestions(projectId.value, allowIpSuggestions.value)
    if (result.success) {
      suggestionError.value = null
      suggestions.value = (result.suggestions || []).slice(0, 5).map((suggestion, index) => ({
        ...suggestion,
        id: `suggestion-${Date.now()}-${index}`,
        originalTopic: suggestion.topic
      }))
      selectedSuggestions.value = new Set()
      suggestionNotice.value = result.warning || ''
    } else suggestionError.value = normalizeApiError(result.error || result.error_message || '获取主题候选失败', '获取主题候选失败')
  } finally { loadingSuggestions.value = false }
}

function toggleSuggestion(id: string) {
  const next = new Set(selectedSuggestions.value)
  if (next.has(id)) next.delete(id); else next.add(id)
  selectedSuggestions.value = next
}
async function appendSelectedSuggestions() {
  const selected = suggestions.value.filter(suggestion => selectedSuggestions.value.has(suggestion.id) && suggestion.topic)
  const unchanged = selected.filter(suggestion => suggestion.topic === suggestion.originalTopic).map(suggestion => suggestion.topic)
  const changed = selected.filter(suggestion => suggestion.topic !== suggestion.originalTopic).map(suggestion => suggestion.topic)
  let added = false
  if (unchanged.length) added = await appendItems(unchanged, 'system', false, ipRightsConfirmed.value) || added
  if (changed.length) added = await appendItems(changed, 'user_modified_system', false, ipRightsConfirmed.value) || added
  if (added) {
    selectedSuggestions.value = new Set()
    currentPage.value = 1
    await refreshAll()
  }
}
function toggleItem(itemId: string) {
  const next = new Set(selectedIds.value)
  if (next.has(itemId)) next.delete(itemId)
  else if (next.size < 10) next.add(itemId)
  selectedIds.value = next
}
function isItemCollapsed(itemId: string) { return collapsedItemIds.value.has(itemId) }
function toggleItemCollapsed(itemId: string) {
  const next = new Set(collapsedItemIds.value)
  if (next.has(itemId)) next.delete(itemId); else next.add(itemId)
  collapsedItemIds.value = next
}

function canDeleteItem(item: SeriesProjectItem) {
  return !hasActiveProjectTask.value
    && !['queued', 'outlining', 'generating', 'running', 'processing'].includes(item.status)
}

async function deleteItem(item: SeriesProjectItem) {
  if (!canDeleteItem(item) || itemBusy(item.id)) return
  const confirmed = window.confirm(`确定从合集移除“${item.topic}”吗？\n\n只会移除合集中的子主题，已生成的历史成品和图片仍会保留。`)
  if (!confirmed) return
  setItemBusy(item.id, true)
  error.value = null
  try {
    const result = await deleteSeriesProjectItem(projectId.value, item.id)
    if (!result.success) {
      error.value = normalizeApiError(result.error || result.error_message || '删除子主题失败', '删除子主题失败')
      return
    }
    const selected = new Set(selectedIds.value)
    selected.delete(item.id)
    selectedIds.value = selected
    const changed = new Set(changedIds.value)
    changed.delete(item.id)
    changedIds.value = changed
    const collapsed = new Set(collapsedItemIds.value)
    collapsed.delete(item.id)
    collapsedItemIds.value = collapsed
    // 删除当前页最后一项后，从第一页重新拉取，避免停留在不存在的分页。
    currentPage.value = 1
    await refreshAll()
  } finally { setItemBusy(item.id, false) }
}

async function runBulk(action: BulkAction) {
  const ids = Array.from(selectedIds.value).slice(0, 10)
  if (!ids.length) return
  bulkWorking.value = true
  error.value = null
  try {
    const result = action === 'outlines'
      ? await generateSeriesOutlines(projectId.value, ids)
      : action === 'confirm'
        ? await confirmSeriesProject(projectId.value, ids)
        : await generateSeriesImages(projectId.value, ids)
    if (!result.success) error.value = normalizeApiError(result.error || result.error_message || '批量操作失败', '批量操作失败')
    else { selectedIds.value = new Set(); await refreshAll() }
  } finally { bulkWorking.value = false }
}

async function runItemAction(item: SeriesProjectItem, action: ItemAction) {
  setItemBusy(item.id, true)
  error.value = null
  try {
    if (action === 'confirm' && changedIds.value.has(item.id)) {
      const saved = await saveItemRequest(item)
      if (!saved) return
    }
    const result = action === 'outline'
      ? await generateSeriesItemOutline(projectId.value, item.id)
      : action === 'confirm'
        ? await confirmSeriesProjectItem(projectId.value, item.id)
        : await generateSeriesProjectItem(projectId.value, item.id)
    if (!result.success) error.value = normalizeApiError(result.error || result.error_message || '子主题操作失败', '子主题操作失败')
    else await refreshAll()
  } finally { setItemBusy(item.id, false) }
}

async function saveItemRequest(item: SeriesProjectItem) {
  const result = await updateSeriesProjectItem(projectId.value, item.id, {
    outline: syncOutline(item),
    pages: (item.pages || []).map(page => ({ ...page }))
  })
  if (!result.success) {
    error.value = normalizeApiError(result.error || result.error_message || '保存大纲失败', '保存大纲失败')
    return false
  }
  const next = new Set(changedIds.value); next.delete(item.id); changedIds.value = next
  return true
}
async function saveItem(item: SeriesProjectItem) {
  setItemBusy(item.id, true)
  try { if (await saveItemRequest(item)) await refreshAll() } finally { setItemBusy(item.id, false) }
}

function canOutlineItem(item: SeriesProjectItem) { return !hasActiveProjectTask.value && !(item.pages || []).length && !['outlining', 'queued', 'generating', 'running', 'completed', 'done'].includes(item.status) }
function canEditItem(item: SeriesProjectItem) { return !hasActiveProjectTask.value && Boolean((item.pages || []).length || item.outline) && ['outline_ready', 'draft', 'failed'].includes(item.status) && !item.record_id }
function canConfirmItem(item: SeriesProjectItem) { return !hasActiveProjectTask.value && Boolean((item.pages || []).length) && ['outline_ready', 'draft', 'failed'].includes(item.status) && !item.record_id }
function canGenerateItem(item: SeriesProjectItem) { return !hasActiveProjectTask.value && (item.status === 'confirmed' || (item.status === 'failed' && Boolean((item.pages || []).length) && (Boolean(item.record_id) || ['confirmed', 'approved'].includes(item.outline_status || '')))) }
function syncOutline(item: SeriesProjectItem) { return (item.pages || []).length ? item.pages.map(page => page.content.trim()).join('\n\n<page>\n\n') : item.outline }
function markChanged(itemId: string) { const next = new Set(changedIds.value); next.add(itemId); changedIds.value = next }
function setItemBusy(itemId: string, busy: boolean) { const next = new Set(busyItemIds.value); if (busy) next.add(itemId); else next.delete(itemId); busyItemIds.value = next }
function itemBusy(itemId: string) { return busyItemIds.value.has(itemId) }
function canChangeMode(item: SeriesProjectItem) {
  return !hasActiveProjectTask.value && !item.record_id && ['draft', 'failed'].includes(item.status)
}
async function changeItemMode(item: SeriesProjectItem, event: Event) {
  const value = (event.target as HTMLSelectElement).value as SeriesContentMode
  const current = item.content_mode || 'story'
  if (value === current || !canChangeMode(item)) return
  setItemBusy(item.id, true)
  error.value = null
  try {
    const result = await updateSeriesProjectItem(projectId.value, item.id, { content_mode: value })
    if (!result.success) error.value = normalizeApiError(result.error || result.error_message || '切换内容方向失败', '切换内容方向失败')
    else await refreshAll()
  } finally { setItemBusy(item.id, false) }
}

function guardUnsavedChanges() {
  if (!changedIds.value.size) return true
  error.value = normalizeApiError('当前页面还有未保存的大纲修改，请先保存再切换筛选或分页。', '存在未保存修改')
  return false
}
function applyFilters() { if (!guardUnsavedChanges()) return; currentPage.value = 1; selectedIds.value = new Set(); void refreshItems() }
function changePage(page: number) { if (!guardUnsavedChanges()) return; currentPage.value = page; selectedIds.value = new Set(); void refreshItems() }
function cloneItems(values: SeriesProjectItem[]) { return values.map(item => ({ ...item, pages: (item.pages || []).map(page => ({ ...page })) })) }

async function openResult(item: SeriesProjectItem) {
  if (!item.record_id) return
  openingRecordId.value = item.record_id
  error.value = null
  try {
    const result = await getHistory(item.record_id)
    if (!result.success || !result.record) {
      error.value = normalizeApiError(result.error || result.error_message || '打开系列成品失败', '打开系列成品失败')
      return
    }
    const record = result.record
    const taskId = record.images.task_id
    const generated = record.images.generated || []
    const images: GeneratedImage[] = record.outline.pages.map((page, index) => {
      const filename = generated[page.index] || generated[index] || ''
      return { index: page.index, url: filename && taskId ? getImageUrl(taskId, filename) : '', status: filename ? 'done' : 'error', retryable: !filename }
    })
    const doneCount = images.filter(image => image.status === 'done').length
    store.replaceWork({
      topic: record.title, outline: record.outline, recordId: record.id, taskId, images,
      seriesContext: seriesContextFromHistory(record, {
        series_id: record.series_id || project.value?.id || undefined,
        series_template_id: record.series_template_id || project.value?.template_id || undefined,
        series_project_id: record.series_project_id || project.value?.id || undefined,
        series_item_id: record.series_item_id || item.id,
        series_item_index: record.series_item_index ?? item.index,
        series_item_title: record.series_item_title || item.topic
      }),
      progress: { current: doneCount, total: images.length, status: doneCount === images.length ? 'done' : 'error' },
      stage: doneCount === images.length ? 'result' : 'generating', content: record.content
    })
    await router.push(doneCount === images.length ? '/result' : '/outline')
  } finally { openingRecordId.value = null }
}

const statusLabels: Record<string, string> = { draft: '待生成大纲', outlining: '正在生成大纲', outline_ready: '大纲待确认', confirmed: '待生成作品', queued: '排队中', generating: '生成中', running: '生成中', completed: '已完成', done: '已完成', failed: '失败' }
function itemStatusLabel(status: string) { return statusLabels[status] || status || '待处理' }
function contentModeLabel(mode: SeriesProjectItem['content_mode']) {
  return mode === 'character_sheet' ? '精细角色图' : '剧情小故事'
}
function itemPageCount(item: SeriesProjectItem) {
  return item.content_mode === 'character_sheet'
    ? item.character_names?.length || item.template_snapshot?.page_structure.page_count || 1
    : project.value?.template?.page_structure.page_count || 0
}
function statusTone(status: string) { return ['completed', 'done'].includes(status) ? 'success' : ['failed', 'error'].includes(status) ? 'error' : ['queued', 'outlining', 'generating', 'running', 'processing'].includes(status) ? 'active' : '' }
function pageTypeLabel(type: Page['type']) { return type === 'cover' ? '封面' : type === 'summary' ? '总结' : '内容' }
function itemProgressText(item: SeriesProjectItem) { const value = item.progress; if (typeof value === 'number') return `${Math.round(value)}%`; return value?.total ? `${value.current}/${value.total}` : '' }
function itemErrorText(item: SeriesProjectItem) { const value = normalizeApiError(item.error || item.error_message || '生成失败', '生成失败'); return value.suggestion || value.detail }

function schedulePolling() {
  stopPolling()
  // The project summary and paged item list are fetched independently. During
  // the short window where one response is newer than the other, keep polling
  // if either source still reports an active task so the next-step CTA cannot
  // remain disabled indefinitely.
  if (hasActiveProjectTask.value || items.value.some(item => ['outlining', 'queued', 'generating', 'running', 'processing'].includes(item.status))) {
    pollTimer = window.setTimeout(() => refreshAll(), 2000)
  }
}
function stopPolling() { if (pollTimer !== null) window.clearTimeout(pollTimer); pollTimer = null }

onMounted(refreshAll)
onUnmounted(stopPolling)
watch(allowIpSuggestions, () => {
  suggestions.value = []
  suggestionNotice.value = ''
  suggestionError.value = null
  selectedSuggestions.value = new Set()
  if (!allowIpSuggestions.value) ipRightsConfirmed.value = false
})
</script>

<style scoped>
.series-page { max-width: 1080px; }
.series-header { align-items: flex-end; }
.header-actions { display: flex; flex-wrap: wrap; justify-content: flex-end; gap: 8px; }
.back-link { margin-bottom: 8px; padding: 0; border: 0; background: transparent; color: var(--primary); cursor: pointer; font: inherit; font-size: 13px; }
.series-error { margin-bottom: 16px; }
.active-task-notice { margin-bottom: 14px; padding: 10px 12px; border: 1px solid color-mix(in srgb, var(--primary) 38%, var(--border-color)); border-radius: 10px; background: var(--primary-fade); color: var(--text-sub); font-size: 11px; }
.loading-card { display: flex; align-items: center; justify-content: center; gap: 10px; min-height: 180px; color: var(--text-sub); }
.series-spinner { width: 21px; height: 21px; border: 2px solid var(--border-color); border-top-color: var(--primary); border-radius: 50%; animation: spin .8s linear infinite; }
@keyframes spin { to { transform: rotate(360deg); } }
.count-grid { display: grid; grid-template-columns: repeat(7, minmax(0, 1fr)); gap: 8px; margin-bottom: 18px; }
.count-card { display: grid; gap: 1px; padding: 12px; border: 1px solid var(--border-color); border-radius: 12px; background: var(--bg-card); box-shadow: var(--shadow-sm); }
.count-card strong { color: var(--text-main); font-size: 20px; }
.count-card span { color: var(--text-secondary); font-size: 10px; }
.count-card.active strong, .count-card.review strong { color: var(--primary); }
.count-card.success strong { color: var(--primary); }
.count-card.error strong { color: var(--primary-active); }
.template-editor { padding: 20px; }
.template-editor-heading { margin-bottom: 14px; }
.snapshot-notice { margin-bottom: 14px; padding: 11px 12px; border: 1px solid color-mix(in srgb, var(--primary) 42%, var(--border-color)); border-radius: 9px; background: var(--primary-fade); }
.snapshot-notice strong { color: var(--text-main); font-size: 12px; }
.snapshot-notice p { margin: 2px 0 0; color: var(--text-sub); font-size: 10px; line-height: 1.5; }
.template-success { margin-bottom: 12px; padding: 9px 11px; border-radius: 8px; background: var(--primary-fade); color: var(--primary); font-size: 11px; }
.template-field-grid { display: grid; grid-template-columns: repeat(2, minmax(0, 1fr)); gap: 12px; }
.template-field-grid label, .template-full-field { display: grid; gap: 5px; color: var(--text-main); font-size: 12px; font-weight: 600; }
.template-field-grid textarea, .template-full-field textarea { width: 100%; resize: vertical; padding: 9px 10px; border: 1px solid var(--border-color); border-radius: 8px; outline: none; background: var(--bg-control); color: var(--text-main); font: inherit; font-size: 12px; line-height: 1.5; }
.template-field-grid textarea:focus, .template-full-field textarea:focus { border-color: var(--primary); box-shadow: 0 0 0 3px var(--primary-fade); }
.template-full-field { margin-top: 12px; }
.locked-structure { display: flex; align-items: center; justify-content: space-between; gap: 16px; margin-top: 14px; padding: 10px 12px; border-radius: 9px; background: var(--bg-muted); }
.locked-structure > div { display: grid; gap: 1px; }
.locked-structure strong { color: var(--text-main); font-size: 12px; }
.locked-structure span, .locked-structure p { color: var(--text-sub); font-size: 10px; }
.locked-structure p { max-width: 520px; margin: 0; text-align: right; }
.template-editor-actions { display: flex; justify-content: flex-end; gap: 8px; margin-top: 16px; }
.topic-manager, .collection-toolbar, .item-card { padding: 20px; }
.section-heading, .suggestion-header, .append-actions, .search-row, .bulk-toolbar, .item-header, .item-actions { display: flex; align-items: center; justify-content: space-between; gap: 12px; }
.section-heading h2 { margin: 0; color: var(--text-main); font-size: 18px; }
.section-heading p, .suggestion-header p { margin: 2px 0 0; color: var(--text-sub); font-size: 11px; }
.section-heading > span { color: var(--text-secondary); font-size: 11px; }
.control { box-sizing: border-box; padding: 9px 11px; border: 1px solid var(--border-color); border-radius: 9px; outline: none; background: var(--bg-control); color: var(--text-main); font: inherit; }
.control:focus { border-color: var(--primary); box-shadow: 0 0 0 3px var(--primary-fade); }
.topic-textarea { width: 100%; margin-top: 13px; resize: vertical; font-size: 13px; line-height: 1.5; }
.append-actions { margin-top: 8px; }
.append-actions span { color: var(--text-secondary); font-size: 11px; }
.append-actions span.invalid { color: var(--primary); }
.append-submit-controls { display: flex; align-items: flex-end; gap: 8px; }
.content-mode-control { display: grid; gap: 3px; color: var(--text-secondary); font-size: 10px; }
.content-mode-control .control { min-width: 126px; padding: 7px 9px; font-size: 11px; }
.content-mode-hint { max-width: 230px; color: var(--text-sub); font-size: 10px; line-height: 1.35; }
.small-btn { padding: 7px 12px; font-size: 12px; }
.suggestion-panel { margin-top: 18px; padding-top: 16px; border-top: 1px solid var(--border-color); }
.suggestion-header > div:first-child { flex: 1; }
.suggestion-error { margin-top: 12px; }
.ip-switch { display: flex; align-items: center; gap: 6px; color: var(--text-sub); cursor: pointer; font-size: 11px; }
.ip-switch input { accent-color: var(--primary); }
.suggestion-list { display: grid; gap: 7px; margin-top: 12px; }
.suggestion-notice { margin: 0; padding: 8px 10px; border-radius: 8px; background: var(--bg-muted); color: var(--text-sub); font-size: 10px; }
.suggestion-option { display: flex; align-items: center; gap: 9px; padding: 9px 10px; border: 1px solid var(--border-color); border-radius: 9px; background: var(--bg-control); cursor: pointer; }
.suggestion-option.selected { border-color: var(--primary); background: var(--primary-fade); }
.suggestion-option input { accent-color: var(--primary); }
.suggestion-option span { display: grid; flex: 1; }
.suggestion-topic-input { width: 100%; padding: 2px 4px; border: 1px solid transparent; border-radius: 5px; outline: none; background: transparent; color: var(--text-main); font: inherit; font-size: 12px; font-weight: 600; }
.suggestion-topic-input:focus { border-color: var(--primary); background: var(--bg-control); }
.suggestion-option small { color: var(--text-sub); font-size: 10px; }
.suggestion-option em { color: var(--primary); font-size: 10px; font-style: normal; }
.suggestion-add { width: fit-content; margin: 4px 0 0 auto; }
.ip-warning { margin-top: 9px; padding: 9px 10px; border-radius: 8px; background: var(--primary-fade); color: var(--primary); font-size: 10px; }
.ip-warning p { margin: 0 0 5px; }
.ip-warning label { display: flex; align-items: flex-start; gap: 6px; color: var(--text-main); cursor: pointer; }
.ip-warning input { margin-top: 2px; accent-color: var(--primary); }
.search-row { flex-wrap: wrap; }
.search-control { display: flex; min-width: min(100%, 320px); flex: 1; }
.search-control input { width: 100%; border-radius: 9px 0 0 9px; }
.search-control button { padding: 0 13px; border: 1px solid var(--border-color); border-left: 0; border-radius: 0 9px 9px 0; background: var(--bg-muted); color: var(--text-main); cursor: pointer; }
.status-filter { min-width: 145px; }
.result-count { color: var(--text-secondary); font-size: 11px; }
.bulk-toolbar { flex-wrap: wrap; margin-top: 14px; padding: 11px 12px; border-radius: 10px; background: var(--primary-fade); }
.bulk-toolbar strong { color: var(--primary); font-size: 12px; }
.bulk-toolbar > span { flex: 1; color: var(--text-sub); font-size: 10px; }
.bulk-toolbar > div { display: flex; flex-wrap: wrap; gap: 7px; }
.empty-card { padding: 50px 20px; text-align: center; }
.empty-card h2 { margin: 0 0 6px; color: var(--text-main); font-size: 18px; }
.empty-card p { margin: 0; color: var(--text-sub); font-size: 12px; }
.item-list { display: grid; gap: 14px; }
.item-card { margin: 0; }
.item-card.selected { border-color: var(--primary); }
.item-mode-row { display: flex; align-items: center; gap: 10px; margin-top: 12px; padding: 9px 10px; border-radius: 9px; background: var(--bg-subtle); }
.item-mode-row label { display: flex; align-items: center; gap: 8px; color: var(--text-sub); font-size: 10px; }
.item-mode-row .control { min-width: 210px; padding: 6px 8px; font-size: 11px; }
.item-mode-row small { color: var(--text-secondary); font-size: 10px; }
.item-select input { width: 16px; height: 16px; accent-color: var(--primary); }
.item-index { display: inline-flex; align-items: center; justify-content: center; flex: 0 0 auto; width: 32px; height: 32px; border-radius: 9px; background: var(--primary-fade); color: var(--primary); font-weight: 700; }
.item-title { min-width: 0; flex: 1; }
.item-title h2 { margin: 0; overflow: hidden; color: var(--text-main); font-size: 15px; text-overflow: ellipsis; white-space: nowrap; }
.item-title p { margin: 2px 0 0; color: var(--text-secondary); font-size: 10px; }
.status-badge { padding: 4px 8px; border: 1px solid var(--border-color); border-radius: 999px; background: var(--bg-muted); color: var(--text-sub); font-size: 10px; }
.status-badge.active, .status-badge.success { border-color: var(--primary); color: var(--primary); }
.status-badge.error { color: var(--primary-active); }
.content-mode-badge { padding: 4px 8px; border-radius: 999px; background: var(--primary-fade); color: var(--primary); font-size: 10px; white-space: nowrap; }
.item-collapse-toggle { flex: 0 0 auto; padding: 4px 7px; border: 1px solid var(--border-color); border-radius: 7px; background: var(--bg-control); color: var(--text-sub); cursor: pointer; font: inherit; font-size: 10px; }
.item-collapse-toggle:hover { border-color: var(--primary); color: var(--primary); }
.item-delete-button { flex: 0 0 auto; padding: 4px 7px; border: 1px solid color-mix(in srgb, var(--primary-active) 38%, var(--border-color)); border-radius: 7px; background: var(--bg-control); color: var(--primary-active); cursor: pointer; font: inherit; font-size: 10px; }
.item-delete-button:hover:not(:disabled) { border-color: var(--primary-active); background: color-mix(in srgb, var(--primary-active) 8%, var(--bg-control)); }
.item-delete-button:disabled { cursor: not-allowed; opacity: .55; }
.item-next-step { margin-top: 14px; padding: 12px; border: 1px solid var(--border-color); border-radius: 10px; background: var(--bg-subtle); }
.item-step-track { display: grid; grid-template-columns: repeat(3, minmax(0, 1fr)); gap: 7px; margin: 0; padding: 0; list-style: none; }
.item-step-track li { display: flex; align-items: center; gap: 6px; color: var(--text-secondary); font-size: 10px; }
.item-step-track li span { display: inline-flex; align-items: center; justify-content: center; width: 20px; height: 20px; border: 1px solid var(--border-color); border-radius: 50%; background: var(--bg-control); color: var(--text-secondary); }
.item-step-track li.active { color: var(--primary); font-weight: 600; }
.item-step-track li.active span { border-color: var(--primary); color: var(--primary); box-shadow: 0 0 0 3px var(--primary-fade); }
.item-step-track li.done { color: var(--text-sub); }
.item-step-track li.done span { border-color: var(--primary); background: var(--primary); color: var(--bg-card); }
.next-step-action { display: flex; align-items: center; justify-content: space-between; gap: 16px; margin-top: 11px; padding-top: 10px; border-top: 1px solid var(--border-color); }
.next-step-action > div { min-width: 0; }
.next-step-action strong { color: var(--text-main); font-size: 12px; }
.next-step-action p { margin: 2px 0 0; color: var(--text-sub); font-size: 10px; line-height: 1.45; }
.next-step-button { flex: 0 0 auto; white-space: nowrap; }
.page-editor-list { display: grid; gap: 8px; margin-top: 14px; }
.page-editor, .raw-outline-editor { display: grid; gap: 4px; color: var(--text-sub); font-size: 10px; }
.page-editor textarea, .raw-outline-editor textarea { width: 100%; resize: vertical; padding: 8px 9px; border: 1px solid var(--border-color); border-radius: 8px; outline: none; background: var(--bg-control); color: var(--text-main); font: inherit; font-size: 12px; line-height: 1.5; }
.page-editor textarea:focus, .raw-outline-editor textarea:focus { border-color: var(--primary); box-shadow: 0 0 0 3px var(--primary-fade); }
.raw-outline-editor { margin-top: 14px; }
.outline-placeholder { margin-top: 14px; padding: 24px; border: 1px dashed var(--border-color); border-radius: 9px; background: var(--bg-subtle); color: var(--text-secondary); text-align: center; font-size: 11px; }
.item-actions { margin-top: 12px; }
.item-actions > div { display: flex; flex-wrap: wrap; justify-content: flex-end; gap: 7px; }
.changed-hint { margin-right: auto; color: var(--primary); font-size: 10px; }
.item-error { margin: 9px 0 0; padding: 8px 10px; border-radius: 8px; background: var(--primary-fade); color: var(--primary-active); font-size: 10px; }
.pagination { display: flex; align-items: center; justify-content: center; gap: 14px; margin: 20px 0; color: var(--text-sub); font-size: 12px; }
.ip-notice { margin-top: 20px; padding: 12px 14px; border: 1px solid color-mix(in srgb, var(--primary) 42%, var(--border-color)); border-radius: 10px; background: var(--primary-fade); }
.ip-notice strong { font-size: 12px; }
.ip-notice p { margin: 3px 0 0; color: var(--text-sub); font-size: 10px; line-height: 1.55; }
@media (max-width: 900px) { .count-grid { grid-template-columns: repeat(4, minmax(0, 1fr)); } }
@media (max-width: 700px) {
  .series-header, .section-heading, .suggestion-header, .append-actions, .item-actions { align-items: stretch; flex-direction: column; }
  .header-actions, .template-editor-actions { justify-content: flex-start; }
  .template-field-grid { grid-template-columns: 1fr; }
  .locked-structure { align-items: flex-start; flex-direction: column; }
  .locked-structure p { text-align: left; }
  .count-grid { grid-template-columns: repeat(2, minmax(0, 1fr)); }
  .suggestion-header .btn, .append-actions .btn { width: 100%; }
  .append-submit-controls { align-items: stretch; flex-direction: column; width: 100%; }
  .content-mode-control .control { width: 100%; }
  .search-control { min-width: 100%; }
  .status-filter { width: 100%; }
  .item-header { flex-wrap: wrap; }
  .item-mode-row { align-items: stretch; flex-direction: column; }
  .item-mode-row label { align-items: stretch; flex-direction: column; }
  .item-mode-row .control { width: 100%; }
  .item-title { flex-basis: calc(100% - 80px); }
  .content-mode-badge, .status-badge { margin-left: 58px; }
  .item-collapse-toggle { margin-left: 58px; }
  .item-step-track { grid-template-columns: 1fr; }
  .next-step-action { align-items: stretch; flex-direction: column; }
  .next-step-button { width: 100%; }
  .item-actions > div { justify-content: flex-start; }
}
</style>
