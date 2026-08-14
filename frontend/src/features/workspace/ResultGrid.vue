<script setup lang="ts">
import { computed, ref } from 'vue'
import { CheckOutlined, EditOutlined, EyeOutlined, FileTextOutlined, LoadingOutlined, PlayCircleOutlined, ReloadOutlined } from '@ant-design/icons-vue'
import type { JobItem } from '../../api/client'
import { previewAspectStyle } from './workspace-model'

const props = defineProps<{ items: JobItem[]; selected: string[]; showWatermark?: boolean; aspectRatio?: string }>()
const emit = defineEmits<{ toggle: [id: string]; edit: [item: JobItem]; textEdit: [item: JobItem]; preview: [item: JobItem]; retry: [item: JobItem]; script: [item: JobItem] }>()
const selectedSet = computed(() => new Set(props.selected))
const naturalAspectRatios = ref<Record<string, string>>({})
const currentUrl = (item: JobItem) => item.versions.find((version) => version.id === item.current_version_id)?.url ?? item.versions.at(-1)?.url
const canUseResult = (item: JobItem) => item.status === 'succeeded' && Boolean(currentUrl(item))
const itemPreviewAspectRatio = (item: JobItem) => {
  const url = currentUrl(item)
  return (url && naturalAspectRatios.value[url]) || props.aspectRatio
}
const selectedSizeLabel = computed(() => String(props.aspectRatio || '').trim())
function updateNaturalAspect(url: string | undefined, event: Event) {
  const image = event.currentTarget as HTMLImageElement
  if (!url || !image.naturalWidth || !image.naturalHeight) return
  naturalAspectRatios.value = { ...naturalAspectRatios.value, [url]: `${image.naturalWidth}:${image.naturalHeight}` }
}
const placeholderLabel = (item: JobItem) => {
  if (item.status === 'failed') return '生成失败'
  if (item.status === 'cancelled') return '已取消'
  if (item.status === 'cancelling') return '取消中'
  if (item.status === 'succeeded') return '结果同步中'
  return '生成中'
}
const placeholderSpinning = (item: JobItem) => ['queued', 'running', 'succeeded'].includes(item.status)
function previewItem(item: JobItem) {
  if (!canUseResult(item)) return
  emit('preview', item)
}
</script>

<template>
  <div class="result-grid">
    <article v-for="item in items" :key="item.id" class="result-card" :class="{ selected: selectedSet.has(item.id) }">
      <button class="select-dot" type="button" :disabled="!canUseResult(item)" :aria-label="`选择第 ${item.index + 1} 张`" @click.stop="emit('toggle', item.id)">
        <CheckOutlined v-if="selectedSet.has(item.id)" />
      </button>
      <div v-if="currentUrl(item)" class="result-image-frame" :data-text-edit-anchor="item.id">
        <span class="image-watermark-box" :style="previewAspectStyle(itemPreviewAspectRatio(item))">
          <img :src="currentUrl(item)" :alt="`第 ${item.index + 1} 张生成结果`" @load="updateNaturalAspect(currentUrl(item), $event)" />
          <img v-if="props.showWatermark !== false" class="ai-watermark-overlay" src="/watermarks/ai-generated-badge-v2.svg" alt="" aria-hidden="true" />
        </span>
      </div>
      <div v-else class="pending-image" :class="{ terminal: !placeholderSpinning(item) }">
        <LoadingOutlined v-if="placeholderSpinning(item)" spin />
        <span>{{ placeholderLabel(item) }}</span>
      </div>
      <div class="result-meta">
        <div>
          <span>第 {{ item.index + 1 }} 张 · {{ item.status }}</span>
          <span v-if="selectedSizeLabel" class="image-size-meta">{{ selectedSizeLabel }}</span>
        </div>
        <div class="card-actions">
          <button title="预览" aria-label="预览" :disabled="!canUseResult(item)" @click="previewItem(item)"><EyeOutlined /></button>
          <button title="二次编辑" aria-label="二次编辑" :disabled="!canUseResult(item)" @click="emit('edit', item)"><EditOutlined /></button>
          <button title="编辑文字" aria-label="编辑文字" :disabled="!canUseResult(item)" @click="emit('textEdit', item)"><FileTextOutlined /></button>
          <button title="脚本" aria-label="脚本" :disabled="!item.prompt_text && !item.error" @click="emit('script', item)"><PlayCircleOutlined /></button>
          <button v-if="item.status === 'failed'" title="重试" aria-label="重试" @click="emit('retry', item)"><ReloadOutlined /></button>
        </div>
      </div>
    </article>
  </div>
</template>

<style scoped>
.select-dot {
  display: grid;
  place-items: center;
  padding: 0;
  line-height: 0;
  transition: background .18s ease, border-color .18s ease, box-shadow .18s ease, transform .18s ease;
}

.select-dot .anticon {
  display: block;
  font-size: 14px;
}

.select-dot:disabled,
.card-actions button:disabled {
  opacity: .45;
  cursor: not-allowed;
}
</style>
