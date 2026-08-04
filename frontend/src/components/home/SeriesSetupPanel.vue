<template>
  <section class="series-setup" aria-labelledby="series-setup-title">
    <div class="series-heading">
      <div>
        <h2 id="series-setup-title">创建系列合集</h2>
        <p>先锁定统一视觉和角色规则；初始主题可留空，进入合集后随时追加。</p>
      </div>
      <div class="series-heading-actions">
        <button class="btn btn-secondary compact-btn" type="button" @click="router.push('/series')">查看我的合集</button>
        <button class="btn btn-secondary compact-btn" type="button" :disabled="busy" @click="toggleTemplateMode">
          {{ creatingTemplate ? '选择已有模板' : '创建新模板' }}
        </button>
      </div>
    </div>

    <ErrorCard v-if="error" :error="error" dismissible class="series-error" @dismiss="error = null" />

    <div v-if="loadingTemplates" class="series-loading">
      <span class="series-spinner"></span>
      正在加载系列模板…
    </div>

    <template v-else>
      <div v-if="!creatingTemplate" class="template-picker">
        <label class="field-label" for="series-template">选择系列模板</label>
        <select id="series-template" v-model="selectedTemplateId" class="field-control" :disabled="busy">
          <option value="" disabled>请选择模板</option>
          <option v-for="template in templates" :key="template.id" :value="template.id">
            {{ template.name }} · {{ template.page_structure.page_count }} 页
          </option>
        </select>
        <div v-if="selectedTemplate" class="template-summary">
          <div>
            <span>视觉风格</span>
            <strong>{{ selectedTemplate.visual_style || '未填写' }}</strong>
          </div>
          <div>
            <span>角色设定</span>
            <strong>{{ selectedTemplate.character_bible || '无固定角色' }}</strong>
          </div>
          <div>
            <span>文案语气</span>
            <strong>{{ selectedTemplate.copy_tone || '未填写' }}</strong>
          </div>
          <div>
            <span>固定结构</span>
            <strong>{{ structureLabel(selectedTemplate.page_structure.preset) }}</strong>
          </div>
        </div>
        <div v-if="templates.length === 0" class="empty-template">
          暂无系列模板，请先创建一个模板。
        </div>
      </div>

      <div v-else class="template-form">
        <div class="field-grid">
          <label class="field-block">
            <span class="field-label">模板名称 *</span>
            <input v-model.trim="form.name" class="field-control" maxlength="60" placeholder="例如：圆滚滚程序员日记" />
          </label>
          <label class="field-block">
            <span class="field-label">模板说明</span>
            <input v-model.trim="form.description" class="field-control" maxlength="200" placeholder="这一系列主要讲什么" />
          </label>
          <label class="field-block">
            <span class="field-label">视觉风格 *</span>
            <input v-model.trim="form.visual_style" class="field-control" maxlength="300" placeholder="例如：温暖手绘、粗线条、轻微纸张纹理" />
          </label>
          <label class="field-block">
            <span class="field-label">色板 *</span>
            <input v-model.trim="form.palette" class="field-control" maxlength="200" placeholder="例如：奶油白、珊瑚红、墨蓝，低饱和" />
          </label>
          <label class="field-block">
            <span class="field-label">构图规则 *</span>
            <input v-model.trim="form.composition" class="field-control" maxlength="300" placeholder="例如：主体居中，上方留标题安全区，3:4 竖图" />
          </label>
          <label class="field-block">
            <span class="field-label">文案语气 *</span>
            <input v-model.trim="form.copy_tone" class="field-control" maxlength="200" placeholder="例如：第一人称、轻松吐槽、短句" />
          </label>
        </div>

        <label class="field-block full-field">
          <span class="field-label">角色设定（Character Bible）</span>
          <textarea v-model.trim="form.character_bible" class="field-control" rows="3" maxlength="1000" placeholder="角色外貌、服饰、性格、固定道具和不可改变的特征"></textarea>
        </label>
        <label class="field-block full-field">
          <span class="field-label">禁止元素</span>
          <textarea v-model.trim="form.prohibited_elements" class="field-control" rows="2" maxlength="500" placeholder="例如：禁止写实照片感、禁止密集文字、禁止改变角色发型"></textarea>
        </label>
        <label class="field-block full-field">
          <span class="field-label">模板版权备注</span>
          <textarea v-model.trim="form.ip_notice" class="field-control" rows="2" maxlength="500" placeholder="记录该模板角色、品牌与参考素材的授权范围和发布注意事项"></textarea>
        </label>

        <div class="structure-field">
          <span class="field-label">固定页面结构 *</span>
          <div class="structure-options">
            <button
              v-for="option in structureOptions"
              :key="option.preset"
              type="button"
              class="structure-card"
              :class="{ active: form.page_structure.preset === option.preset }"
              :disabled="busy"
              @click="selectStructure(option.preset, option.page_count)"
            >
              <strong>{{ option.name }}</strong>
              <small>{{ option.description }}</small>
            </button>
          </div>
        </div>

        <div class="reference-field">
          <div>
            <span class="field-label">风格 / 角色参考图</span>
            <p>最多 4 张，仅用于保持本系列视觉一致；单张不超过 5 MB。</p>
          </div>
          <label class="upload-button" :class="{ disabled: busy || referenceImages.length >= 4 }">
            选择图片
            <input
              type="file"
              accept="image/png,image/jpeg,image/webp"
              multiple
              :disabled="busy || referenceImages.length >= 4"
              @change="handleReferenceImages"
            />
          </label>
        </div>
        <div v-if="referenceImages.length" class="reference-grid">
          <figure v-for="(image, index) in referenceImages" :key="`${index}-${image.name}`">
            <img :src="image.dataUrl" :alt="`参考图 ${index + 1}`" />
            <button type="button" :disabled="busy" aria-label="移除参考图" @click="referenceImages.splice(index, 1)">×</button>
          </figure>
        </div>
      </div>

      <label class="project-name-field" for="series-project-name">
        <span class="field-label">合集名称 *</span>
        <input
          id="series-project-name"
          v-model.trim="projectName"
          class="field-control"
          maxlength="80"
          :disabled="busy"
          placeholder="例如：程序员和 Codex 的 100 天"
          @input="projectNameTouched = true"
        />
        <small>用于区分使用同一模板创建的不同合集，之后在合集列表和工作台展示。</small>
      </label>

      <label class="topics-field" for="series-topics">
        <span class="field-label">初始主题（可选，每行一个，最多 10 个）</span>
        <textarea
          id="series-topics"
          v-model="topicsText"
          class="field-control"
          rows="6"
          :disabled="busy"
          placeholder="第一次使用 Codex 的我&#10;用 Codex 重构旧项目&#10;把 Codex 变成日常搭档"
        ></textarea>
        <span class="topic-count" :class="{ invalid: topics.length > 10 }">{{ topics.length }}/10 个主题</span>
      </label>

      <div class="copyright-notice">
        <strong>第三方 IP 与参考图版权提示</strong>
        <p>请勿未经授权复刻动漫、影视、游戏角色、品牌形象或他人作品。上传参考图不代表获得商业使用权，生成内容仍需你自行审核。</p>
        <label>
          <input v-model="rightsConfirmed" type="checkbox" :disabled="busy" />
          我确认拥有参考图和角色设定的必要权利，或仅使用原创 / 已获授权素材。
        </label>
      </div>

      <div class="series-actions">
        <span>合集可长期维护，后续能追加主题、使用系统候选，并独立生成每篇内容。</span>
        <button class="btn btn-primary" type="button" :disabled="!canCreateProject" @click="createProject">
          {{ busy ? '正在创建…' : '创建系列项目' }}
        </button>
      </div>
    </template>
  </section>
