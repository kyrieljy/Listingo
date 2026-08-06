<script setup lang="ts">
import { computed } from 'vue'
import { CheckCircleFilled, EditOutlined, EyeOutlined, LoadingOutlined, PlayCircleOutlined, ReloadOutlined } from '@ant-design/icons-vue'
import type { JobItem } from '../../api/client'

const props = defineProps<{ items: JobItem[]; selected: string[] }>()
const emit = defineEmits<{ toggle: [id: string]; edit: [item: JobItem]; preview: [item: JobItem]; retry: [item: JobItem]; script: [item: JobItem] }>()
const selectedSet = computed(() => new Set(props.selected))
const currentUrl = (item: JobItem) => item.versions.find((version) => version.id === item.current_version_id)?.url ?? item.versions.at(-1)?.url
const placeholderLabel = (item: JobItem) => {
  if (item.status === 'failed') return '生成失败'
  if (item.status === 'cancelled') return '已取消'
  if (item.status === 'cancelling') return '取消中'
  if (item.status === 'succeeded') return '结果同步中'
  return '生成中'
}
const placeholderSpinning = (item: JobItem) => ['queued', 'running', 'succeeded'].includes(item.status)
</script>

<template>
  <div class="result-grid">
    <article v-for="item in items" :key="item.id" class="result-card" :class="{ selected: selectedSet.has(item.id) }">
      <button class="select-dot" type="button" :disabled="item.status !== 'succeeded'" :aria-label="`选择第 ${item.index + 1} 张`" @click="emit('toggle', item.id)">
        <CheckCircleFilled v-if="selectedSet.has(item.id)" />
      </button>
      <div v-if="currentUrl(item)" class="result-image-frame">
        <img :src="currentUrl(item)" :alt="`第 ${item.index + 1} 张生成结果`" />
      </div>
      <div v-else class="pending-image" :class="{ terminal: !placeholderSpinning(item) }">
        <LoadingOutlined v-if="placeholderSpinning(item)" spin />
        <span>{{ placeholderLabel(item) }}</span>
      </div>
      <div class="result-meta">
        <div><span>第 {{ item.index + 1 }} 张 · {{ item.status }}</span></div>
        <div class="card-actions">
          <button title="预览" @click="emit('preview', item)"><EyeOutlined /></button>
          <button title="二次编辑" :disabled="item.status !== 'succeeded'" @click="emit('edit', item)"><EditOutlined /></button>
          <button title="脚本" :disabled="!item.prompt_text && !item.error" @click="emit('script', item)"><PlayCircleOutlined /></button>
          <button v-if="item.status === 'failed'" title="重试" @click="emit('retry', item)"><ReloadOutlined /></button>
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
}

.select-dot:disabled,
.card-actions button:disabled {
  opacity: .45;
  cursor: not-allowed;
}
</style>
