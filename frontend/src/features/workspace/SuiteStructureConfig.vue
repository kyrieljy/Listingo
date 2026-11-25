<script setup lang="ts">
import { computed } from 'vue'
import { createDefaultWorkspaceForm, customTypeDefinitions, customTotal, type CustomCountKey, type CustomCounts } from './workspace-model'
import { suiteStructureParams } from './batch-model'

const props = defineProps<{ params: Record<string, unknown>; disabled?: boolean }>()
const emit = defineEmits<{ change: [Record<string, unknown>] }>()
const counts = computed(() => (props.params.custom_counts ?? createDefaultWorkspaceForm().customCounts) as CustomCounts)
const total = computed(() => customTotal(counts.value))
function setMode(mode: string) {
  emit('change', suiteStructureParams(mode, counts.value))
}
function adjust(key: CustomCountKey, delta: number) {
  if (props.disabled || (delta > 0 && (counts.value[key] >= 4 || total.value >= 12)) || (delta < 0 && (counts.value[key] <= 0 || total.value <= 1))) return
  emit('change', suiteStructureParams('custom', { ...counts.value, [key]: counts.value[key] + delta }))
}
</script>

<template>
  <fieldset class="suite-structure-config" :disabled="disabled">
    <legend>套图结构配置</legend>
    <label>生成方式<select :value="params.mode ?? 'smart'" @change="setMode(($event.target as HTMLSelectElement).value)"><option value="smart">智能匹配 · 7张</option><option value="custom">自定义配置</option></select></label>
    <template v-if="params.mode === 'custom'">
      <p>共 {{ total }} 张 · 至少1张，最多12张，每种类型最多4张</p>
      <div class="suite-count-grid">
        <div v-for="item in customTypeDefinitions" :key="item.key" class="suite-count-row">
          <span>{{ item.label }}</span>
          <div>
            <button type="button" :aria-label="`减少${item.label}`" :disabled="disabled || counts[item.key] <= 0 || total <= 1" @click="adjust(item.key, -1)">−</button>
            <strong>{{ counts[item.key] }}</strong>
            <button type="button" :aria-label="`增加${item.label}`" :disabled="disabled || counts[item.key] >= 4 || total >= 12" @click="adjust(item.key, 1)">＋</button>
          </div>
        </div>
      </div>
    </template>
  </fieldset>
</template>

<style scoped>
.suite-structure-config { min-width: 0; margin: 16px 0 0; padding: 14px; border: 1px solid #e5e7eb; border-radius: 12px; }
legend { padding: 0 6px; font-weight: 600; }
label { display: flex; align-items: center; gap: 12px; }
select { min-width: 0; padding: 8px; border: 1px solid #d1d5db; border-radius: 8px; background: white; }
p { margin: 12px 0; color: #64748b; font-size: 12px; }
.suite-count-grid { display: grid; grid-template-columns: repeat(auto-fit, minmax(180px, 1fr)); gap: 12px; }
.suite-count-row, .suite-count-row > div { display: flex; align-items: center; justify-content: space-between; gap: 10px; }
button { width: 28px; height: 28px; border: 1px solid #d1d5db; border-radius: 6px; background: white; cursor: pointer; }
button:disabled { opacity: .4; cursor: default; }
fieldset:disabled { opacity: .65; }
</style>
