<script setup lang="ts">
import { computed, nextTick, ref, watch } from 'vue'
import {
  BellOutlined,
  CheckOutlined,
  ClockCircleOutlined,
  DeleteOutlined,
  ExclamationCircleOutlined,
  MinusOutlined,
  PlusOutlined,
  RocketOutlined,
} from '@ant-design/icons-vue'
import { message } from 'ant-design-vue'
import {
  assistCopywriting,
  createBatchJob,
  getWorkspaceConfig,
  uploadAsset,
  userFacingApiErrorMessage,
  type Asset,
  type BatchBusinessType,
  type WorkspaceConfig,
} from '../../api/client'
import { trackWorkspaceEvent } from './analytics'
import {
  APLUS_MODULE_TOTAL_LIMIT,
  aplusLanguageOptions,
  aplusMarketOptions,
  aplusModuleTotal,
  aplusModules,
  aplusOutputSpecs,
  aplusPlatformOptions,
  buildAplusOutputTargets,
  isAplusAmazon,
  languageOptions,
  marketOptions,
  orderedAplusModuleSelections,
  platformOptions,
  ratioOptions,
  type AplusAdvancedTarget,
  type AplusForm,
  type AplusModuleSelection,
  type AplusOutputSpec,
  type WorkspaceForm,
} from './workspace-model'
import BatchHistoryDrawer from './BatchHistoryDrawer.vue'
import BatchTaskCard from './BatchTaskCard.vue'
import { useAuthStore } from '../auth/auth-store'
import {
  BATCH_SUITE_OUTPUT_COUNT,
  BATCH_UPLOAD_CONCURRENCY,
  type BatchSelectionPayload,
  batchValidationSummary,
  buildBatchPayload,
  createDefaultBatchTasks,
  createBatchGlobalParams,
  createBatchTaskDraft,
  estimateTaskOutputs,
  extractBatchProductName,
  type BatchGlobalParams,
  type BatchTaskDraft,
} from './batch-model'

const props = defineProps<{
  open: boolean
  businessType: BatchBusinessType
  suiteForm?: WorkspaceForm
  aplusForm?: AplusForm
}>()

const emit = defineEmits<{
  'update:open': [boolean]
  selectHistory: [BatchSelectionPayload]
  'require-auth': []
}>()
const authStore = useAuthStore()

const fallbackConfig: WorkspaceConfig = {
  max_upload_bytes: 0,
  max_batch_tasks: 0,
  max_batch_item_assets: 0,
  max_active_batch_items: 0,
  max_provider_concurrency: 0,
}

const modelPreferenceOptions = [
  { key: 'fidelity' as const, label: '商品保持优先', description: '优先保持商品外观、颜色、结构和标签一致' },
  { key: 'layout' as const, label: '视觉排版优先', description: '强化画面排版与文字呈现，商品保持度略低' },
]

const config = ref<WorkspaceConfig>(fallbackConfig)
const globalParams = ref<BatchGlobalParams>(createBatchGlobalParams(props.businessType, props.suiteForm, props.aplusForm))
const tasks = ref<BatchTaskDraft[]>(createDefaultBatchTasks())
const submitting = ref(false)
const historyOpen = ref(false)
const configLoaded = ref(false)
const aiWriteRuns = new Map<string, number>()
const submitNotice = ref('')
const highlightedTaskIds = ref<Set<string>>(new Set())

function requireAuthForModelAction(): boolean {
  if (authStore.isAuthenticated) return false
  emit('update:open', false)
  emit('require-auth')
  return true
}

const businessLabel = computed(() => props.businessType === 'aplus' ? 'A+详情' : '商品套图')
const businessDescription = computed(() => props.businessType === 'aplus'
  ? '按首页 A+ 详情逻辑批量生成模块图，支持普通详情、普通 A+ 与高级 A+ 输出。'
  : '按首页套图逻辑批量生成商品套图，统一应用平台、市场、语言、比例和生成偏好。')
