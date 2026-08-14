<script setup lang="ts">
import type { CSSProperties } from 'vue'
import { CloseOutlined, PlusOutlined } from '@ant-design/icons-vue'
import type { ImageTextEditLine } from '../../api/client'

const props = defineProps<{
  dirty: boolean
  lines: ImageTextEditLine[]
  loading: boolean
  open: boolean
  panelStyle: CSSProperties
  submitting: boolean
}>()

const emit = defineEmits<{
  add: []
  cancel: []
  confirm: []
  reload: []
  remove: [index: number]
  'update:lines': [lines: ImageTextEditLine[]]
}>()

function updateText(index: number, text: string) {
  emit('update:lines', props.lines.map((line, offset) => (offset === index ? { ...line, text } : line)))
}
</script>

<template>
  <aside v-if="open" class="text-edit-side-panel" :style="panelStyle">
    <header>
      <strong>编辑文字</strong>
      <div>
        <button type="button" :disabled="loading" @click="emit('reload')">{{ loading ? '识别中...' : '重新识别' }}</button>
        <button class="text-edit-icon-button" type="button" title="新增一行" @click="emit('add')"><PlusOutlined /></button>
        <button class="text-edit-icon-button" type="button" title="关闭" @click="emit('cancel')"><CloseOutlined /></button>
      </div>
    </header>

    <div class="text-edit-panel-fields">
      <div v-for="(line, index) in lines" :key="line.id || index" class="text-edit-panel-row">
        <input
          :value="line.text"
          :placeholder="line.original_text || '输入需要替换的新文字'"
          @input="updateText(index, ($event.target as HTMLInputElement).value)"
        />
        <button class="text-edit-icon-button" type="button" title="删除" @click="emit('remove', index)"><CloseOutlined /></button>
      </div>
    </div>

    <footer>
      <button type="button" @click="emit('cancel')">取消</button>
      <button
        class="text-edit-confirm"
        :class="{ ready: dirty && !loading && !submitting }"
        type="button"
        :disabled="!dirty || loading || submitting"
        @click="emit('confirm')"
      >
        {{ submitting ? '改字中...' : '确认改字' }}
      </button>
    </footer>
  </aside>
</template>
