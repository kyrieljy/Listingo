<script setup lang="ts">
import { computed } from 'vue'
import { CheckOutlined, MinusOutlined, PlusOutlined } from '@ant-design/icons-vue'
import { createDefaultWorkspaceForm, customTypeDefinitions, customTotal, type CustomCountKey, type CustomCounts } from './workspace-model'
import { suiteStructureParams } from './batch-model'

const props = defineProps<{ params: Record<string, unknown>; disabled?: boolean; hideTitle?: boolean }>()
const emit = defineEmits<{ change: [Record<string, unknown>] }>()
const counts = computed(() => (props.params.custom_counts ?? createDefaultWorkspaceForm().customCounts) as CustomCounts)
const total = computed(() => customTotal(counts.value))
const modes = [
  { value: 'smart', label: '智能匹配', description: '根据商品与平台规则，智能规划7张套图' },
  { value: 'custom', label: '自定义配置', description: '自由选择图片类型与数量，生成1–12张' },
] as const
function setMode(mode: string) {
  if (props.disabled) return
  emit('change', suiteStructureParams(mode, counts.value))
}
function adjust(key: CustomCountKey, delta: number) {
  if (props.disabled || (delta > 0 && (counts.value[key] >= 4 || total.value >= 12)) || (delta < 0 && (counts.value[key] <= 0 || total.value <= 1))) return
  emit('change', suiteStructureParams('custom', { ...counts.value, [key]: counts.value[key] + delta }))
}
function toggleType(key: CustomCountKey) {
  if (props.disabled) return
  const current = counts.value[key]
  if (current > 0) {
    if (total.value - current < 1) return
    emit('change', suiteStructureParams('custom', { ...counts.value, [key]: 0 }))
  } else {
    adjust(key, 1)
  }
}
</script>

<template>
  <section class="suite-structure-config">
    <div v-if="!hideTitle" class="batch-output-head"><b>套图结构配置</b></div>
    <div class="batch-output-grid suite-mode-grid">
      <button v-for="mode in modes" :key="mode.value" type="button" :class="{ active: (params.mode ?? 'smart') === mode.value }" :disabled="disabled" :aria-pressed="(params.mode ?? 'smart') === mode.value" @click="setMode(mode.value)">
        <i><CheckOutlined v-if="(params.mode ?? 'smart') === mode.value" /></i>
        <span><b>{{ mode.label }}</b><small>{{ mode.description }}</small></span>
      </button>
    </div>
    <template v-if="params.mode === 'custom'">
      <div class="batch-aplus-module-head">
        <b>图片类型</b><em>已选 {{ total }}/12 张</em>
      </div>
      <div class="batch-aplus-module-grid">
        <article v-for="item in customTypeDefinitions" :key="item.key" class="aplus-module-option batch-module-option" :class="{ active: counts[item.key] > 0, disabled }">
          <button class="aplus-module-main" type="button" :disabled="disabled || (counts[item.key] > 0 && total - counts[item.key] < 1)" :aria-pressed="counts[item.key] > 0" @click="toggleType(item.key)">
            <span><b>{{ item.label }}</b><small>{{ item.description }}</small></span>
          </button>
          <div class="aplus-module-stepper" :aria-label="`${item.label}数量`">
            <button type="button" :aria-label="`减少${item.label}`" :disabled="disabled || counts[item.key] <= 0 || total <= 1" @click="adjust(item.key, -1)"><MinusOutlined /></button>
            <strong>{{ counts[item.key] }}</strong>
            <button type="button" :aria-label="`增加${item.label}`" :disabled="disabled || counts[item.key] >= 4 || total >= 12" @click="adjust(item.key, 1)"><PlusOutlined /></button>
          </div>
        </article>
      </div>
      <small class="suite-structure-hint">至少1张，最多12张，每种类型最多4张</small>
    </template>
  </section>
</template>
