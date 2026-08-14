import type { AplusJob, Asset, BatchBusinessType, BatchItem, Job, WorkspaceConfig } from '../../api/client'
import {
  buildAplusOutputTargets,
  createDefaultAplusForm,
  createDefaultWorkspaceForm,
  orderedAplusModuleSelections,
  ratioValues,
  type AplusForm,
  type WorkspaceForm,
} from './workspace-model'

export const BATCH_UPLOAD_CONCURRENCY = 3
export const BATCH_SUITE_OUTPUT_COUNT = 7

export type BatchGlobalParams = Record<string, unknown> & {
  platform: string
  market: string
  language: string
  aspect_ratio: string
  dry_run: boolean
}

export type BatchTaskDraft = {
  id: string
  name: string
  sellingPoints: string
  aiSuggestion: string
  aiWriteOpen: boolean
  aiSuggestionEditing: boolean
  aiWriting: boolean
  copyEditing: boolean
  assets: Asset[]
  pendingFiles: File[]
  uploading: boolean
  uploadError: string
  confirmed: boolean
  overridesOpen: boolean
  overrides: Record<string, unknown>
}

export type BatchValidationSummary = {
  taskCount: number
  estimatedImages: number
  uploadFailedCount: number
  incompleteCount: number
  limitExceeded: boolean
  messages: string[]
}

export type BatchSelectionTask = {
  batchId: string
  batchCreatedAt: string
  batchStatus: string
  batchProgress: number
  item: BatchItem
}

export type BatchSelectionPayload = {
  businessType: BatchBusinessType
  tasks: BatchSelectionTask[]
}

export function batchItemResultJob(item: BatchItem, businessType: BatchBusinessType): Job | AplusJob | null {
  return businessType === 'aplus' ? item.aplus_generation_job ?? null : item.generation_job ?? null
}

export function batchItemSuccessIds(item: BatchItem, businessType: BatchBusinessType): string[] {
  const job = batchItemResultJob(item, businessType)
  return job?.items.filter((result) => result.status === 'succeeded').map((result) => result.id) ?? []
}

export function createBatchTaskDraft(index = 1): BatchTaskDraft {
  return {
    id: `batch-task-${Date.now()}-${index}`,
    name: '',
    sellingPoints: '',
    aiSuggestion: '',
    aiWriteOpen: false,
    aiSuggestionEditing: false,
    aiWriting: false,
    copyEditing: false,
    assets: [],
    pendingFiles: [],
    uploading: false,
    uploadError: '',
    confirmed: false,
    overridesOpen: false,
    overrides: {},
  }
}

export function createDefaultBatchTasks(): BatchTaskDraft[] {
  return [createBatchTaskDraft(1), createBatchTaskDraft(2)]
}

