<template>
  <!-- 主题输入组合框 -->
  <div class="composer-container">
    <!-- 输入区域 -->
    <div class="composer-input-wrapper">
      <div class="search-icon-static" aria-hidden="true">
        <svg width="24" height="24" viewBox="0 0 24 24" fill="none" xmlns="http://www.w3.org/2000/svg">
          <path d="M21 21L16.65 16.65M19 11C19 15.4183 15.4183 19 11 19C6.58172 19 3 15.4183 3 11C3 6.58172 6.58172 3 11 3C15.4183 3 19 6.58172 19 11Z" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"/>
        </svg>
      </div>
      <textarea
        ref="textareaRef"
        :value="modelValue"
        @input="handleInput"
        class="composer-textarea"
        aria-label="创作主题"
        placeholder="输入主题，例如：使用 Codex 之前和之后的我"
        :disabled="loading"
        rows="1"
      ></textarea>
    </div>

    <div class="creative-brief-wrapper">
      <label for="creative-brief" class="creative-brief-label">补充创作要求 <span>（可选）</span></label>
      <textarea
        id="creative-brief"
        :value="creativeBrief"
        class="creative-brief-input"
        placeholder="例如：前后反差夸张；画面优先，少文字；整体轻松幽默"
        :disabled="loading"
        rows="2"
        @input="handleBriefInput"
      ></textarea>
    </div>

    <!-- 已上传图片预览 -->
    <div v-if="uploadedImages.length > 0" class="uploaded-images-preview">
      <div
        v-for="(img, idx) in uploadedImages"
        :key="idx"
        class="uploaded-image-item"
      >
        <img :src="img.preview" :alt="`图片 ${idx + 1}`" />
        <button class="remove-image-btn" @click="removeImage(idx)">
          <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
            <line x1="18" y1="6" x2="6" y2="18"></line>
            <line x1="6" y1="6" x2="18" y2="18"></line>
          </svg>
        </button>
      </div>
      <div class="upload-hint">
        这些图片将用于生成封面和内容参考
      </div>
    </div>

    <!-- 工具栏 -->
    <div class="composer-toolbar">
      <div class="toolbar-left">
        <label class="tool-btn" :class="{ 'active': uploadedImages.length > 0 }" title="上传参考图">
          <input
            type="file"
            accept="image/*"
            multiple
            @change="handleImageUpload"
            :disabled="loading"
            style="display: none;"
          />
          <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
            <rect x="3" y="3" width="18" height="18" rx="2" ry="2"></rect>
            <circle cx="8.5" cy="8.5" r="1.5"></circle>
            <polyline points="21 15 16 10 5 21"></polyline>
          </svg>
          <span v-if="uploadedImages.length > 0" class="badge-count">{{ uploadedImages.length }}</span>
        </label>
      </div>
      <div class="toolbar-right">
        <button
          class="btn btn-primary generate-btn"
          @click="$emit('generate')"
          :disabled="!modelValue.trim() || loading"
        >
          <span v-if="loading" class="spinner-sm"></span>
          <span>{{ loading ? '生成中' : '生成大纲' }}</span>
        </button>
      </div>
    </div>

    <div v-if="loading" class="loading-hint" role="status" aria-live="polite">
      请稍后，这一步大概要 15-30 秒左右。
    </div>
  </div>
</template>

<script setup lang="ts">
import { ref, onUnmounted } from 'vue'

/**
 * 主题输入组合框组件
 *
 * 功能：
 * - 主题文本输入（自动调整高度）
 * - 参考图片上传（最多5张）
 * - 生成按钮
 */

// 定义上传的图片类型
interface UploadedImage {
  file: File
  preview: string
}

// 定义 Props
const props = defineProps<{
  modelValue: string
  creativeBrief: string
  loading: boolean
}>()

// 定义 Emits
const emit = defineEmits<{
  (e: 'update:modelValue', value: string): void
  (e: 'update:creativeBrief', value: string): void
  (e: 'generate'): void
  (e: 'imagesChange', images: File[]): void
}>()

// 输入框引用
const textareaRef = ref<HTMLTextAreaElement | null>(null)

// 已上传的图片
const uploadedImages = ref<UploadedImage[]>([])

/**
 * 处理输入变化
 */
function handleInput(event: Event) {
  const target = event.target as HTMLTextAreaElement
  emit('update:modelValue', target.value)
  adjustHeight()
}

/**
 * 更新不作为标题保存的补充创作要求。
 */
function handleBriefInput(event: Event) {
  emit('update:creativeBrief', (event.target as HTMLTextAreaElement).value)
}

/**
 * 自动调整输入框高度
 */
function adjustHeight() {
  const el = textareaRef.value
  if (!el) return

  el.style.height = 'auto'
  const newHeight = Math.max(64, Math.min(el.scrollHeight, 200))
  el.style.height = newHeight + 'px'
}

/**
 * 处理图片上传
 */
function handleImageUpload(event: Event) {
  const target = event.target as HTMLInputElement
  if (!target.files) return

  const files = Array.from(target.files)
  files.forEach((file) => {
    // 限制最多 5 张图片
    if (uploadedImages.value.length >= 5) {
      return
    }
    // 创建预览 URL
    const preview = URL.createObjectURL(file)
    uploadedImages.value.push({ file, preview })
  })

  // 通知父组件
  emitImagesChange()

  // 清空 input，允许重复选择同一文件
  target.value = ''
}

/**
 * 移除图片
 */
function removeImage(index: number) {
  const img = uploadedImages.value[index]
  // 释放预览 URL
  URL.revokeObjectURL(img.preview)
  uploadedImages.value.splice(index, 1)

  // 通知父组件
  emitImagesChange()
}

