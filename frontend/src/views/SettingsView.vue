<template>
  <div class="container">
    <div class="page-header">
      <h1 class="page-title">系统设置</h1>
      <p class="page-subtitle">配置文本生成和图片生成的 API 服务</p>
    </div>

    <div v-if="loading" class="loading-container">
      <div class="spinner"></div>
      <p>加载配置中...</p>
    </div>

    <div v-else class="settings-container">
      <ErrorCard
        v-if="feedback?.type === 'error'"
        :error="feedback.error"
        dismissible
        @dismiss="clearFeedback"
        style="margin-bottom: 16px;"
      />

      <div
        v-else-if="feedback?.type === 'success'"
        class="success-card"
        role="status"
        aria-live="polite"
      >
        <span>{{ feedback.message }}</span>
        <button type="button" @click="clearFeedback" aria-label="关闭提示">×</button>
      </div>

      <section class="card theme-card" aria-labelledby="theme-settings-title">
        <div>
          <h2 id="theme-settings-title" class="section-title">外观</h2>
          <p class="section-desc">选择界面主题；跟随系统会在系统外观变化时自动切换。</p>
        </div>
        <div class="theme-options" role="radiogroup" aria-label="界面主题">
          <button
            v-for="option in themeOptions"
            :key="option.value"
            type="button"
            class="theme-option"
            :class="{ active: themePreference === option.value }"
            role="radio"
            :aria-checked="themePreference === option.value"
            @click="setTheme(option.value)"
          >
            <span class="theme-option-icon" aria-hidden="true">{{ option.icon }}</span>
            <span>{{ option.label }}</span>
          </button>
        </div>
        <p class="theme-current">当前使用：{{ resolvedTheme === 'dark' ? '暗色主题' : '浅色主题' }}</p>
      </section>

      <!-- 文本生成配置 -->
      <div class="card">
        <div class="section-header">
          <div>
            <h2 class="section-title">文本生成配置</h2>
            <p class="section-desc">用于生成小红书图文大纲</p>
          </div>
          <button class="btn btn-small" @click="openAddTextModal">
            <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
              <line x1="12" y1="5" x2="12" y2="19"></line>
              <line x1="5" y1="12" x2="19" y2="12"></line>
            </svg>
            添加
          </button>
        </div>

        <!-- 服务商列表表格 -->
        <ProviderTable
          :providers="textConfig.providers"
          :activeProvider="textConfig.active_provider"
          @activate="activateTextProvider"
          @edit="openEditTextModal"
          @delete="deleteTextProvider"
          @test="testTextProviderInList"
        />
      </div>

      <!-- 图片生成配置 -->
      <div class="card">
        <div class="section-header">
          <div>
            <h2 class="section-title">图片生成配置</h2>
            <p class="section-desc">用于生成小红书配图</p>
          </div>
          <button class="btn btn-small" @click="openAddImageModal">
            <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
              <line x1="12" y1="5" x2="12" y2="19"></line>
              <line x1="5" y1="12" x2="19" y2="12"></line>
            </svg>
            添加
          </button>
        </div>

        <!-- 服务商列表表格 -->
        <ProviderTable
          :providers="imageConfig.providers"
          :activeProvider="imageConfig.active_provider"
          @activate="activateImageProvider"
          @edit="openEditImageModal"
          @delete="deleteImageProvider"
          @test="testImageProviderInList"
        />
      </div>
    </div>

    <!-- 文本服务商弹窗 -->
    <ProviderModal
      :visible="showTextModal"
      :isEditing="!!editingTextProvider"
      :formData="textForm"
      :testing="testingText"
      :saving="saving"
      :typeOptions="textTypeOptions"
      providerCategory="text"
      @close="closeTextModal"
      @save="saveTextProvider"
      @test="testTextConnection"
      @update:formData="updateTextForm"
    />

    <!-- 图片服务商弹窗 -->
    <ImageProviderModal
      :visible="showImageModal"
      :isEditing="!!editingImageProvider"
      :formData="imageForm"
      :testing="testingImage"
      :saving="saving"
      :typeOptions="imageTypeOptions"
      @close="closeImageModal"
      @save="saveImageProvider"
      @test="testImageConnection"
      @update:formData="updateImageForm"
    />
  </div>
</template>