export function extractBatchProductName(text: string): string {
  const placeholderValues = new Set(['-', '--', '---', '无', '暂无', '未填写', '未识别'])
  const namePattern = /(?:品名|商品名|商品名称|产品名|产品名称)\s*[:：]\s*(.+)$/i
  for (const rawLine of text.split(/\r?\n/)) {
    const line = rawLine
      .replace(/^[\s>*#-]+/, '')
      .replace(/^[\s\d.、，,：:]+/, '')
      .replace(/\*\*/g, '')
      .trim()
    const match = line.match(namePattern)
    if (!match) continue
    const name = match[1]
      .replace(/\*\*/g, '')
      .replace(/^[\s"'“”‘’]+|[\s"'“”‘’，,。；;]+$/g, '')
      .trim()
    if (name && !placeholderValues.has(name)) return name.slice(0, 40)
  }
  return ''
}

export function createBatchGlobalParams(
  businessType: BatchBusinessType,
  suiteForm: WorkspaceForm = createDefaultWorkspaceForm(),
  aplusForm: AplusForm = createDefaultAplusForm(),
): BatchGlobalParams {
  if (businessType === 'aplus') {
    const outputTargets = buildAplusOutputTargets(aplusForm)
    return {
      platform: aplusForm.platform,
      market: aplusForm.market,
      language: aplusForm.language,
      category: aplusForm.category,
      aspect_ratio: outputTargets[0]?.aspect_ratio ?? '1:1',
      output_spec: aplusForm.outputSpec,
      advanced_targets: [...aplusForm.advancedTargets],
      module_selections: orderedAplusModuleSelections(aplusForm.selectedModules),
      output_targets: outputTargets,
      dry_run: aplusForm.dryRun,
    }
  }
  return {
    platform: suiteForm.platform,
    market: suiteForm.market,
    language: suiteForm.language,
    category: suiteForm.category,
    aspect_ratio: ratioValues[suiteForm.ratio] ?? '1:1',
    mode: 'smart',
    count: BATCH_SUITE_OUTPUT_COUNT,
    model_preference: suiteForm.modelPreference,
    dry_run: suiteForm.dryRun,
  }
}

export function estimateBatchOutputs(businessType: BatchBusinessType, globalParams: Record<string, unknown>): number {
  if (businessType === 'aplus') {
    const modules = Array.isArray(globalParams.module_selections) ? globalParams.module_selections : []
    const moduleCount = modules.reduce((total, item) => {
      if (!item || typeof item !== 'object') return total
      return total + Math.max(0, Number((item as Record<string, unknown>).count) || 0)
    }, 0)
    const targetCount = Array.isArray(globalParams.output_targets) ? globalParams.output_targets.length : 1
    return moduleCount > 0 && targetCount > 0 ? moduleCount * targetCount : 0
  }
  return BATCH_SUITE_OUTPUT_COUNT
}

export function estimateTaskOutputs(
  businessType: BatchBusinessType,
  globalParams: Record<string, unknown>,
  overrides: Record<string, unknown> = {},
): number {
  if (businessType !== 'aplus') return BATCH_SUITE_OUTPUT_COUNT
  return estimateBatchOutputs(businessType, { ...globalParams, ...overrides })
}

export function batchValidationSummary(
  businessType: BatchBusinessType,
  tasks: BatchTaskDraft[],
  globalParams: Record<string, unknown>,
  config: WorkspaceConfig,
): BatchValidationSummary {
  const messages: string[] = []
  const uploadFailedCount = tasks.filter((task) => task.uploadError).length
  const baseIncompleteCount = tasks.filter((task) => {
    if (task.assets.length < 1 || task.assets.length > config.max_batch_item_assets) return true
    if (businessType === 'suite' && !task.sellingPoints.trim() && !String(globalParams.selling_points || '').trim()) return true
    if (businessType === 'aplus' && estimateTaskOutputs(businessType, globalParams, task.overrides) < 1) return true
    return false
  }).length
  const aplusGlobalIncomplete = businessType === 'aplus'
    && estimateBatchOutputs(businessType, globalParams) < 1
    && !tasks.some((task) => estimateTaskOutputs(businessType, globalParams, task.overrides) > 0)
  const incompleteCount = baseIncompleteCount
  const limitExceeded = tasks.length > config.max_batch_tasks
  if (limitExceeded) messages.push(`最多 ${config.max_batch_tasks} 个商品任务`)
  if (uploadFailedCount) messages.push(`${uploadFailedCount} 个任务上传失败`)
  if (aplusGlobalIncomplete) messages.push('请至少选择 1 个详情页模块和 1 个输出规格')
  if (incompleteCount) messages.push(`${incompleteCount} 个任务配置不完整`)
  return {
    taskCount: tasks.length,
    estimatedImages: tasks.reduce((total, task) => total + estimateTaskOutputs(businessType, globalParams, task.overrides), 0),
    uploadFailedCount,
    incompleteCount,
    limitExceeded,
    messages,
  }
}

export function buildBatchPayload(
  businessType: BatchBusinessType,
  globalParams: Record<string, unknown>,
  tasks: BatchTaskDraft[],
) {
  return {
    business_type: businessType,
    global_params: globalParams,
    notification_config: { in_app: true, completion_toast: true },
    items: tasks.map((task) => ({
      asset_ids: task.assets.map((asset) => asset.id),
      name: task.name.trim() || extractBatchProductName(task.sellingPoints),
      selling_points: task.sellingPoints.trim(),
      overrides: task.overrides,
    })),
  }
}