const platformChoices = computed(() => props.businessType === 'aplus' ? aplusPlatformOptions : platformOptions)
const marketChoices = computed(() => props.businessType === 'aplus' ? aplusMarketOptions : marketOptions)
const languageChoices = computed(() => props.businessType === 'aplus' ? aplusLanguageOptions : languageOptions)
const amazonPlatform = computed(() => isAplusAmazon(String(globalParams.value.platform || '')))
const availableAplusOutputSpecs = computed(() => aplusOutputSpecs.filter((item) => !item.amazonOnly || amazonPlatform.value))
const selectedOutputSpec = computed(() => String(globalParams.value.output_spec || '1:1') as AplusOutputSpec)
const selectedAdvancedTargets = computed<AplusAdvancedTarget[]>(() => {
  const raw = Array.isArray(globalParams.value.advanced_targets) ? globalParams.value.advanced_targets : ['web']
  const targets = raw.filter((item): item is AplusAdvancedTarget => item === 'web' || item === 'mobile')
  return targets.length ? targets : ['web']
})
const selectedModules = computed<AplusModuleSelection[]>(() => {
  const raw = Array.isArray(globalParams.value.module_selections) ? globalParams.value.module_selections : []
  return orderedAplusModuleSelections(raw.filter((item): item is AplusModuleSelection =>
    Boolean(item && typeof item === 'object' && 'name' in item && 'count' in item),
  ))
})
const selectedModuleTotal = computed(() => aplusModuleTotal(selectedModules.value))
const summary = computed(() => batchValidationSummary(props.businessType, tasks.value, globalParams.value, config.value))
const canSubmit = computed(() => configLoaded.value && !submitting.value && summary.value.taskCount > 0 && !summary.value.limitExceeded && summary.value.incompleteCount === 0 && summary.value.uploadFailedCount === 0)
const submitButtonDisabled = computed(() => !configLoaded.value || submitting.value)
const taskValidationDetails = computed(() => tasks.value
  .map((task, index) => ({ taskId: task.id, messages: validateTask(task, index) }))
  .filter((item) => item.messages.length > 0))
const taskValidationMap = computed(() => new Map(taskValidationDetails.value.map((item) => [item.taskId, item.messages])))

function batchFeatureKey(): 'batch_suite' | 'batch_aplus' {
  return props.businessType === 'aplus' ? 'batch_aplus' : 'batch_suite'
}

function batchAnalyticsPayload(metadata: Record<string, unknown> = {}) {
  return {
    business_type: batchFeatureKey(),
    platform: String(globalParams.value.platform || ''),
    market: String(globalParams.value.market || ''),
    language: String(globalParams.value.language || ''),
    metadata: {
      business_type: props.businessType,
      task_count: tasks.value.length,
      valid_task_count: summary.value.taskCount,
      output_spec: String(globalParams.value.output_spec || ''),
      aspect_ratio: String(globalParams.value.aspect_ratio || globalParams.value.ratio || ''),
      dry_run: Boolean(globalParams.value.dry_run),
      ...metadata,
    },
  }
}

function trackBatchEvent(eventName: string, eventType = 'click', metadata: Record<string, unknown> = {}) {
  trackWorkspaceEvent({ event_name: eventName, event_type: eventType, feature_key: batchFeatureKey(), ...batchAnalyticsPayload(metadata) })
}

watch(() => props.open, async (open) => {
  if (!open) return
  trackBatchEvent('batch_modal_view', 'view')
  globalParams.value = createBatchGlobalParams(props.businessType, props.suiteForm, props.aplusForm)
  if (tasks.value.length < 2) tasks.value = createDefaultBatchTasks()
  if (!configLoaded.value) {
    try {
      config.value = await getWorkspaceConfig()
      configLoaded.value = true
    } catch {
      config.value = fallbackConfig
    }
  }
}, { immediate: true })

watch(() => props.businessType, () => {
  globalParams.value = createBatchGlobalParams(props.businessType, props.suiteForm, props.aplusForm)
  tasks.value = createDefaultBatchTasks()
})

watch(taskValidationDetails, (details) => {
  const invalidIds = new Set(details.map((item) => item.taskId))
  const nextHighlighted = new Set([...highlightedTaskIds.value].filter((id) => invalidIds.has(id)))
  highlightedTaskIds.value = nextHighlighted
  if (submitNotice.value) {
    submitNotice.value = details.length || summary.value.messages.length ? firstValidationMessage() : ''
  }
})

function selectValue(event: Event): string {
  return (event.target as HTMLSelectElement | HTMLInputElement).value
}

function checkedValue(event: Event): boolean {
  return (event.target as HTMLInputElement).checked
}

