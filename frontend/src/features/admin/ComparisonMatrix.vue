<script setup lang="ts">
import { computed, ref, watch } from 'vue'
import MetricHelpPopover from './MetricHelpPopover.vue'
import MonitoringPager from './MonitoringPager.vue'
import type { MetricDefinition, MetricRow } from './monitoring-data'

const props = defineProps<{
  rows: MetricRow[]
  columns: Array<{ key: string; label: string; kind?: 'percent' | 'duration' | 'number'; definitionKey?: string }>
  definitions?: Record<string, MetricDefinition>
  labelKey?: string
  compact?: boolean
  pageSize?: number
}>()

const page = ref(1)
const pagedRows = computed(() => {
  if (!props.pageSize || props.rows.length <= props.pageSize) return props.rows
  const start = (page.value - 1) * props.pageSize
  return props.rows.slice(start, start + props.pageSize)
})

watch(() => [props.rows.length, props.pageSize], () => {
  page.value = 1
})

function valueText(value: unknown, kind = 'number'): string {
  const numeric = finiteNumber(value)
  if (kind === 'percent') return `${numeric.toFixed(1)}%`
  if (kind === 'duration') {
    if (numeric >= 1000) return `${(numeric / 1000).toFixed(1)}s`
    return `${Math.round(numeric)}ms`
  }
  return Intl.NumberFormat('zh-CN').format(numeric)
}

function barWidth(value: unknown, kind = 'number'): string {
  const numeric = finiteNumber(value)
  const max = kind === 'percent' ? 100 : Math.max(1, numeric)
  return `${Math.max(3, Math.min(100, numeric * 100 / max))}%`
}

function finiteNumber(value: unknown): number {
  const numeric = Number(value)
  return Number.isFinite(numeric) ? numeric : 0
}

function rowLabel(row: MetricRow, labelKey = 'label'): string {
  return String(row[labelKey] || row.label || row.key || '未命名')
}
</script>

<template>
  <div class="comparison-matrix" :class="{ compact }">
    <table>
      <thead>
        <tr>
          <th>对象</th>
          <th v-for="column in columns" :key="column.key">
            <span>{{ column.label }}</span>
            <MetricHelpPopover v-if="column.definitionKey" :definition="definitions?.[column.definitionKey]" :label="column.label" />
          </th>
        </tr>
      </thead>
      <tbody>
        <tr v-for="row in pagedRows" :key="String(row.key || row.provider_id || row.business_type || row.label)">
          <td>
            <b>{{ rowLabel(row, labelKey) }}</b>
            <small v-if="row.description">{{ row.description }}</small>
            <small v-else-if="row.model_name">{{ row.model_name }}</small>
            <small v-else-if="row.system_name">{{ row.system_name }}</small>
          </td>
          <td v-for="column in columns" :key="column.key">
            <span>{{ valueText(row[column.key], column.kind) }}</span>
            <i><em :style="{ width: barWidth(row[column.key], column.kind) }" /></i>
          </td>
        </tr>
      </tbody>
    </table>
    <p v-if="!rows.length" class="monitoring-empty">暂无可对比数据</p>
    <MonitoringPager
      v-if="pageSize"
      v-model="page"
      :total="rows.length"
      :page-size="pageSize"
    />
  </div>
</template>
