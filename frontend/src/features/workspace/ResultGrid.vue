<script setup lang="ts">
import { computed } from 'vue'
import { CheckCircleFilled, EditOutlined, EyeOutlined, LoadingOutlined, ReloadOutlined } from '@ant-design/icons-vue'
import type { JobItem } from '../../api/client'

const props = defineProps<{ items: JobItem[]; selected: string[] }>()
const emit = defineEmits<{ toggle: [id: string]; edit: [item: JobItem]; preview: [item: JobItem]; retry: [item: JobItem] }>()
const selectedSet = computed(() => new Set(props.selected))
const currentUrl = (item: JobItem) => item.versions.find((version) => version.id === item.current_version_id)?.url ?? item.versions.at(-1)?.url
</script>

<template>
  <div class="result-grid">
    <article v-for="item in items" :key="item.id" class="result-card" :class="{ selected: selectedSet.has(item.id) }">
      <button class="select-dot" type="button" :aria-label="`选择第 ${item.index + 1} 张`" @click="emit('toggle', item.id)">
        <CheckCircleFilled v-if="selectedSet.has(item.id)" />
      </button>
      <img v-if="currentUrl(item)" :src="currentUrl(item)" :alt="`第 ${item.index + 1} 张生成结果`" />
      <div v-else class="pending-image"><LoadingOutlined spin /><span>生成中</span></div>
      <div class="result-meta">
        <div><span>第 {{ item.index + 1 }} 张 · {{ item.status }}</span></div>
        <div class="card-actions">
          <button title="预览" @click="emit('preview', item)"><EyeOutlined /></button>
          <button title="二次编辑" @click="emit('edit', item)"><EditOutlined /></button>
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
</style>
