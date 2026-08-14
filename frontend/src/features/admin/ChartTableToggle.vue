<script setup lang="ts">
defineProps<{
  modelValue: 'chart' | 'table' | 'pie'
  chartLabel?: string
  tableLabel?: string
  pieLabel?: string
  hideChart?: boolean
}>()

const emit = defineEmits<{
  'update:modelValue': ['chart' | 'table' | 'pie']
}>()
</script>

<template>
  <div class="chart-table-toggle" role="tablist" aria-label="图表和表格切换">
    <button v-if="!hideChart" type="button" :class="{ active: modelValue === 'chart' }" @click="emit('update:modelValue', 'chart')">{{ chartLabel || '图表' }}</button>
    <button v-if="pieLabel" type="button" :class="{ active: modelValue === 'pie' }" @click="emit('update:modelValue', 'pie')">{{ pieLabel }}</button>
    <button type="button" :class="{ active: modelValue === 'table' }" @click="emit('update:modelValue', 'table')">{{ tableLabel || '表格' }}</button>
  </div>
</template>
