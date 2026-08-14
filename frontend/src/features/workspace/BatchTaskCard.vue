<script setup lang="ts">
import { computed, nextTick, ref } from 'vue'
import {
  CheckOutlined,
  CloseOutlined,
  CloudUploadOutlined,
  CopyOutlined,
  DeleteOutlined,
  DownOutlined,
  EditOutlined,
  MinusOutlined,
  PlusOutlined,
  ThunderboltOutlined,
  UpOutlined,
} from '@ant-design/icons-vue'
import type { BatchBusinessType, WorkspaceConfig } from '../../api/client'
import {
  APLUS_MODULE_TOTAL_LIMIT,
  aplusModuleTotal,
  aplusModules,
  aplusLanguageOptions,
  aplusMarketOptions,
  aplusOutputSpecs,
  aplusPlatformOptions,
  buildAplusOutputTargets,
  isAplusAmazon,
  languageOptions,
  marketOptions,
  orderedAplusModuleSelections,
  platformOptions,
  ratioOptions,
  renderMarkdown,
  type AplusAdvancedTarget,
  type AplusForm,
  type AplusModuleSelection,
  type AplusOutputSpec,
} from './workspace-model'
import { extractBatchProductName, type BatchTaskDraft } from './batch-model'

const props = defineProps<{
  task: BatchTaskDraft
  index: number
  businessType: BatchBusinessType
  config: WorkspaceConfig
  globalParams: Record<string, unknown>
  canDelete: boolean
  validationMessages: string[]
  highlighted: boolean
}>()

const emit = defineEmits<{
  update: [BatchTaskDraft]
  delete: []
  copy: []
  upload: [File[]]
  'ai-write': []
}>()

const fileInput = ref<HTMLInputElement | null>(null)
const copyInput = ref<HTMLTextAreaElement | null>(null)
const platformChoices = computed(() => props.businessType === 'aplus' ? aplusPlatformOptions : platformOptions)
const marketChoices = computed(() => props.businessType === 'aplus' ? aplusMarketOptions : marketOptions)
const languageChoices = computed(() => props.businessType === 'aplus' ? aplusLanguageOptions : languageOptions)
const effectivePlatform = computed(() => String(props.task.overrides.platform ?? props.globalParams.platform ?? ''))
const itemOutputSpecChoices = computed(() => aplusOutputSpecs.filter((item) => !item.amazonOnly || isAplusAmazon(effectivePlatform.value)))
const outputSpecOverrideValue = computed(() => String(props.task.overrides.output_spec ?? ''))
const taskFollowsGlobalModules = computed(() => !Array.isArray(props.task.overrides.module_selections))
const taskModuleSelections = computed(() => {
  const source = taskFollowsGlobalModules.value ? props.globalParams.module_selections : props.task.overrides.module_selections
  return normalizeModuleSelections(source)
})
const taskModuleTotal = computed(() => aplusModuleTotal(taskModuleSelections.value))
const imageLimitReached = computed(() => props.task.assets.length >= props.config.max_batch_item_assets || props.task.uploading)
const requirementLabel = computed(() => props.businessType === 'aplus' ? '商品信息与要求' : '商品卖点与要求')
const aiLabel = computed(() => props.businessType === 'aplus' ? 'AI 转写' : 'AI 帮写')
const regenerateLabel = computed(() => props.businessType === 'aplus' ? '重新转写' : '重新帮写')
const fallbackTitle = computed(() => props.businessType === 'aplus' ? `A+任务${props.index}` : `商品任务${props.index}`)
const summaryTitle = computed(() => {
  if (props.task.name.trim()) return props.task.name.trim()
  return extractBatchProductName(props.task.sellingPoints) || fallbackTitle.value
})
const taskTitle = computed(() => props.task.name.trim() || fallbackTitle.value)
const firstAsset = computed(() => props.task.assets[0])
const placeholder = `建议包含以下信息，帮助生成更精准：
1. 商品名称
2. 核心卖点
3. 适用人群
4. 期望场景
5. 具体参数`

