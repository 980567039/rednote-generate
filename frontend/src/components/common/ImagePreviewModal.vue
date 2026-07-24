<template>
  <Teleport to="body">
    <div
      v-if="visible"
      class="image-preview-backdrop"
      role="dialog"
      aria-modal="true"
      :aria-label="alt || '图片大图预览'"
      @click="emit('close')"
    >
      <div class="image-preview-dialog" @click.stop>
        <button class="image-preview-close" type="button" aria-label="关闭大图预览" @click="emit('close')">
          ×
        </button>
        <img :src="originalSrc" :alt="alt" decoding="async" />
      </div>
    </div>
  </Teleport>
</template>

<script setup lang="ts">
import { computed, onMounted, onUnmounted } from 'vue'

const props = withDefaults(defineProps<{
  visible: boolean
  src: string
  alt?: string
}>(), {
  alt: '图片大图预览'
})

const emit = defineEmits<{
  (e: 'close'): void
}>()

const originalSrc = computed(() => {
  if (!props.src) return ''

  const [base, query = ''] = props.src.split('?')
  const params = new URLSearchParams(query)
  params.set('thumbnail', 'false')
  return `${base}?${params.toString()}`
})

function handleKeydown(event: KeyboardEvent) {
  if (props.visible && event.key === 'Escape') {
    emit('close')
  }
}

onMounted(() => window.addEventListener('keydown', handleKeydown))
onUnmounted(() => window.removeEventListener('keydown', handleKeydown))
</script>

<style scoped>
.image-preview-backdrop {
  position: fixed;
  inset: 0;
  z-index: 1200;
  display: flex;
  align-items: center;
  justify-content: center;
  padding: 24px;
  background: rgba(0, 0, 0, 0.88);
  backdrop-filter: blur(4px);
}

.image-preview-dialog {
  position: relative;
  display: flex;
  max-width: 94vw;
  max-height: 94vh;
  align-items: center;
  justify-content: center;
}

.image-preview-dialog img {
  display: block;
  max-width: 94vw;
  max-height: 94vh;
  object-fit: contain;
  border-radius: 10px;
  box-shadow: 0 24px 80px rgba(0, 0, 0, 0.45);
}

.image-preview-close {
  position: absolute;
  top: 12px;
  right: 12px;
  z-index: 1;
  width: 36px;
  height: 36px;
  padding: 0;
  border: 1px solid rgba(255, 255, 255, 0.35);
  border-radius: 50%;
  background: rgba(0, 0, 0, 0.55);
  color: white;
  cursor: pointer;
  font-size: 25px;
  line-height: 32px;
  transition: background-color 0.2s, transform 0.2s;
}

.image-preview-close:hover {
  background: var(--primary, #ff2442);
  transform: scale(1.05);
}
</style>
