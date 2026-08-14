<script setup lang="ts">
import { computed } from 'vue'
import { QuestionCircleOutlined } from '@ant-design/icons-vue'
import type { MetricDefinition } from './monitoring-data'

const props = defineProps<{
  definition?: MetricDefinition | null
  label?: string
}>()

const fallback = computed<MetricDefinition>(() => ({
  key: props.label || 'unknown',
  label: props.label || '口径',
  formula: '该指标暂未配置口径',
  source: '待补充',
  numerator: '待补充',
  denominator: '待补充',
  unit: '待补充',
  notes: '请在 metric_definitions 中补充该指标定义。',
}))

const item = computed(() => props.definition || fallback.value)
</script>

<template>
  <a-popover trigger="click" placement="bottomLeft" overlay-class-name="metric-help-popover">
    <button class="metric-help-trigger" type="button" :aria-label="`${item.label}口径`" @click.stop>
      <QuestionCircleOutlined />
    </button>
    <template #content>
      <section class="metric-help-content">
        <header>
          <b>{{ item.label }}</b>
          <span>{{ item.unit }}</span>
        </header>
        <dl>
          <div><dt>公式</dt><dd>{{ item.formula }}</dd></div>
          <div><dt>数据源</dt><dd>{{ item.source }}</dd></div>
          <div><dt>分子</dt><dd>{{ item.numerator }}</dd></div>
          <div><dt>分母</dt><dd>{{ item.denominator }}</dd></div>
          <div><dt>说明</dt><dd>{{ item.notes }}</dd></div>
        </dl>
      </section>
    </template>
  </a-popover>
</template>