function normalizeAplusParams(next: Record<string, unknown>) {
  const outputSpec = String(next.output_spec || '1:1') as AplusOutputSpec
  const formLike: AplusForm = {
    platform: String(next.platform || '亚马逊'),
    market: String(next.market || '美国'),
    language: String(next.language || '英文'),
    category: String(next.category || ''),
    productInfo: '',
    selectedModules: selectedModulesFromRecord(next),
    outputSpec,
    advancedTargets: selectedAdvancedTargetsFromRecord(next),
    dryRun: Boolean(next.dry_run),
  }
  const outputTargets = buildAplusOutputTargets(formLike)
  next.module_selections = orderedAplusModuleSelections(formLike.selectedModules)
  next.output_targets = outputTargets
  next.aspect_ratio = outputTargets[0]?.aspect_ratio ?? '1:1'
}

function selectedModulesFromRecord(source: Record<string, unknown>): AplusModuleSelection[] {
  const raw = Array.isArray(source.module_selections) ? source.module_selections : []
  return orderedAplusModuleSelections(raw.filter((item): item is AplusModuleSelection =>
    Boolean(item && typeof item === 'object' && 'name' in item && 'count' in item),
  ))
}

function selectedAdvancedTargetsFromRecord(source: Record<string, unknown>): AplusAdvancedTarget[] {
  const raw = Array.isArray(source.advanced_targets) ? source.advanced_targets : ['web']
  const targets = raw.filter((item): item is AplusAdvancedTarget => item === 'web' || item === 'mobile')
  return targets.length ? targets : ['web']
}

function setGlobalParam(key: string, value: unknown) {
  if (['platform', 'market', 'language', 'aspect_ratio', 'ratio', 'dry_run'].includes(key)) {
    trackBatchEvent('batch_param_change', 'click', { param_key: key, param_value: value })
  }
  const next: Record<string, unknown> = { ...globalParams.value, [key]: value }
  if (props.businessType === 'aplus') {
    if (key === 'platform' && !isAplusAmazon(String(value)) && String(next.output_spec || '').startsWith('amazon_aplus')) {
      next.output_spec = '1:1'
      next.advanced_targets = ['web']
    }
    normalizeAplusParams(next)
  } else {
    next.count = BATCH_SUITE_OUTPUT_COUNT
    next.mode = 'smart'
    delete next.custom_counts
  }
  globalParams.value = next as BatchGlobalParams
}

function selectAplusOutputSpec(spec: AplusOutputSpec) {
  trackBatchEvent('batch_aplus_output_spec_click', 'click', { output_spec: spec })
  if (spec.startsWith('amazon_aplus') && !amazonPlatform.value) {
    message.warning('普通 A+ 和高级 A+ 仅亚马逊平台可用')
    return
  }
  const next: Record<string, unknown> = { ...globalParams.value, output_spec: spec }
  if (spec === 'amazon_aplus_advanced' && !selectedAdvancedTargetsFromRecord(next).length) next.advanced_targets = ['web']
  normalizeAplusParams(next)
  globalParams.value = next as BatchGlobalParams
}

function toggleAdvancedTarget(target: AplusAdvancedTarget) {
  trackBatchEvent('batch_aplus_advanced_target_click', 'click', { advanced_target: target })
  const current = selectedAdvancedTargets.value
  const exists = current.includes(target)
  if (exists && current.length === 1) {
    message.warning('高级 A+ 至少选择 Web 或移动端中的一个')
    return
  }
  const nextTargets = exists ? current.filter((item) => item !== target) : [...current, target]
  const next: Record<string, unknown> = { ...globalParams.value, advanced_targets: nextTargets }
  normalizeAplusParams(next)
  globalParams.value = next as BatchGlobalParams
}

function moduleCount(moduleName: string): number {
  return selectedModules.value.find((item) => item.name === moduleName)?.count ?? 0
}

function setModuleCount(moduleName: string, count: number) {
  const normalized = Math.max(0, Math.min(APLUS_MODULE_TOTAL_LIMIT, Math.floor(count) || 0))
  const nextModules = selectedModules.value.filter((item) => item.name !== moduleName)
  if (normalized > 0) nextModules.push({ name: moduleName, count: normalized })
  const next: Record<string, unknown> = { ...globalParams.value, module_selections: orderedAplusModuleSelections(nextModules) }
  normalizeAplusParams(next)
  globalParams.value = next as BatchGlobalParams
}