/**
 * 通知父组件图片变化
 */
function emitImagesChange() {
  const files = uploadedImages.value.map(img => img.file)
  emit('imagesChange', files)
}

/**
 * 清理所有预览 URL
 */
function clearPreviews() {
  uploadedImages.value.forEach(img => URL.revokeObjectURL(img.preview))
  uploadedImages.value = []
}

// 组件卸载时清理
onUnmounted(() => {
  clearPreviews()
})

// 暴露方法给父组件
defineExpose({
  clearPreviews
})
</script>

<style scoped>
/* 组合框容器 */
.composer-container {
  background: var(--bg-card);
  border-radius: 16px;
  padding: 16px;
  box-shadow: var(--shadow-md);
  border: 1px solid var(--border-color);
}

/* 输入区域 */
.composer-input-wrapper {
  display: flex;
  align-items: flex-start;
  gap: 12px;
}

.search-icon-static {
  flex-shrink: 0;
  padding-top: 8px;
  color: var(--text-secondary);
}

.composer-textarea {
  flex: 1;
  border: none;
  outline: none;
  font-size: 16px;
  line-height: 1.6;
  resize: none;
  min-height: 44px;
  max-height: 200px;
  padding: 8px 0;
  font-family: inherit;
  background: transparent;
  color: var(--text-main);
}

.composer-textarea::placeholder {
  color: var(--text-placeholder);
}

.composer-textarea:disabled {
  background: transparent;
  color: var(--text-secondary);
}

.creative-brief-wrapper {
  margin: 4px 0 0 36px;
  padding: 10px 12px;
  border: 1px solid var(--border-color, #eee);
  border-radius: 10px;
  background: var(--bg-subtle);
  text-align: left;
}

.creative-brief-label {
  display: block;
  margin-bottom: 5px;
  color: var(--text-main);
  font-size: 13px;
  font-weight: 600;
}

.creative-brief-label span {
  color: var(--text-sub);
  font-weight: 400;
}

.creative-brief-input {
  display: block;
  box-sizing: border-box;
  width: 100%;
  min-height: 44px;
  padding: 0;
  border: none;
  outline: none;
  resize: vertical;
  background: transparent;
  color: var(--text-main);
  font: inherit;
  font-size: 14px;
  line-height: 1.55;
}

.creative-brief-input::placeholder {
  color: var(--text-placeholder);
}

.creative-brief-input:disabled {
  color: var(--text-secondary);
}

/* 已上传图片预览 */
.uploaded-images-preview {
  display: flex;
  flex-wrap: wrap;
  gap: 12px;
  margin-top: 16px;
  padding: 16px;
  background: var(--bg-muted);
  border-radius: 12px;
  align-items: center;
}

.uploaded-image-item {
  position: relative;
  width: 60px;
  height: 60px;
  border-radius: 8px;
  overflow: hidden;
  box-shadow: 0 2px 8px rgba(0, 0, 0, 0.1);
}

.uploaded-image-item img {
  width: 100%;
  height: 100%;
  object-fit: cover;
}

.remove-image-btn {
  position: absolute;
  top: 2px;
  right: 2px;
  width: 20px;
  height: 20px;
  border-radius: 50%;
  background: rgba(0, 0, 0, 0.6);
  border: none;
  cursor: pointer;
  display: flex;
  align-items: center;
  justify-content: center;
  color: white;
  opacity: 0;
  transition: opacity 0.2s;
}

.uploaded-image-item:hover .remove-image-btn {
  opacity: 1;
}

.remove-image-btn:hover {
  background: var(--primary, #ff2442);
}

.upload-hint {
  flex: 1;
  font-size: 12px;
  color: var(--text-sub);
  text-align: right;
}

/* 工具栏 */
.composer-toolbar {
  display: flex;
  justify-content: space-between;
  align-items: center;
  margin-top: 12px;
  padding-top: 12px;
  border-top: 1px solid var(--border-subtle);
}

.toolbar-left {
  display: flex;
  gap: 8px;
}

.tool-btn {
  display: flex;
  align-items: center;
  justify-content: center;
  position: relative;
  width: 40px;
  height: 40px;
  border-radius: 10px;
  background: var(--bg-muted);
  border: none;
  cursor: pointer;
  color: var(--text-sub);
  transition: all 0.2s;
}

.tool-btn:hover {
  background: var(--surface-hover);
  color: var(--primary);
}

.tool-btn.active {
  background: var(--primary-light);
  color: var(--primary);
}

.badge-count {
  position: absolute;
  top: -4px;
  right: -4px;
  min-width: 18px;
  height: 18px;
  background: var(--primary, #ff2442);
  color: white;
  border-radius: 9px;
  font-size: 11px;
  font-weight: 600;
  display: flex;
  align-items: center;
  justify-content: center;
  padding: 0 4px;
}

/* 生成按钮 */
.generate-btn {
  min-width: 112px;
  padding: 10px 24px;
  font-size: 15px;
  border-radius: 100px;
  display: flex;
  align-items: center;
  gap: 8px;
}

.generate-btn:disabled {
  opacity: 0.5;
  cursor: not-allowed;
}

.loading-hint {
  margin-top: 12px;
  padding: 10px 12px;
  border-radius: 8px;
  background: var(--primary-fade);
  color: var(--text-sub);
  font-size: 14px;
  line-height: 1.5;
  text-align: right;
}

/* 加载动画 */
.spinner-sm {
  width: 16px;
  height: 16px;
  border: 2px solid currentColor;
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
