<template>
  <div class="container series-list-page">
    <header class="page-header series-list-header">
      <div>
        <h1 class="page-title">我的系列合集</h1>
        <p class="page-subtitle">继续编辑大纲、查看进度，或进入已完成的子作品。</p>
      </div>
      <button class="btn btn-primary" type="button" @click="router.push('/?mode=series')">新建合集</button>
    </header>

    <ErrorCard v-if="error" :error="error" dismissible @dismiss="error = null" />
    <div v-if="loading" class="loading-card card">正在加载合集…</div>
    <div v-else-if="!projects.length" class="empty-card card">
      <h2>还没有系列合集</h2>
      <p>创建一个固定像素风模板，就可以每天添加新的子主题。</p>
      <button class="btn btn-primary" type="button" @click="router.push('/?mode=series')">创建第一个合集</button>
    </div>
    <div v-else class="series-project-grid">
      <article v-for="project in projects" :key="project.id" class="series-project-card card">
        <div class="project-card-heading">
          <div>
            <h2>{{ project.name || project.template?.name || '未命名系列合集' }}</h2>
            <p>{{ project.item_count ?? countTotal(project) }} 个子主题 · 可持续追加</p>
          </div>
          <span class="updated-date">{{ formatDate(project.updated_at || project.created_at) }}</span>
        </div>
        <div class="status-counts" aria-label="子主题状态计数">
          <div><strong>{{ countFor(project, ['draft']) }}</strong><span>待大纲</span></div>
          <div><strong>{{ countFor(project, ['outline_ready']) }}</strong><span>待确认</span></div>
          <div><strong>{{ countFor(project, ['confirmed']) }}</strong><span>待生成</span></div>
          <div class="active"><strong>{{ countFor(project, ['queued', 'outlining', 'generating', 'running']) }}</strong><span>生成中</span></div>
          <div class="success"><strong>{{ countFor(project, ['completed', 'done']) }}</strong><span>已完成</span></div>
          <div class="error"><strong>{{ countFor(project, ['failed', 'error']) }}</strong><span>失败</span></div>
        </div>
        <button class="btn btn-secondary project-open-button" type="button" @click="router.push(`/series/${project.id}`)">
          进入合集工作台
        </button>
      </article>
    </div>
  </div>
</template>

<script setup lang="ts">
import { onMounted, ref } from 'vue'
import { useRouter } from 'vue-router'
import { getSeriesProjects, type SeriesProject } from '../api'
import ErrorCard from '../components/common/ErrorCard.vue'
import { normalizeApiError, type AppError } from '../utils/errors'

const router = useRouter()
const projects = ref<SeriesProject[]>([])
const loading = ref(true)
const error = ref<AppError | null>(null)

function projectCounts(project: SeriesProject) {
  if (project.status_counts && Object.keys(project.status_counts).length) return project.status_counts
  return (project.items || []).reduce<Record<string, number>>((result, item) => {
    result[item.status] = (result[item.status] || 0) + 1
    return result
  }, {})
}
function countFor(project: SeriesProject, statuses: string[]) {
  const counts = projectCounts(project)
  return statuses.reduce((sum, status) => sum + (counts[status] || 0), 0)
}
function countTotal(project: SeriesProject) { return Object.values(projectCounts(project)).reduce((sum, count) => sum + count, 0) }
function formatDate(value?: string) {
  if (!value) return ''
  const date = new Date(value)
  return Number.isNaN(date.getTime()) ? '' : date.toLocaleDateString('zh-CN')
}

onMounted(async () => {
  const result = await getSeriesProjects()
  if (result.success) projects.value = result.projects || []
  else error.value = normalizeApiError(result.error || result.error_message || '加载系列合集失败', '加载系列合集失败')
  loading.value = false
})
</script>

<style scoped>
.series-list-page { max-width: 1040px; }
.series-list-header { align-items: flex-end; }
.series-project-grid { display: grid; grid-template-columns: repeat(2, minmax(0, 1fr)); gap: 16px; }
.series-project-card { padding: 20px; }
.project-card-heading { display: flex; align-items: flex-start; justify-content: space-between; gap: 12px; }
.project-card-heading h2 { margin: 0 0 5px; color: var(--text-main); font-size: 18px; }
.project-card-heading p, .updated-date { margin: 0; color: var(--text-sub); font-size: 12px; }
.status-counts { display: grid; grid-template-columns: repeat(6, minmax(0, 1fr)); gap: 6px; margin: 18px 0; }
.status-counts div { display: grid; justify-items: center; gap: 1px; padding: 7px 3px; border-radius: 8px; background: var(--bg-muted); }
.status-counts strong { color: var(--text-main); font-size: 15px; }
.status-counts span { color: var(--text-secondary); font-size: 9px; }
.status-counts .active strong, .status-counts .success strong { color: var(--primary); }
.status-counts .error strong { color: var(--primary-active); }
.project-open-button { width: 100%; }
.empty-card { padding: 54px 20px; text-align: center; }
.empty-card h2 { margin: 0 0 8px; color: var(--text-main); }
.empty-card p { margin: 0 0 20px; color: var(--text-sub); }
@media (max-width: 760px) { .series-project-grid { grid-template-columns: 1fr; } .series-list-header { align-items: stretch; flex-direction: column; } }
</style>