function patch(next: Partial<BatchTaskDraft>) {
  const nextTask: BatchTaskDraft = { ...props.task, ...next }
  const editingMainCopy = next.copyEditing === true || Object.prototype.hasOwnProperty.call(next, 'sellingPoints')
  const closingTask = next.confirmed === true
  const closingAi = next.aiWriteOpen === false || editingMainCopy || closingTask
  if (closingAi && next.aiWriteOpen !== true) {
    nextTask.aiWriteOpen = false
    nextTask.aiSuggestionEditing = false
  }
  if (editingMainCopy || closingTask) nextTask.aiSuggestion = ''
  emit('update', nextTask)
}

function removeAsset(id: string) {
  patch({ assets: props.task.assets.filter((asset) => asset.id !== id), confirmed: false, aiWriteOpen: false, aiSuggestion: '' })
}

function selectFiles(event: Event) {
  const input = event.target as HTMLInputElement
  const files = Array.from(input.files ?? [])
  input.value = ''
  if (!files.length || imageLimitReached.value) return
  emit('upload', files.slice(0, Math.max(0, props.config.max_batch_item_assets - props.task.assets.length)))
}

function normalizeModuleSelections(source: unknown): AplusModuleSelection[] {
  const raw = Array.isArray(source) ? source : []
  return orderedAplusModuleSelections(raw.filter((item): item is AplusModuleSelection =>
    Boolean(item && typeof item === 'object' && 'name' in item && 'count' in item),
  ))
}

function moduleSelectionsFromGlobal(): AplusModuleSelection[] {
  return normalizeModuleSelections(props.globalParams.module_selections)
}

function advancedTargetsFromRecord(source: Record<string, unknown>): AplusAdvancedTarget[] {
  const raw = Array.isArray(source.advanced_targets)
    ? source.advanced_targets
    : Array.isArray(props.globalParams.advanced_targets)
      ? props.globalParams.advanced_targets
      : ['web']
  const targets = raw.filter((item): item is AplusAdvancedTarget => item === 'web' || item === 'mobile')
  return targets.length ? targets : ['web']
}

function clearAplusOutputOverride(next: Record<string, unknown>) {
  delete next.output_spec
  delete next.output_targets
  delete next.aspect_ratio
  delete next.advanced_targets
}

function applyAplusOutputOverride(next: Record<string, unknown>, value: unknown) {
  const platform = String(next.platform ?? props.globalParams.platform ?? '亚马逊')
  const requestedSpec = String(value || '1:1') as AplusOutputSpec
  const outputSpec = requestedSpec.startsWith('amazon_aplus') && !isAplusAmazon(platform) ? '1:1' : requestedSpec
  const formLike: AplusForm = {
    platform,
    market: String(next.market ?? props.globalParams.market ?? '美国'),
    language: String(next.language ?? props.globalParams.language ?? '英文'),
    category: String(next.category ?? props.globalParams.category ?? ''),
    productInfo: '',
    selectedModules: moduleSelectionsFromGlobal(),
    outputSpec,
    advancedTargets: advancedTargetsFromRecord(next),
    dryRun: Boolean(next.dry_run ?? props.globalParams.dry_run),
  }
  const outputTargets = buildAplusOutputTargets(formLike)
  next.output_spec = outputSpec
  next.output_targets = outputTargets
  next.aspect_ratio = outputTargets[0]?.aspect_ratio ?? '1:1'
  if (outputSpec === 'amazon_aplus_advanced') next.advanced_targets = formLike.advancedTargets
  else delete next.advanced_targets
}

function setOverride(key: string, value: unknown) {
  const next: Record<string, unknown> = { ...props.task.overrides }
  if (value === '' || value === props.globalParams[key]) delete next[key]
  else next[key] = value
  if (props.businessType === 'aplus') {
    if (key === 'platform') {
      const platform = String(next.platform ?? props.globalParams.platform ?? '')
      if (!next.platform) {
        clearAplusOutputOverride(next)
      } else if (!isAplusAmazon(platform)) {
        applyAplusOutputOverride(next, '1:1')
      } else {
        const outputSpec = String(next.output_spec || '')
        if (outputSpec) applyAplusOutputOverride(next, outputSpec)
        else clearAplusOutputOverride(next)
      }
    }
    if (key === 'output_spec') {
      const platform = String(next.platform ?? props.globalParams.platform ?? '')
      if (!value && next.platform && !isAplusAmazon(platform)) applyAplusOutputOverride(next, '1:1')
      else if (!value) clearAplusOutputOverride(next)
      else applyAplusOutputOverride(next, value)
    }
  }
  patch({ overrides: next, confirmed: false })
}