</template>

<script setup lang="ts">
import { computed, onMounted, reactive, ref, watch } from 'vue'
import { useRouter } from 'vue-router'
import {
  createSeriesProject,
  createSeriesTemplate,
  getSeriesTemplates,
  uploadSeriesTemplateReferences,
  type CreateSeriesTemplateInput,
  type SeriesStructurePreset,
  type SeriesTemplate
} from '../../api'
import ErrorCard from '../common/ErrorCard.vue'
import { normalizeApiError, type AppError } from '../../utils/errors'

interface ReferenceImage {
  name: string
  dataUrl: string
  file: File
}

const router = useRouter()
const templates = ref<SeriesTemplate[]>([])
const selectedTemplateId = ref('')
const creatingTemplate = ref(false)
const loadingTemplates = ref(true)
const busy = ref(false)
const topicsText = ref('')
const rightsConfirmed = ref(false)
const projectName = ref('')
const projectNameTouched = ref(false)
const referenceImages = ref<ReferenceImage[]>([])
const error = ref<AppError | null>(null)

const structureOptions: Array<{
  preset: SeriesStructurePreset
  page_count: number
  name: string
  description: string
}> = [
  { preset: 'standard', page_count: 5, name: '标准 5 页', description: '封面 + 3 内容页 + 总结' },
  { preset: 'comparison_two', page_count: 2, name: '前后对比 2 页', description: '之前 / 之后' },
  { preset: 'comparison_four', page_count: 4, name: '完整对比 4 页', description: '封面 + 前后 + 总结' }
]

