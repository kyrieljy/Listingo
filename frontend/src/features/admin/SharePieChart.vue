<script setup lang="ts">
import { computed } from 'vue'
import { use } from 'echarts/core'
import { CanvasRenderer } from 'echarts/renderers'
import { PieChart } from 'echarts/charts'
import { LegendComponent, TooltipComponent } from 'echarts/components'
import VChart from 'vue-echarts'
import type { MetricRow } from './monitoring-data'

use([CanvasRenderer, PieChart, LegendComponent, TooltipComponent])

const props = defineProps<{
  rows: MetricRow[]
  valueKey?: string
  labelKey?: string
}>()

const chartOption = computed(() => {
  const valueKey = props.valueKey || 'share'
  const labelKey = props.labelKey || 'label'
  return {
    color: ['#2563eb', '#16a34a', '#d97706', '#7c3aed', '#0891b2', '#64748b'],
    animationDuration: 260,
    tooltip: {
      trigger: 'item',
      formatter: '{b}: {c}%',
    },
    legend: {
      orient: 'vertical',
      right: 0,
      top: 'middle',
      itemWidth: 10,
      itemHeight: 8,
      textStyle: { color: '#667085', fontSize: 11, fontWeight: 600 },
    },
    series: [
      {
        name: '占比',
        type: 'pie',
        radius: ['48%', '72%'],
        center: ['38%', '50%'],
        avoidLabelOverlap: true,
        label: {
          formatter: '{b}\n{d}%',
          color: '#334155',
          fontSize: 11,
          fontWeight: 700,
        },
        labelLine: {
          length: 10,
          length2: 8,
          lineStyle: { color: '#cbd5e1' },
        },
        data: props.rows.map((row) => ({
          name: String(row[labelKey] || row.label || row.key || '未命名'),
          value: finiteNumber(row[valueKey]),
        })),
      },
    ],
  }
})

function finiteNumber(value: unknown): number {
  const numeric = Number(value)
  return Number.isFinite(numeric) ? numeric : 0
}
</script>

<template>
  <VChart v-if="rows.length" class="monitoring-echart share-pie-chart" :option="chartOption" autoresize />
  <p v-else class="monitoring-empty">暂无可展示数据</p>
</template>