function overrideValue(key: string): string {
  return String(props.task.overrides[key] ?? '')
}

function moduleCount(moduleName: string): number {
  return taskModuleSelections.value.find((item) => item.name === moduleName)?.count ?? 0
}

function setTaskModuleFollow(followGlobal: boolean) {
  const next: Record<string, unknown> = { ...props.task.overrides }
  if (followGlobal) delete next.module_selections
  else next.module_selections = moduleSelectionsFromGlobal()
  patch({ overrides: next, confirmed: false })
}

function setTaskModuleCount(moduleName: string, count: number) {
  if (taskFollowsGlobalModules.value) return
  const normalized = Math.max(0, Math.min(APLUS_MODULE_TOTAL_LIMIT, Math.floor(count) || 0))
  const nextModules = taskModuleSelections.value.filter((item) => item.name !== moduleName)
  if (normalized > 0) nextModules.push({ name: moduleName, count: normalized })
  patch({
    overrides: {
      ...props.task.overrides,
      module_selections: orderedAplusModuleSelections(nextModules),
    },
    confirmed: false,
  })
}

function toggleTaskModule(moduleName: string) {
  if (taskFollowsGlobalModules.value) return
  if (moduleCount(moduleName) > 0) setTaskModuleCount(moduleName, 0)
  else if (taskModuleTotal.value < APLUS_MODULE_TOTAL_LIMIT) setTaskModuleCount(moduleName, 1)
}

function incrementTaskModule(moduleName: string) {
  if (taskModuleTotal.value >= APLUS_MODULE_TOTAL_LIMIT) return
  setTaskModuleCount(moduleName, moduleCount(moduleName) + 1)
}

function decrementTaskModule(moduleName: string) {
  setTaskModuleCount(moduleName, moduleCount(moduleName) - 1)
}

function inputValue(event: Event): string {
  return (event.target as HTMLInputElement | HTMLTextAreaElement | HTMLSelectElement).value
}

function applyAiSuggestion() {
  if (!props.task.aiSuggestion.trim()) return
  patch({
    sellingPoints: props.task.aiSuggestion.trim(),
    aiWriteOpen: false,
    aiSuggestionEditing: false,
    aiSuggestion: '',
    copyEditing: false,
    confirmed: false,
  })
}

function openCopyEditor() {
  if (props.task.copyEditing && !props.task.aiWriteOpen && !props.task.aiSuggestionEditing && !props.task.aiSuggestion) return
  patch({ copyEditing: true, aiWriteOpen: false })
  void nextTick(() => copyInput.value?.focus())
}
</script>

