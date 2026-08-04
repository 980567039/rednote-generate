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

      <section class="card publish-settings" aria-labelledby="publish-settings-title">
        <div class="section-header">
          <div>
            <h2 id="publish-settings-title" class="section-title">小红书发布</h2>
            <p class="section-desc">通过本机 Chrome 自动填写发布页；建议默认保留人工预览确认。</p>
          </div>
          <span class="availability-badge" :class="{ available: publishConfig.publisher_available }">
            {{ publishLoading ? '检查中' : publishConfig.publisher_available ? '发布助手可用' : '发布助手不可用' }}
          </span>
        </div>

        <ErrorCard
          v-if="publishError"
          :error="publishError"
          dismissible
          class="publish-feedback"
          @dismiss="publishError = null"
        />
        <div v-else-if="publishMessage" class="publish-success" role="status">
          {{ publishMessage }}
        </div>

        <div v-if="publishLoading" class="publish-loading">
          <span class="spinner publish-spinner"></span>
          正在加载发布配置…
        </div>
        <form v-else class="publish-form" @submit.prevent="savePublishSettings">
          <div class="publish-grid">
            <label class="publish-field">
              <span>账号配置名</span>
              <input v-model.trim="publishConfig.account" type="text" placeholder="default" />
              <small>用于区分本机 Chrome 登录配置，不是小红书昵称。</small>
            </label>
            <label class="publish-field">
              <span>Chrome CDP 端口</span>
              <input v-model.number="publishConfig.port" type="number" min="1024" max="65535" />
              <small>需要与发布助手启动 Chrome 时使用的调试端口一致。</small>
            </label>
            <label class="publish-field">
              <span>默认发布模式</span>
              <select v-model="publishConfig.default_mode">
                <option value="preview">预览确认（推荐）</option>
                <option value="auto">自动发布</option>
              </select>
              <small>自动发布会直接点击发布，存在误发和账号风控风险。</small>
            </label>
            <label class="publish-switch">
              <input v-model="publishConfig.headless" type="checkbox" />
              <span>
                <strong>无头浏览器</strong>
                <small>后台运行 Chrome。登录和预览确认时建议关闭。</small>
              </span>
            </label>
          </div>

          <div class="publisher-path">
            <span>发布器目录</span>
            <code>{{ publishConfig.publisher_dir || '未检测到' }}</code>
          </div>

          <div class="publish-settings-actions">
            <div class="auth-result" :class="{ logged: publishLoggedIn === true }">
              {{ publishAuthMessage }}
            </div>
            <button
              class="btn btn-secondary btn-small"
              type="button"
              :disabled="publishCheckingAuth || publishOpeningLogin || !publishConfig.publisher_available"
              @click="checkPublishAuth"
            >
              {{ publishCheckingAuth ? '检查中…' : '检查登录' }}
            </button>
            <button
              class="btn btn-secondary btn-small"
              type="button"
              :disabled="publishCheckingAuth || publishOpeningLogin || !publishConfig.publisher_available"
              @click="startPublishLogin"
            >
              {{ publishOpeningLogin ? '打开中…' : '打开登录页' }}
            </button>
            <button class="btn btn-primary btn-small" type="submit" :disabled="publishSaving">
              {{ publishSaving ? '保存中…' : '保存发布配置' }}
            </button>
          </div>
        </form>
      </section>

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
import { onMounted, ref } from 'vue'
import { useTheme, type ThemePreference } from '../composables/useTheme'
import ProviderTable from '../components/settings/ProviderTable.vue'
import ProviderModal from '../components/settings/ProviderModal.vue'
import ImageProviderModal from '../components/settings/ImageProviderModal.vue'
import ErrorCard from '../components/common/ErrorCard.vue'
import {
  checkPublishLogin,
  getPublishConfig,
  openPublishLogin,
  updatePublishConfig,
  type PublishConfig
} from '../api'
import { normalizeApiError, type AppError } from '../utils/errors'
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

const publishConfig = ref<PublishConfig>({
  account: 'default',
  port: 9222,
  headless: false,
  default_mode: 'preview',
  publisher_available: false,
  publisher_dir: ''
})
const publishLoading = ref(true)
const publishSaving = ref(false)
const publishCheckingAuth = ref(false)
const publishOpeningLogin = ref(false)
const publishLoggedIn = ref<boolean | null>(null)
const publishAuthMessage = ref('尚未检查登录状态')
const publishMessage = ref('')
const publishError = ref<AppError | null>(null)

async function loadPublishSettings() {
  publishLoading.value = true
  try {
    const result = await getPublishConfig()
    if (result.success && result.config) {
      publishConfig.value = result.config
    } else {
      publishError.value = normalizeApiError(result.error || result.error_message || '加载发布配置失败', '加载发布配置失败')
    }
  } finally {
    publishLoading.value = false
  }
}