const form = reactive<CreateSeriesTemplateInput>({
  name: '',
  description: '',
  visual_style: '',
  palette: '',
  composition: '',
  character_bible: '',
  copy_tone: '',
  prohibited_elements: '',
  page_structure: { preset: 'standard', page_count: 5 },
  ip_notice: '仅使用原创或已获授权的角色、品牌与参考素材；发布前需人工复核第三方知识产权风险。',
  reference_images: []
})

const topics = computed(() => topicsText.value
  .split(/\r?\n/)
  .map(topic => topic.trim())
  .filter((topic, index, list) => Boolean(topic) && list.indexOf(topic) === index))

const selectedTemplate = computed(() => templates.value.find(template => template.id === selectedTemplateId.value) || null)
const defaultProjectName = computed(() => creatingTemplate.value ? form.name : selectedTemplate.value?.name || '')
const effectiveProjectName = computed(() => projectName.value.trim() || defaultProjectName.value.trim())

const newTemplateValid = computed(() => Boolean(
  form.name && form.visual_style && form.palette && form.composition && form.copy_tone
))

const canCreateProject = computed(() => Boolean(
  !busy.value
  && rightsConfirmed.value
  && Boolean(effectiveProjectName.value)
  && topics.value.length <= 10
  && (creatingTemplate.value ? newTemplateValid.value : selectedTemplateId.value)
))

function structureLabel(preset: SeriesStructurePreset) {
  return structureOptions.find(option => option.preset === preset)?.name || preset
}

function selectStructure(preset: SeriesStructurePreset, pageCount: number) {
  form.page_structure = { preset, page_count: pageCount }
}

function toggleTemplateMode() {
  creatingTemplate.value = !creatingTemplate.value
  error.value = null
}

async function loadTemplates() {
  loadingTemplates.value = true
  try {
    const result = await getSeriesTemplates()
    if (result.success) {
      templates.value = result.templates || []
      selectedTemplateId.value = templates.value[0]?.id || ''
      if (!templates.value.length) creatingTemplate.value = true
    } else {
      error.value = normalizeApiError(result.error || result.error_message || '加载系列模板失败', '加载系列模板失败')
    }
  } finally {
    loadingTemplates.value = false
  }
}

async function handleReferenceImages(event: Event) {
  const input = event.target as HTMLInputElement
  const files = Array.from(input.files || [])
  input.value = ''
  for (const file of files) {
    if (referenceImages.value.length >= 4) break
    if (!['image/png', 'image/jpeg', 'image/webp'].includes(file.type) || file.size > 5 * 1024 * 1024) {
      error.value = normalizeApiError(`“${file.name}”格式不支持或超过 5 MB`, '参考图无法使用')
      continue
    }
    referenceImages.value.push({ name: file.name, dataUrl: await readFile(file), file })
  }
}