<template>
  <article
    v-if="task.confirmed"
    class="batch-task-summary-card"
    :class="{ invalid: highlighted }"
    :data-batch-task-id="task.id"
  >
    <div class="batch-summary-media">
      <img v-if="firstAsset" :src="firstAsset.url" :alt="firstAsset.original_name" />
      <CloudUploadOutlined v-else />
    </div>
    <b>{{ summaryTitle }}</b>
    <nav>
      <button type="button" aria-label="编辑任务" @click="patch({ confirmed: false, copyEditing: true, aiWriteOpen: false })"><EditOutlined /></button>
      <button type="button" aria-label="复制任务" @click="emit('copy')"><CopyOutlined /></button>
      <button type="button" aria-label="删除任务" :disabled="!canDelete" @click="emit('delete')"><DeleteOutlined /></button>
    </nav>
    <p v-if="validationMessages.length" class="batch-task-error">{{ validationMessages[0] }}</p>
  </article>

  <article v-else class="batch-task-card" :class="{ invalid: highlighted }" :data-batch-task-id="task.id">
    <header class="batch-task-header">
      <div>
        <b>{{ taskTitle }}</b>
        <span>{{ task.assets.length }}/{{ config.max_batch_item_assets }} 张图 · {{ task.confirmed ? '已确认' : '待确认' }}</span>
      </div>
      <nav>
        <button type="button" class="ghost-action" @click="emit('delete')" :disabled="!canDelete"><DeleteOutlined />删除</button>
        <button type="button" class="primary-action" @click="patch({ confirmed: true, aiWriteOpen: false })"><CheckOutlined />确定</button>
      </nav>
    </header>
    <p v-if="validationMessages.length" class="batch-task-error">{{ validationMessages[0] }}</p>

    <div class="batch-task-body">
      <section class="batch-upload-column">
        <span class="batch-field-title">上传图片</span>
        <div class="batch-upload-box" :class="{ disabled: imageLimitReached }">
          <input ref="fileInput" type="file" accept="image/png,image/jpeg,image/webp" multiple :disabled="imageLimitReached" @change="selectFiles" />
          <button type="button" class="batch-upload-trigger" :disabled="imageLimitReached" @click="fileInput?.click()">
            <CloudUploadOutlined />
            <span>{{ task.uploading ? '上传中' : imageLimitReached ? '已达上限' : '上传图片' }}</span>
          </button>
          <div class="batch-thumb-list" v-if="task.assets.length">
            <figure v-for="asset in task.assets" :key="asset.id">
              <img :src="asset.url" :alt="asset.original_name" />
              <button type="button" aria-label="删除图片" @click="removeAsset(asset.id)"><CloseOutlined /></button>
            </figure>
          </div>
          <p>拖拽或点击上传 JPEG/JPG/PNG，支持 {{ config.max_batch_item_assets }} 张</p>
          <small v-if="task.uploadError">{{ task.uploadError }}</small>
        </div>
      </section>

      <section class="batch-task-fields">
        <div class="batch-task-field">
          <div class="batch-field-heading">
            <span>{{ requirementLabel }}</span>
            <button type="button" class="mini-ai-button" :disabled="task.aiWriting" @pointerdown.stop @click.stop="emit('ai-write')"><ThunderboltOutlined />{{ task.aiWriting ? '生成中...' : aiLabel }}</button>
          </div>
          <div class="markdown-input-frame batch-copy-markdown-frame">
            <div
              v-if="task.sellingPoints.trim() && !task.copyEditing"
              class="markdown-preview main-copy-preview"
              role="button"
              tabindex="0"
              :aria-label="`编辑${requirementLabel}`"
              @click.stop="openCopyEditor"
              @keydown.enter.prevent="openCopyEditor"
              @keydown.space.prevent="openCopyEditor"
              v-html="renderMarkdown(task.sellingPoints)"
            />
            <textarea
              v-else
              ref="copyInput"
              :value="task.sellingPoints"
              rows="6"
              :placeholder="placeholder"
              @pointerdown.stop="openCopyEditor"
              @click.stop
              @focus="openCopyEditor"
              @blur="patch({ copyEditing: false })"
              @input="patch({ sellingPoints: inputValue($event), confirmed: false, aiWriteOpen: false })"
            />
          </div>
        </div>

        <div v-if="task.aiWriteOpen" class="batch-ai-write-panel">
          <header>
            <strong><ThunderboltOutlined />{{ aiLabel }}建议</strong>
            <button type="button" aria-label="关闭 AI 建议" @click="patch({ aiWriteOpen: false })"><CloseOutlined /></button>
          </header>
          <div class="markdown-input-frame batch-ai-suggestion-frame">
            <button
              v-if="task.aiSuggestion.trim() && !task.aiSuggestionEditing"
              class="markdown-preview"
              type="button"
              aria-label="编辑 AI 建议"
              @click="patch({ aiSuggestionEditing: true })"
              v-html="renderMarkdown(task.aiSuggestion)"
            />
            <textarea
              v-else
              :value="task.aiSuggestion"
              rows="6"
              aria-label="AI 建议内容"
              @blur="patch({ aiSuggestionEditing: false })"
              @input="patch({ aiSuggestion: inputValue($event) })"
            />
          </div>
          <footer>
            <button type="button" :disabled="task.aiWriting" @click="emit('ai-write')"><ThunderboltOutlined />{{ task.aiWriting ? '生成中...' : regenerateLabel }}</button>
            <button type="button" class="apply" @click="applyAiSuggestion">确认回填</button>
          </footer>
        </div>
      </section>
    </div>

    <button type="button" class="batch-override-toggle" @click="patch({ overridesOpen: !task.overridesOpen })">
      单独调整参数
      <UpOutlined v-if="task.overridesOpen" />
      <DownOutlined v-else />
    </button>
    <div v-if="task.overridesOpen" class="batch-override-grid">
      <label>平台<select :value="overrideValue('platform')" @change="setOverride('platform', inputValue($event))"><option value="">跟随全局-平台</option><option v-for="value in platformChoices" :key="value" :value="value">{{ value }}</option></select></label>
      <label>市场<select :value="overrideValue('market')" @change="setOverride('market', inputValue($event))"><option value="">跟随全局-市场</option><option v-for="value in marketChoices" :key="value" :value="value">{{ value }}</option></select></label>
      <label>语言<select :value="overrideValue('language')" @change="setOverride('language', inputValue($event))"><option value="">跟随全局-语言</option><option v-for="value in languageChoices" :key="value" :value="value">{{ value }}</option></select></label>
      <label v-if="businessType === 'suite'">比例<select :value="overrideValue('aspect_ratio')" @change="setOverride('aspect_ratio', inputValue($event))"><option value="">跟随全局-比例</option><option v-for="value in ratioOptions" :key="value" :value="value">{{ value }}</option></select></label>
      <label v-if="businessType === 'suite'">生成偏好<select :value="overrideValue('model_preference')" @change="setOverride('model_preference', inputValue($event))"><option value="">跟随全局-生成偏好</option><option value="fidelity">商品保持优先</option><option value="layout">视觉排版优先</option></select></label>
      <label v-else>输出规格<select :value="outputSpecOverrideValue" @change="setOverride('output_spec', inputValue($event))"><option value="">跟随全局-输出规格</option><option v-for="spec in itemOutputSpecChoices" :key="spec.value" :value="spec.value">{{ spec.label }}</option></select></label>
    </div>
    <section v-if="businessType === 'aplus' && task.overridesOpen" class="batch-override-module-panel" :class="{ disabled: taskFollowsGlobalModules }">
      <header>
        <div>
          <b>需要的模块{{ taskFollowsGlobalModules ? '-跟随全局' : '' }}</b>
          <span>已选 {{ taskModuleTotal }}/{{ APLUS_MODULE_TOTAL_LIMIT }} 张</span>
        </div>
        <button
          type="button"
          class="batch-follow-toggle"
          :class="{ active: taskFollowsGlobalModules }"
          :aria-pressed="taskFollowsGlobalModules"
          @click="setTaskModuleFollow(!taskFollowsGlobalModules)"
        >
          <span>跟随全局</span>
          <i />
        </button>
      </header>
      <small>选择需要的模块</small>
      <div class="batch-task-module-grid">
        <article
          v-for="module in aplusModules"
          :key="module.name"
          class="aplus-module-option batch-module-option batch-task-module-option"
          :class="{ active: moduleCount(module.name) > 0, disabled: taskFollowsGlobalModules }"
        >
          <button class="aplus-module-main" type="button" :disabled="taskFollowsGlobalModules" @click="toggleTaskModule(module.name)">
            <span><b>{{ module.name }}</b><small>{{ module.description }}</small></span>
          </button>
          <div class="aplus-module-stepper batch-task-module-stepper" :aria-label="`${module.name} 模块数量`">
            <button type="button" :disabled="taskFollowsGlobalModules || moduleCount(module.name) <= 0" :aria-label="`减少 ${module.name}`" @click.stop="decrementTaskModule(module.name)"><MinusOutlined /></button>
            <strong>{{ moduleCount(module.name) }}</strong>
            <button type="button" :disabled="taskFollowsGlobalModules || taskModuleTotal >= APLUS_MODULE_TOTAL_LIMIT" :aria-label="`增加 ${module.name}`" @click.stop="incrementTaskModule(module.name)"><PlusOutlined /></button>
          </div>
        </article>
      </div>
    </section>
  </article>
</template>
