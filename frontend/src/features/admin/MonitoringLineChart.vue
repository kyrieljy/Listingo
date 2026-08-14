<script setup lang="ts">
import { computed } from 'vue'
import { use } from 'echarts/core'
import { CanvasRenderer } from 'echarts/renderers'
import { BarChart, LineChart } from 'echarts/charts'
import { GridComponent, LegendComponent, TooltipComponent } from 'echarts/components'
import VChart from 'vue-echarts'
import MetricHelpPopover from './MetricHelpPopover.vue'
import type { MetricDefinition, MetricRow } from './monitoring-data'

use([CanvasRenderer, LineChart, BarChart, GridComponent, LegendComponent, TooltipComponent])

const props = defineProps<{
  title: string
  subtitle: string
  rows: MetricRow[]
  metrics: Array<{ key: string; label: string; type?: 'line' | 'bar'; unit?: string; color?: string; yAxisIndex?: number }>
  definitions?: Record<string, MetricDefinition>
  definitionKey?: string
  xKey?: string
  embedded?: boolean
}>()

const chartOption = computed(() => {
  const xKey = props.xKey || 'bucket'
  return {
    color: props.metrics.map((item) => item.color || '#2563eb'),
    animationDuration: 260,
    tooltip: { trigger: 'axis', valueFormatter: (value: unknown) => String(value) },
    legend: {
      top: 4,
      right: 18,
      itemWidth: 10,
      itemHeight: 6,
      textStyle: { color: '#667085', fontSize: 11, fontWeight: 600 },
    },
    grid: { top: 54, left: 44, right: 58, bottom: 32, containLabel: false },
    xAxis: {
      type: 'category',
      boundaryGap: true,
      data: props.rows.map((row) => String(row[xKey] || '')),
      axisLine: { lineStyle: { color: '#d9dee8' } },
      axisTick: { show: false },
      axisLabel: { color: '#7b8494', fontSize: 10 },
    },
    yAxis: [
      {
        type: 'value',
        name: props.metrics.some((item) => item.unit === '%') ? '百分比(%)' : '数量',
        nameTextStyle: { color: '#7b8494', fontSize: 10, align: 'left' },
        axisLabel: { color: '#7b8494', fontSize: 10 },
        splitLine: { lineStyle: { color: '#eef1f5' } },
      },
      {
        type: 'value',
        name: '',
        show: props.metrics.some((item) => item.yAxisIndex === 1),
        nameTextStyle: { color: '#7b8494', fontSize: 10 },
        axisLabel: { color: '#7b8494', fontSize: 10 },
        splitLine: { show: false },
      },
    ],
    series: props.metrics.map((metric) => ({
      name: metric.label,
      type: metric.type || 'line',
      smooth: metric.type !== 'bar',
      yAxisIndex: metric.yAxisIndex || 0,
      symbolSize: 5,
      barMaxWidth: 18,
      lineStyle: { width: 2.2 },
      areaStyle: metric.type === 'bar' ? undefined : { opacity: 0.04 },
      data: props.rows.map((row) => finiteNumber(row[metric.key])),
    })),
  }
})

function finiteNumber(value: unknown): number {
  const numeric = Number(value)
  return Number.isFinite(numeric) ? numeric : 0
}
</script>

<template>
  <component :is="embedded ? 'div' : 'section'" :class="['monitoring-chart-shell', { 'embedded-chart-shell': embedded }]">
    <header>
      <div>
        <span>{{ title }}</span>
        <b>{{ subtitle }}</b>
      </div>
      <MetricHelpPopover v-if="definitionKey" :definition="definitions?.[definitionKey]" :label="title" />
    </header>
    <VChart v-if="rows.length" class="monitoring-echart monitoring-line-chart" :option="chartOption" autoresize />
    <p v-else class="monitoring-empty">暂无可展示数据</p>
  </component>
</template>
