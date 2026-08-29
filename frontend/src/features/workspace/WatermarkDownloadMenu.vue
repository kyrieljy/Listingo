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
const acknowledgementOpen = ref(false)
const watermarkAcknowledged = ref(false)

function toggleMenu(menu: 'formats' | 'watermark') {
  openMenu.value = openMenu.value === menu ? null : menu
}

function download(format: DownloadFormat) {
  openMenu.value = null
  emit('download', format)
}

function toggleWatermark(event: Event, canExportWithoutWatermark: boolean) {
  const input = event.target as HTMLInputElement
  const value = input.checked
  if (!canExportWithoutWatermark && !value) {
    input.checked = true
    return
  }
  if (canExportWithoutWatermark && !value) {
    input.checked = true
    watermarkAcknowledged.value = false
    acknowledgementOpen.value = true
    openMenu.value = null
    return
  }
  emit('update:includeWatermark', value)
}

function cancelWatermarkAcknowledgement() {
  acknowledgementOpen.value = false
  watermarkAcknowledged.value = false
}

function confirmWatermarkRemoval() {
  if (!watermarkAcknowledged.value) return
  acknowledgementOpen.value = false
  watermarkAcknowledged.value = false
  emit('update:includeWatermark', false)
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
          @change="toggleWatermark($event, canExportWithoutWatermark)"
        />
      </label>
    </div>

    <a-modal
      :open="acknowledgementOpen"
      title="关闭 AI 水印确认"
      ok-text="确定"
      cancel-text="取消"
      :ok-button-props="{ disabled: !watermarkAcknowledged, danger: true }"
      @ok="confirmWatermarkRemoval"
      @cancel="cancelWatermarkAcknowledgement"
      @update:open="(open) => { if (!open) cancelWatermarkAcknowledgement() }"
    >
      <div class="watermark-acknowledgement">
        <p>亲爱的创作者，您即将获取一张无平台印记的AI作品。去掉水印，意味着这张图将完全以“您认为的样子”进入现实世界。</p>
        <p>在此，平台恳请您务必留意：</p>
        <ol>
          <li>AI不是原创者：AI模型基于海量人类作品训练，生成内容可能存在“风格撞车”风险。AI生成图不具有《著作权法》意义上的“独创性”，若您将其作为“原创”商用，存在被第三方起诉抄袭的风险，此风险需由您自行规避。</li>
          <li>防止误导公众：根据法规要求，若您发布的图片涉及新闻时事、公众人物或可能影响社会舆论，请务必在显眼位置标注“由AI生成”。因未标注导致的社会误解或谣言扩散，平台将配合监管部门追溯至您的账号。</li>
        </ol>
        <label class="watermark-acknowledgement-check">
          <input v-model="watermarkAcknowledged" type="checkbox" />
          <span>我已知悉</span>
        </label>
      </div>
    </a-modal>
  </div>
</template>

<style scoped>
.watermark-acknowledgement {
  max-height: min(58vh, 520px);
  overflow-y: auto;
  padding-right: 4px;
  color: #3f4550;
  line-height: 1.7;
}

.watermark-acknowledgement p,
.watermark-acknowledgement li {
  margin: 0 0 10px;
}

.watermark-acknowledgement ol {
  padding-left: 20px;
  margin: 0 0 14px;
}

.watermark-acknowledgement-check {
  display: flex;
  align-items: center;
  gap: 8px;
  margin: 0;
  font-weight: 600;
  color: #252b36;
}

.watermark-acknowledgement-check input {
  width: 16px;
  height: 16px;
  flex: 0 0 auto;
  accent-color: #d32029;
}
</style>
