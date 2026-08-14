<script setup lang="ts">
import { computed, watch } from 'vue'

const props = defineProps<{
  total: number
  pageSize: number
  modelValue: number
}>()

const emit = defineEmits<{
  'update:modelValue': [number]
}>()

const pageCount = computed(() => Math.max(1, Math.ceil(props.total / Math.max(1, props.pageSize))))
const currentPage = computed(() => Math.min(Math.max(1, props.modelValue || 1), pageCount.value))
const start = computed(() => props.total ? (currentPage.value - 1) * props.pageSize + 1 : 0)
const end = computed(() => Math.min(props.total, currentPage.value * props.pageSize))

watch(pageCount, () => {
  if (props.modelValue > pageCount.value) emit('update:modelValue', pageCount.value)
})

function setPage(page: number): void {
  emit('update:modelValue', Math.min(Math.max(1, page), pageCount.value))
}
</script>

<template>
  <div v-if="total > pageSize" class="monitoring-pagination">
    <span>{{ start }}-{{ end }} / {{ total }}</span>
    <button type="button" :disabled="currentPage <= 1" @click="setPage(currentPage - 1)">上一页</button>
    <button type="button" :disabled="currentPage >= pageCount" @click="setPage(currentPage + 1)">下一页</button>
  </div>
</template>