function toggleModule(moduleName: string) {
  trackBatchEvent('batch_aplus_module_click', 'click', { module_name: moduleName, selected: moduleCount(moduleName) <= 0 })
  if (moduleCount(moduleName) > 0) {
    setModuleCount(moduleName, 0)
    return
  }
  if (selectedModuleTotal.value >= APLUS_MODULE_TOTAL_LIMIT) {
    message.warning(`详情页模块最多生成 ${APLUS_MODULE_TOTAL_LIMIT} 张`)
    return
  }
  setModuleCount(moduleName, 1)
}

function incrementModule(moduleName: string) {
  trackBatchEvent('batch_aplus_module_increment', 'click', { module_name: moduleName })
  if (selectedModuleTotal.value >= APLUS_MODULE_TOTAL_LIMIT) {
    message.warning(`详情页模块最多生成 ${APLUS_MODULE_TOTAL_LIMIT} 张`)
    return
  }
  setModuleCount(moduleName, moduleCount(moduleName) + 1)
}

function decrementModule(moduleName: string) {
  trackBatchEvent('batch_aplus_module_decrement', 'click', { module_name: moduleName })
  setModuleCount(moduleName, moduleCount(moduleName) - 1)
}

function validateTask(task: BatchTaskDraft, index: number): string[] {
  const taskLabel = `任务${index + 1}`
  const messages: string[] = []
  if (task.uploadError) messages.push(`${taskLabel}上传失败，请重新上传`)
  if (task.assets.length < 1) messages.push(`${taskLabel}缺少商品图`)
  else if (task.assets.length > config.value.max_batch_item_assets) messages.push(`${taskLabel}商品图超过 ${config.value.max_batch_item_assets} 张`)
  if (props.businessType === 'suite' && !task.sellingPoints.trim() && !String(globalParams.value.selling_points || '').trim()) {
    messages.push(`${taskLabel}缺少商品卖点与要求`)
  }
  if (props.businessType === 'aplus' && estimateTaskOutputs(props.businessType, globalParams.value, task.overrides) < 1) {
    messages.push(`${taskLabel}未选择详情页模块或输出规格`)
  }
  return messages
}

function taskValidationMessages(taskId: string): string[] {
  return taskValidationMap.value.get(taskId) ?? []
}

function firstValidationMessage(): string {
  if (!configLoaded.value) return '批量配置加载中，请稍后再提交'
  if (summary.value.taskCount < 1) return '至少需要 1 个商品任务'
  if (summary.value.limitExceeded) return summary.value.messages[0] || `单批最多 ${config.value.max_batch_tasks} 个商品任务`
  const firstTaskIssue = taskValidationDetails.value[0]?.messages[0]
  return firstTaskIssue || summary.value.messages[0] || '请补全商品任务配置'
}

async function showSubmitValidation() {
  const invalidIds = new Set(taskValidationDetails.value.map((item) => item.taskId))
  highlightedTaskIds.value = invalidIds
  submitNotice.value = firstValidationMessage()
  await nextTick()
  const firstInvalidId = taskValidationDetails.value[0]?.taskId
  if (firstInvalidId) {
    document.querySelector(`[data-batch-task-id="${firstInvalidId}"]`)?.scrollIntoView({ block: 'center', behavior: 'smooth' })
  }
}

function nextAiWriteRun(taskId: string): number {
  const runId = (aiWriteRuns.get(taskId) ?? 0) + 1
  aiWriteRuns.set(taskId, runId)
  return runId
}

function invalidateAiWriteRun(taskId: string) {
  aiWriteRuns.set(taskId, (aiWriteRuns.get(taskId) ?? 0) + 1)
}

function updateTask(index: number, task: BatchTaskDraft, options: { keepAiRun?: boolean } = {}) {
  const previous = tasks.value[index]
  if (!options.keepAiRun && previous?.id === task.id) {
    const copyChanged = previous.sellingPoints !== task.sellingPoints
    const aiPanelClosed = previous.aiWriteOpen && !task.aiWriteOpen
    const enteredCopyEditing = !previous.copyEditing && task.copyEditing && !task.aiWriteOpen
    if (copyChanged || aiPanelClosed || enteredCopyEditing || task.confirmed) invalidateAiWriteRun(task.id)
  }
  tasks.value = tasks.value.map((item, taskIndex) => taskIndex === index ? task : item)
}