<script setup lang="ts">
import { onMounted } from 'vue'
import { useTheme, type ThemePreference } from '../composables/useTheme'
import ProviderTable from '../components/settings/ProviderTable.vue'
import ProviderModal from '../components/settings/ProviderModal.vue'
import ImageProviderModal from '../components/settings/ImageProviderModal.vue'
import ErrorCard from '../components/common/ErrorCard.vue'
import {
  useProviderForm,
  textTypeOptions,
  imageTypeOptions
} from '../composables/useProviderForm'

/**
 * 系统设置页面
 *
 * 功能：
 * - 管理文本生成服务商配置
 * - 管理图片生成服务商配置
 * - 测试 API 连接
 */

// 使用 composable 管理表单状态和逻辑
const {
  // 状态
  loading,
  saving,
  testingText,
  testingImage,
  feedback,

  // 配置数据
  textConfig,
  imageConfig,

  // 文本服务商弹窗
  showTextModal,
  editingTextProvider,
  textForm,

  // 图片服务商弹窗
  showImageModal,
  editingImageProvider,
  imageForm,

  // 方法
  loadConfig,
  clearFeedback,

  // 文本服务商方法
  activateTextProvider,
  openAddTextModal,
  openEditTextModal,
  closeTextModal,
  saveTextProvider,
  deleteTextProvider,
  testTextConnection,
  testTextProviderInList,
  updateTextForm,

  // 图片服务商方法
  activateImageProvider,
  openAddImageModal,
  openEditImageModal,
  closeImageModal,
  saveImageProvider,
  deleteImageProvider,
  testImageConnection,
  testImageProviderInList,
  updateImageForm
} = useProviderForm()

const { preference: themePreference, resolvedTheme, setTheme } = useTheme()
const themeOptions: Array<{ value: ThemePreference; label: string; icon: string }> = [
  { value: 'system', label: '跟随系统', icon: '◐' },
  { value: 'light', label: '浅色', icon: '☀' },
  { value: 'dark', label: '暗色', icon: '☾' }
]

onMounted(() => {
  loadConfig()
})
</script>

<style scoped>
.settings-container {
  max-width: 900px;
  margin: 0 auto;
}

.section-header {
  display: flex;
  justify-content: space-between;
  align-items: flex-start;
  margin-bottom: 20px;
}

.section-title {
  font-size: 18px;
  font-weight: 600;
  margin-bottom: 4px;
  color: var(--text-main);
}

.section-desc {
  font-size: 14px;
  color: var(--text-sub);
  margin: 0;
}

.success-card {
  display: flex;
  justify-content: space-between;
  align-items: center;
  gap: 12px;
  margin-bottom: 16px;
  padding: 12px 14px;
  border: 1px solid #bbf7d0;
  background: #f0fdf4;
  color: #166534;
  border-radius: 8px;
  font-size: 14px;
}

.success-card button {
  border: none;
  background: transparent;
  color: #166534;
  font-size: 18px;
  line-height: 1;
  cursor: pointer;
}

.theme-card {
  display: grid;
  grid-template-columns: minmax(0, 1fr) auto;
  align-items: center;
  gap: 20px;
}

.theme-card .section-title {
  margin-bottom: 4px;
}

.theme-options {
  display: flex;
  gap: 8px;
  padding: 4px;
  border: 1px solid var(--border-color);
  border-radius: 12px;
  background: var(--bg-muted);
}

.theme-option {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  min-height: 36px;
  padding: 7px 11px;
  border: 1px solid transparent;
  border-radius: 8px;
  color: var(--text-sub);
  background: transparent;
  font: inherit;
  font-size: 13px;
  cursor: pointer;
  transition: background 0.2s ease, color 0.2s ease, box-shadow 0.2s ease;
}

.theme-option:hover {
  color: var(--text-main);
}

.theme-option.active {
  background: var(--bg-card);
  color: var(--primary);
  border-color: var(--border-color);
  box-shadow: var(--shadow-sm);
}

.theme-option-icon {
  font-size: 17px;
  line-height: 1;
}

.theme-current {
  grid-column: 1 / -1;
  margin: -8px 0 0;
  color: var(--text-secondary);
  font-size: 13px;
}

/* 按钮样式 */
.btn-small {
  padding: 6px 12px;
  font-size: 13px;
  display: inline-flex;
  align-items: center;
  gap: 6px;
}

/* 加载状态 */
.loading-container {
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  padding: 80px 20px;
  color: var(--text-sub);
}

@media (max-width: 700px) {
  .theme-card { grid-template-columns: 1fr; }
  .theme-options { width: fit-content; }
}
</style>
