<script setup lang="ts">
import { computed, ref } from 'vue'
import { CheckOutlined, DownOutlined } from '@ant-design/icons-vue'
import { modelPreferenceOptions, normalizeModelPreference, type ModelPreference } from './workspace-model'

const model = defineModel<ModelPreference>()
const open = ref(false)
const selected = computed(() => modelPreferenceOptions.find(option => option.key === normalizeModelPreference(model.value)) ?? modelPreferenceOptions[0])

function select(preference: ModelPreference) {
  model.value = preference
  open.value = false
}
</script>

<template>
          <div class="model-preference-row">
            <span><b>生成偏好</b><small>{{ selected.description }}</small></span>
            <div class="model-preference-select">
              <button class="model-preference-trigger" type="button" :aria-expanded="open" aria-haspopup="listbox" @click="open = !open">{{ selected.label }}<DownOutlined/></button>
              <div v-if="open" class="model-preference-menu" role="listbox" aria-label="生成偏好">
                <button v-for="option in modelPreferenceOptions" :key="option.key" type="button" role="option" :aria-selected="option.key === selected.key" @click="select(option.key)">
                  <span><b>{{ option.label }}</b><small>{{ option.description }}</small></span>
                  <CheckOutlined v-if="option.key === selected.key"/>
                </button>
              </div>
            </div>
          </div>
</template>