function deleteTask(index: number) {
  if (tasks.value.length === 1) return
  tasks.value = tasks.value.filter((_, taskIndex) => taskIndex !== index)
}

function taskSummaryName(task: BatchTaskDraft, index: number): string {
  if (task.name.trim()) return task.name.trim()
  return extractBatchProductName(task.sellingPoints) || `${props.businessType === 'aplus' ? 'A+任务' : '商品任务'}${index + 1}`
}

function copyTask(index: number) {
  const task = tasks.value[index]
  if (!task) return
  if (tasks.value.length >= config.value.max_batch_tasks) {
    message.warning(`单批最多 ${config.value.max_batch_tasks} 个商品任务`)
    return
  }
  const copy: BatchTaskDraft = {
    ...task,
    id: `batch-task-${Date.now()}-copy`,
    name: `${taskSummaryName(task, index)}（复制）`,
    assets: [...task.assets],
    overrides: { ...task.overrides },
    confirmed: false,
    overridesOpen: false,
    uploadError: '',
    uploading: false,
    aiWriting: false,
    aiWriteOpen: false,
    aiSuggestion: '',
    aiSuggestionEditing: false,
    copyEditing: true,
  }
  tasks.value = [...tasks.value.slice(0, index + 1), copy, ...tasks.value.slice(index + 1)]
}

function addTask() {
  trackBatchEvent('batch_add_task_click', 'click')
  if (tasks.value.length >= config.value.max_batch_tasks) {
    message.warning(`单批最多 ${config.value.max_batch_tasks} 个商品任务`)
    return
  }
  tasks.value = [...tasks.value, createBatchTaskDraft(tasks.value.length + 1)]
}

function openBatchHistory() {
  trackBatchEvent('batch_history_click', 'click')
  historyOpen.value = true
}

function clearBatchDraft() {
  if (submitting.value) return
  trackBatchEvent('batch_clear_click', 'click')
  tasks.value = createDefaultBatchTasks()
  submitNotice.value = ''
  highlightedTaskIds.value = new Set()
  aiWriteRuns.clear()
}

async function uploadTaskFiles(index: number, files: File[]) {
  const task = tasks.value[index]
  if (!task) return
  const taskId = task.id
  updateTask(index, { ...task, uploading: true, uploadError: '' })
  const queue = [...files]
  const uploaded: Asset[] = []
  try {
    const workers = Array.from({ length: Math.min(BATCH_UPLOAD_CONCURRENCY, queue.length) }, async () => {
      while (queue.length) {
        const file = queue.shift()
        if (file) uploaded.push(await uploadAsset(file))
      }
    })
    await Promise.all(workers)
    const latest = tasks.value[index]
    if (!latest || latest.id !== taskId) return
    updateTask(index, {
      ...latest,
      assets: [...latest.assets, ...uploaded].slice(0, config.value.max_batch_item_assets),
      uploading: false,
      uploadError: '',
      confirmed: false,
      aiWriteOpen: false,
      aiSuggestion: '',
    })
  } catch {
    const latest = tasks.value[index]
    if (!latest || latest.id !== taskId) return
    updateTask(index, { ...latest, uploading: false, uploadError: '上传失败，请重新选择图片', confirmed: false })
  }
}

async function aiWriteTask(index: number) {
  if (requireAuthForModelAction()) return
  const task = tasks.value[index]
  if (!task) return
  trackBatchEvent('batch_ai_copywriting_click', 'click', { task_index: index, asset_count: task.assets.length })
  const taskId = task.id
  const runId = nextAiWriteRun(taskId)
  updateTask(index, { ...task, aiWriting: true, aiWriteOpen: false, aiSuggestionEditing: false }, { keepAiRun: true })
  try {
    const result = await assistCopywriting({
      asset_ids: task.assets.map((asset) => asset.id),
      platform: String(globalParams.value.platform),
      market: String(globalParams.value.market),
      language: String(globalParams.value.language),
      selling_points: task.sellingPoints,
      dry_run: Boolean(globalParams.value.dry_run),
    })
    const latest = tasks.value[index]
    if (!latest || latest.id !== taskId) return
    if (aiWriteRuns.get(taskId) !== runId) {
      updateTask(index, { ...latest, aiWriting: false }, { keepAiRun: true })
      return
    }
    updateTask(index, {
      ...latest,
      aiSuggestion: result.selling_points,
      aiSuggestionEditing: false,
      aiWriteOpen: true,
      aiWriting: false,
      confirmed: false,
    }, { keepAiRun: true })
  } catch {
    const latest = tasks.value[index]
    if (latest?.id === taskId) updateTask(index, { ...latest, aiWriting: false }, { keepAiRun: true })
    message.error(props.businessType === 'aplus' ? 'AI 转写失败' : 'AI 帮写失败')
  }
}