function readFile(file: File) {
  return new Promise<string>((resolve, reject) => {
    const reader = new FileReader()
    reader.onload = () => resolve(String(reader.result || ''))
    reader.onerror = () => reject(reader.error)
    reader.readAsDataURL(file)
  })
}

async function createProject() {
  if (!canCreateProject.value) return
  busy.value = true
  error.value = null
  try {
    let templateId = selectedTemplateId.value
    if (creatingTemplate.value) {
      const templateResult = await createSeriesTemplate({
        ...form,
        page_structure: { ...form.page_structure },
        reference_images: []
      })
      if (!templateResult.success || !templateResult.template) {
        error.value = normalizeApiError(templateResult.error || templateResult.error_message || '创建系列模板失败', '创建系列模板失败')
        return
      }
      templateId = templateResult.template.id
      if (referenceImages.value.length) {
        const referenceResult = await uploadSeriesTemplateReferences(
          templateId,
          referenceImages.value.map(image => image.file)
        )
        if (!referenceResult.success) {
          error.value = normalizeApiError(referenceResult.error || referenceResult.error_message || '上传系列参考图失败', '上传系列参考图失败')
          return
        }
      }
    }

    const projectResult = await createSeriesProject(templateId, topics.value, effectiveProjectName.value)
    if (!projectResult.success || !projectResult.project) {
      error.value = normalizeApiError(projectResult.error || projectResult.error_message || '创建系列项目失败', '创建系列项目失败')
      return
    }
    await router.push(`/series/${projectResult.project.id}`)
  } finally {
    busy.value = false
  }
}

onMounted(loadTemplates)
watch(defaultProjectName, name => {
  if (!projectNameTouched.value) projectName.value = name
}, { immediate: true })
</script>

