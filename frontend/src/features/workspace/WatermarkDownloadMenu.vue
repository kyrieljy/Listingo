<script setup lang="ts">
import { onBeforeUnmount, onMounted, ref } from 'vue'
import { DownloadOutlined, MoreOutlined } from '@ant-design/icons-vue'
import type { DownloadFormat } from '../../api/client'

type DownloadOption = {
  format: DownloadFormat
  label: string
}

withDefaults(defineProps<{
  selectedCount: number
  includeWatermark: boolean
  canExportWithoutWatermark: boolean
  buttonLabel?: string
  options?: DownloadOption[]
}>(), {
  buttonLabel: '下载选中',
  options: () => [{ format: 'zip', label: '下载 ZIP' }],
})

const emit = defineEmits<{
  'update:includeWatermark': [value: boolean]
  download: [format: DownloadFormat]
  upgrade: []
}>()

const menuRoot = ref<HTMLElement | null>(null)
const openMenu = ref<'formats' | 'watermark' | null>(null)

function toggleMenu(menu: 'formats' | 'watermark') {
  openMenu.value = openMenu.value === menu ? null : menu
}

function download(format: DownloadFormat) {
  openMenu.value = null
  emit('download', format)
}

function toggleWatermark(value: boolean, canExportWithoutWatermark: boolean) {
  if (!canExportWithoutWatermark && !value) return
  emit('update:includeWatermark', value)
}

function closeOnOutside(event: PointerEvent) {
  if (!menuRoot.value?.contains(event.target as Node)) openMenu.value = null
}

onMounted(() => document.addEventListener('pointerdown', closeOnOutside))
onBeforeUnmount(() => document.removeEventListener('pointerdown', closeOnOutside))
</script>

<template>
  <div ref="menuRoot" class="download-menu watermark-download-menu">
    <button class="download-button" type="button" :aria-expanded="openMenu === 'formats'" @click="toggleMenu('formats')">
      <DownloadOutlined />{{ buttonLabel }} ({{ selectedCount }})
    </button>
    <button class="download-toggle" type="button" aria-label="下载偏好" :aria-expanded="openMenu === 'watermark'" @click="toggleMenu('watermark')">
      <MoreOutlined />
    </button>

    <div v-if="openMenu === 'formats'" class="download-menu-panel download-format-panel">
      <button v-for="option in options" :key="option.format" type="button" @click="download(option.format)">
        {{ option.label }}
      </button>
    </div>

    <div v-if="openMenu === 'watermark'" class="download-menu-panel watermark-download-panel">
      <label class="watermark-switch-row" :class="{ locked: !canExportWithoutWatermark }">
        <span>
          <b>包含 AI 水印</b>
          <small v-if="canExportWithoutWatermark">导出时保留 AI 生成标识</small>
          <a v-else class="watermark-upgrade-link" href="#" @click.prevent="emit('upgrade')">开通会员取消水印</a>
        </span>
        <input
          type="checkbox"
          :checked="includeWatermark"
          :disabled="!canExportWithoutWatermark"
          @change="toggleWatermark(($event.target as HTMLInputElement).checked, canExportWithoutWatermark)"
        />
      </label>
    </div>
  </div>
</template>