async function submitBatch() {
  if (requireAuthForModelAction()) return
  trackBatchEvent('batch_submit_click', 'click', { can_submit: canSubmit.value })
  if (!canSubmit.value) {
    await showSubmitValidation()
    return
  }
  submitNotice.value = ''
  highlightedTaskIds.value = new Set()
  submitting.value = true
  try {
    const payload = buildBatchPayload(props.businessType, globalParams.value, tasks.value)
    trackBatchEvent('batch_submit', 'submit', { submitted_tasks: tasks.value.length, estimated_outputs: summary.value.estimatedImages })
    await createBatchJob(payload)
    historyOpen.value = true
    message.success('任务已在后台运行，可在消息中心查看结果')
  } catch (error: unknown) {
    message.error(userFacingApiErrorMessage(error) || '批量生成托管提交失败')
  } finally {
    submitting.value = false
  }
}
</script>

<template>
  <a-modal
    :open="open"
    :footer="null"
    width="1180px"
    wrap-class-name="batch-hosting-modal-wrap"
    @update:open="emit('update:open', $event)"
  >
    <template #title>
      <div class="batch-modal-title">
        <span><RocketOutlined />批量生成托管</span>
        <em>{{ businessLabel }}</em>
      </div>
    </template>

    <div class="batch-modal-toolbar">
      <button type="button" class="ghost-action disabled-action"><BellOutlined />通知设置</button>
      <button type="button" class="ghost-action" :disabled="submitting" @click="clearBatchDraft"><DeleteOutlined />清空</button>
      <button type="button" class="ghost-action" @click="openBatchHistory"><ClockCircleOutlined />生成记录</button>
    </div>
    <Transition name="batch-notice">
      <div v-if="submitNotice" class="batch-submit-notice" role="alert">
        <ExclamationCircleOutlined />
        <span>{{ submitNotice }}</span>
      </div>
    </Transition>

    <div class="batch-business-lock">
      <i><RocketOutlined /></i>
      <div>
        <b>{{ businessLabel }}批量生成</b>
        <span>{{ businessDescription }}</span>
      </div>
    </div>

    <section class="batch-global-panel">
      <header>
        <div>
          <b>全局批量设置</b>
          <span>应用于下方所有商品任务，单个商品可单独覆盖</span>
        </div>
        <label class="batch-dryrun-toggle">
          <input type="checkbox" :checked="Boolean(globalParams.dry_run)" @change="setGlobalParam('dry_run', checkedValue($event))" />
          <i />
          <span>安全演示模式</span>
        </label>
      </header>

      <div class="batch-global-grid" :class="{ 'aplus-global-grid': businessType === 'aplus', 'suite-global-grid': businessType === 'suite' }">
        <label>目标平台<select :value="globalParams.platform" @change="setGlobalParam('platform', selectValue($event))"><option v-for="value in platformChoices" :key="value" :value="value">{{ value }}</option></select></label>
        <label>目标市场<select :value="globalParams.market" @change="setGlobalParam('market', selectValue($event))"><option v-for="value in marketChoices" :key="value" :value="value">{{ value }}</option></select></label>
        <label>图片语言<select :value="globalParams.language" @change="setGlobalParam('language', selectValue($event))"><option v-for="value in languageChoices" :key="value" :value="value">{{ value }}</option></select></label>
        <label v-if="businessType === 'suite'">画面比例<select :value="globalParams.aspect_ratio" @change="setGlobalParam('aspect_ratio', selectValue($event))"><option v-for="value in ratioOptions" :key="value" :value="value">{{ value }}</option></select></label>
        <label v-if="businessType === 'suite'">生成偏好<select :value="String(globalParams.model_preference || 'fidelity')" @change="setGlobalParam('model_preference', selectValue($event))"><option v-for="option in modelPreferenceOptions" :key="option.key" :value="option.key">{{ option.label }}</option></select></label>
      </div>

      <div v-if="businessType === 'aplus'" class="batch-aplus-config">
        <div class="batch-output-head">
          <b>输出规格</b>
          <span v-if="!amazonPlatform">普通 A+ 和高级 A+ 仅亚马逊平台可用。</span>
        </div>
        <div class="batch-output-grid">
          <button v-for="spec in availableAplusOutputSpecs" :key="spec.value" type="button" :class="{ active: selectedOutputSpec === spec.value }" @click="selectAplusOutputSpec(spec.value)">
            <i><CheckOutlined v-if="selectedOutputSpec === spec.value" /></i>
            <span><b>{{ spec.label }}</b><small>{{ spec.description }}</small></span>
          </button>
        </div>
        <div v-if="amazonPlatform && selectedOutputSpec === 'amazon_aplus_advanced'" class="batch-advanced-targets">
          <b>高级 A+ 端</b>
          <button type="button" :class="{ active: selectedAdvancedTargets.includes('web') }" @click="toggleAdvancedTarget('web')"><CheckOutlined v-if="selectedAdvancedTargets.includes('web')" />Web · 1464:600</button>
          <button type="button" :class="{ active: selectedAdvancedTargets.includes('mobile') }" @click="toggleAdvancedTarget('mobile')"><CheckOutlined v-if="selectedAdvancedTargets.includes('mobile')" />移动端 · 600:450</button>
        </div>

        <div class="batch-aplus-module-head">
          <b>详情页模块</b>
          <em>{{ selectedModuleTotal }}/{{ APLUS_MODULE_TOTAL_LIMIT }} 张</em>
        </div>
        <div class="batch-aplus-module-grid">
          <article v-for="module in aplusModules" :key="module.name" class="aplus-module-option batch-module-option" :class="{ active: moduleCount(module.name) > 0 }">
            <button class="aplus-module-main" type="button" @click="toggleModule(module.name)">
              <span><b>{{ module.name }}</b><small>{{ module.description }}</small></span>
            </button>
            <div class="aplus-module-stepper" :aria-label="`${module.name} 模块数量`">
              <button type="button" :disabled="moduleCount(module.name) <= 0" :aria-label="`减少 ${module.name}`" @click.stop="decrementModule(module.name)"><MinusOutlined /></button>
              <strong>{{ moduleCount(module.name) }}</strong>
              <button type="button" :disabled="selectedModuleTotal >= APLUS_MODULE_TOTAL_LIMIT" :aria-label="`增加 ${module.name}`" @click.stop="incrementModule(module.name)"><PlusOutlined /></button>
            </div>
          </article>
        </div>
      </div>
    </section>

    <section class="batch-task-stack">
      <BatchTaskCard
        v-for="(task, index) in tasks"
        :key="task.id"
        :task="task"
        :index="index + 1"
        :business-type="businessType"
        :config="config"
        :global-params="globalParams"
        :can-delete="tasks.length > 1"
        :validation-messages="taskValidationMessages(task.id)"
        :highlighted="highlightedTaskIds.has(task.id)"
        @update="updateTask(index, $event)"
        @delete="deleteTask(index)"
        @copy="copyTask(index)"
        @upload="uploadTaskFiles(index, $event)"
        @ai-write="aiWriteTask(index)"
      />
    </section>

    <button type="button" class="batch-add-task" @click="addTask"><PlusOutlined />新建商品任务</button>

    <footer class="batch-submit-bar">
      <div>
        <b>{{ summary.taskCount }} 个商品任务</b>
        <span>预计生成 {{ summary.estimatedImages }} 张 · 上传失败 {{ summary.uploadFailedCount }} 项 · 配置不完整 {{ summary.incompleteCount }} 项</span>
      </div>
      <button type="button" class="primary-action submit-batch-action" :class="{ attention: configLoaded && !canSubmit && !submitting }" :disabled="submitButtonDisabled" @click="submitBatch">
        {{ submitting ? '提交中' : '提交任务' }}
      </button>
    </footer>

    <BatchHistoryDrawer v-model:open="historyOpen" :business-type="businessType" @select-tasks="emit('selectHistory', $event)" />
  </a-modal>
</template>