<style scoped>
.series-setup {
  margin-top: 18px;
  padding: 20px;
  border: 1px solid var(--border-color);
  border-radius: 16px;
  background: var(--bg-subtle);
  color: var(--text-main);
  text-align: left;
}
.series-heading,
.series-actions,
.reference-field { display: flex; align-items: flex-start; justify-content: space-between; gap: 16px; }
.series-heading-actions { display: flex; flex-wrap: wrap; justify-content: flex-end; gap: 8px; }
.series-heading h2 { margin: 0 0 3px; font-size: 18px; }
.series-heading p,
.reference-field p { margin: 0; color: var(--text-sub); font-size: 12px; }
.compact-btn { flex: 0 0 auto; padding: 7px 12px; font-size: 13px; }
.series-error { margin: 14px 0; }
.series-loading { display: flex; align-items: center; justify-content: center; gap: 9px; min-height: 140px; color: var(--text-sub); }
.series-spinner { width: 19px; height: 19px; border: 2px solid var(--border-color); border-top-color: var(--primary); border-radius: 50%; animation: spin 0.8s linear infinite; }
@keyframes spin { to { transform: rotate(360deg); } }
.template-picker,
.template-form { margin-top: 18px; }
.field-label { display: block; margin-bottom: 6px; color: var(--text-main); font-size: 13px; font-weight: 600; }
.field-control { box-sizing: border-box; width: 100%; padding: 9px 11px; border: 1px solid var(--border-color); border-radius: 9px; outline: none; background: var(--bg-control); color: var(--text-main); font: inherit; font-size: 13px; }
.field-control:focus { border-color: var(--primary); box-shadow: 0 0 0 3px var(--primary-fade); }
.field-control::placeholder { color: var(--text-placeholder); }
textarea.field-control { resize: vertical; line-height: 1.55; }
.template-summary { display: grid; grid-template-columns: repeat(2, minmax(0, 1fr)); gap: 8px; margin-top: 10px; }
.template-summary div { display: grid; gap: 2px; padding: 9px 10px; border-radius: 8px; background: var(--bg-muted); }
.template-summary span { color: var(--text-secondary); font-size: 11px; }
.template-summary strong { overflow: hidden; color: var(--text-main); font-size: 12px; font-weight: 500; text-overflow: ellipsis; white-space: nowrap; }
.empty-template { margin-top: 10px; padding: 12px; border: 1px dashed var(--border-color); border-radius: 9px; color: var(--text-sub); font-size: 13px; }
.field-grid { display: grid; grid-template-columns: repeat(2, minmax(0, 1fr)); gap: 12px; }
.field-block { min-width: 0; }
.full-field { display: block; margin-top: 12px; }
.structure-field { margin-top: 14px; }
.structure-options { display: grid; grid-template-columns: repeat(3, minmax(0, 1fr)); gap: 8px; }
.structure-card { display: grid; gap: 2px; padding: 9px 10px; border: 1px solid var(--border-color); border-radius: 9px; background: var(--bg-control); color: var(--text-main); cursor: pointer; font: inherit; text-align: left; }
.structure-card strong { font-size: 12px; }
.structure-card small { color: var(--text-secondary); font-size: 10px; }
.structure-card.active { border-color: var(--primary); background: var(--primary-fade); color: var(--primary); }
.reference-field { align-items: center; margin-top: 14px; }
.upload-button { flex: 0 0 auto; padding: 7px 11px; border: 1px solid var(--border-color); border-radius: 999px; background: var(--bg-control); color: var(--text-main); cursor: pointer; font-size: 12px; font-weight: 600; }
.upload-button.disabled { cursor: default; opacity: 0.55; }
.upload-button input { display: none; }
.reference-grid { display: grid; grid-template-columns: repeat(4, minmax(0, 1fr)); gap: 8px; margin-top: 10px; }
.reference-grid figure { position: relative; overflow: hidden; aspect-ratio: 1; margin: 0; border: 1px solid var(--border-color); border-radius: 9px; background: var(--bg-muted); }
.reference-grid img { width: 100%; height: 100%; object-fit: cover; }
.reference-grid button { position: absolute; top: 5px; right: 5px; width: 24px; height: 24px; padding: 0; border: 1px solid var(--border-color); border-radius: 50%; background: var(--bg-card); color: var(--text-main); cursor: pointer; font-size: 17px; line-height: 20px; }
.topics-field { position: relative; display: block; margin-top: 18px; }
.project-name-field { display: block; margin-top: 18px; }
.project-name-field small { display: block; margin-top: 5px; color: var(--text-sub); font-size: 11px; }
.topic-count { display: block; margin-top: 5px; color: var(--text-secondary); font-size: 11px; text-align: right; }
.topic-count.invalid { color: var(--primary); }
.copyright-notice { margin-top: 14px; padding: 12px; border: 1px solid color-mix(in srgb, var(--primary) 45%, var(--border-color)); border-radius: 10px; background: var(--primary-fade); }
.copyright-notice strong { font-size: 13px; }
.copyright-notice p { margin: 4px 0 8px; color: var(--text-sub); font-size: 11px; line-height: 1.5; }
.copyright-notice label { display: flex; align-items: flex-start; gap: 8px; color: var(--text-main); font-size: 11px; line-height: 1.5; cursor: pointer; }
.copyright-notice input { margin-top: 2px; accent-color: var(--primary); }
.series-actions { align-items: center; margin-top: 16px; }
.series-actions span { color: var(--text-sub); font-size: 11px; }
.series-actions .btn { flex: 0 0 auto; }
@media (max-width: 700px) {
  .series-setup { padding: 15px; }
  .series-heading,
  .series-actions { align-items: stretch; flex-direction: column; }
  .series-heading-actions { justify-content: stretch; }
  .field-grid,
  .template-summary,
  .structure-options { grid-template-columns: 1fr; }
  .reference-grid { grid-template-columns: repeat(2, minmax(0, 1fr)); }
  .series-actions .btn { width: 100%; }
}
</style>
