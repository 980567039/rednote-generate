<template>
  <div v-if="visible" class="regenerate-modal-backdrop" @click.self="close">
    <section class="regenerate-modal" role="dialog" aria-modal="true" aria-labelledby="regenerate-modal-title">
      <header class="regenerate-modal-header">
        <div>
          <h2 id="regenerate-modal-title">重新生成第 {{ pageNumber }} 页</h2>
          <p>补充本次想调整的内容；不填写则按原要求重新生成。</p>
        </div>
        <button class="close-button" type="button" aria-label="关闭" :disabled="loading" @click="close">×</button>
      </header>

      <label class="feedback-label" for="regenerate-feedback">修改意见（可选）</label>
      <textarea
        id="regenerate-feedback"
        v-model="feedback"
        class="feedback-input"
        :disabled="loading"
        maxlength="500"
        rows="4"
        placeholder="例如：人物表情更开心；前后反差更夸张；去掉画面里的文字"
      ></textarea>
      <p class="feedback-count">{{ feedback.length }}/500</p>

      <footer class="regenerate-modal-actions">
        <button class="btn btn-secondary" type="button" :disabled="loading" @click="close">取消</button>
        <button class="btn btn-primary" type="button" :disabled="loading" @click="confirm">
          {{ loading ? '重绘中…' : '确认重新生成' }}
        </button>
      </footer>
    </section>
  </div>
</template>

<script setup lang="ts">
import { ref, watch } from 'vue'

const props = defineProps<{
  visible: boolean
  pageNumber: number
  loading?: boolean
}>()

const emit = defineEmits<{
  (e: 'close'): void
  (e: 'confirm', feedback: string): void
}>()

const feedback = ref('')

watch(() => props.visible, (visible) => {
  if (visible) feedback.value = ''
})

function close() {
  if (!props.loading) emit('close')
}

function confirm() {
  if (!props.loading) emit('confirm', feedback.value.trim())
}
</script>

<style scoped>
.regenerate-modal-backdrop {
  position: fixed;
  inset: 0;
  z-index: 1100;
  display: flex;
  align-items: center;
  justify-content: center;
  padding: 20px;
  background: rgba(0, 0, 0, 0.5);
}

.regenerate-modal {
  width: min(100%, 520px);
  padding: 22px;
  border: 1px solid var(--border-color);
  border-radius: 16px;
  background: var(--bg-card);
  box-shadow: var(--shadow-lg);
}

.regenerate-modal-header {
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  gap: 16px;
  margin-bottom: 18px;
}

.regenerate-modal-header h2 {
  margin: 0 0 6px;
  color: var(--text-main);
  font-size: 18px;
}

.regenerate-modal-header p,
.feedback-count {
  margin: 0;
  color: var(--text-sub);
  font-size: 13px;
  line-height: 1.5;
}

.close-button {
  width: 28px;
  height: 28px;
  border: 0;
  border-radius: 6px;
  background: transparent;
  color: var(--text-sub);
  cursor: pointer;
  font-size: 24px;
  line-height: 1;
}

.close-button:hover:not(:disabled) {
  background: var(--bg-muted);
  color: var(--text-main);
}

.feedback-label {
  display: block;
  margin-bottom: 8px;
  color: var(--text-main);
  font-size: 14px;
  font-weight: 600;
}

.feedback-input {
  box-sizing: border-box;
  width: 100%;
  resize: vertical;
  padding: 10px 12px;
  border: 1px solid var(--border-color);
  border-radius: 10px;
  outline: none;
  background: var(--bg-control);
  color: var(--text-main);
  font: inherit;
  line-height: 1.5;
}

.feedback-input:focus {
  border-color: var(--primary);
  box-shadow: 0 0 0 3px var(--primary-fade);
}

.feedback-input::placeholder {
  color: var(--text-placeholder);
}

.feedback-count {
  margin-top: 5px;
  text-align: right;
}

.regenerate-modal-actions {
  display: flex;
  justify-content: flex-end;
  gap: 10px;
  margin-top: 20px;
}
</style>