async function savePublishSettings() {
  publishSaving.value = true
  publishError.value = null
  publishMessage.value = ''
  try {
    const result = await updatePublishConfig({
      account: publishConfig.value.account,
      port: Number(publishConfig.value.port),
      headless: publishConfig.value.headless,
      default_mode: publishConfig.value.default_mode
    })
    if (result.success) {
      publishMessage.value = result.message || '小红书发布配置已保存'
      if (result.config) publishConfig.value = result.config
    } else {
      publishError.value = normalizeApiError(result.error || result.error_message || '保存发布配置失败', '保存发布配置失败')
    }
  } finally {
    publishSaving.value = false
  }
}

async function checkPublishAuth() {
  if (publishCheckingAuth.value || publishOpeningLogin.value) return
  publishCheckingAuth.value = true
  publishError.value = null
  publishAuthMessage.value = '正在检查小红书登录状态…'
  try {
    const result = await checkPublishLogin()
    if (result.success) {
      publishError.value = null
      publishLoggedIn.value = result.logged_in === true || result.authenticated === true
      publishAuthMessage.value = result.message || (publishLoggedIn.value ? '已登录小红书' : '未登录，请打开登录页扫码')
    } else {
      publishLoggedIn.value = false
      publishError.value = normalizeApiError(result.error || result.error_message || '检查登录失败', '检查登录失败')
    }
  } finally {
    publishCheckingAuth.value = false
  }
}

async function startPublishLogin() {
  if (publishCheckingAuth.value || publishOpeningLogin.value) return
  publishOpeningLogin.value = true
  publishError.value = null
  publishAuthMessage.value = '正在唤起 Chrome 登录页，首次启动可能需要十几秒，请勿重复点击。'
  try {
    const result = await openPublishLogin()
    if (result.success) {
      publishError.value = null
      if (result.logged_in !== undefined || result.authenticated !== undefined) {
        publishLoggedIn.value = result.logged_in === true || result.authenticated === true
      }
      publishAuthMessage.value = result.message || '登录页已打开，请在浏览器登录后重新检查'
    } else {
      publishError.value = normalizeApiError(result.error || result.error_message || '打开登录页失败', '打开登录页失败')
    }
  } finally {
    publishOpeningLogin.value = false
  }
}

onMounted(() => {
  void loadConfig()
  void loadPublishSettings()
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
  border: 1px solid color-mix(in srgb, var(--primary) 28%, var(--border-color));
  background: var(--primary-fade);
  color: var(--text-main);
  border-radius: 8px;
  font-size: 14px;
}

.success-card button {
  border: none;
  background: transparent;
  color: var(--text-sub);
  font-size: 18px;
  line-height: 1;
  cursor: pointer;
}

.publish-settings { margin-top: 0; }
.availability-badge {
  padding: 5px 9px;
  border: 1px solid var(--border-color);
  border-radius: 999px;
  color: var(--text-sub);
  background: var(--bg-muted);
  font-size: 12px;
  white-space: nowrap;
}
.availability-badge.available { border-color: var(--primary); color: var(--primary); background: var(--primary-fade); }
.publish-feedback { margin-bottom: 14px; }
.publish-success { margin-bottom: 14px; padding: 10px 12px; border: 1px solid var(--primary); border-radius: 9px; background: var(--primary-fade); color: var(--text-main); font-size: 13px; }
.publish-loading { display: flex; align-items: center; gap: 10px; min-height: 110px; color: var(--text-sub); }
.publish-spinner { border-color: var(--border-color); border-top-color: var(--primary); }
.publish-grid { display: grid; grid-template-columns: repeat(2, minmax(0, 1fr)); gap: 16px; }
.publish-field { display: grid; gap: 6px; color: var(--text-main); font-size: 14px; font-weight: 600; }
.publish-field input,
.publish-field select { width: 100%; box-sizing: border-box; padding: 9px 11px; border: 1px solid var(--border-color); border-radius: 9px; background: var(--bg-control); color: var(--text-main); font: inherit; outline: none; }
.publish-field input:focus,
.publish-field select:focus { border-color: var(--primary); box-shadow: 0 0 0 3px var(--primary-fade); }
.publish-field small,
.publish-switch small { color: var(--text-sub); font-size: 12px; font-weight: 400; line-height: 1.45; }
.publish-switch { display: flex; align-items: flex-start; gap: 9px; padding: 10px 12px; border: 1px solid var(--border-color); border-radius: 9px; background: var(--bg-control); cursor: pointer; }
.publish-switch input { margin-top: 4px; accent-color: var(--primary); }
.publish-switch span { display: grid; gap: 5px; color: var(--text-main); font-size: 14px; }
.publisher-path { display: flex; gap: 12px; align-items: baseline; margin-top: 16px; padding: 10px 12px; border-radius: 9px; background: var(--bg-muted); color: var(--text-sub); font-size: 12px; }
.publisher-path code { color: var(--text-main); overflow-wrap: anywhere; }
.publish-settings-actions { display: flex; align-items: center; justify-content: flex-end; flex-wrap: wrap; gap: 8px; margin-top: 18px; }
.auth-result { margin-right: auto; color: var(--text-sub); font-size: 12px; }
.auth-result.logged { color: var(--primary); }

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
  .publish-grid { grid-template-columns: 1fr; }
  .publish-settings-actions { justify-content: flex-start; }
  .auth-result { width: 100%; }
}
</style>
