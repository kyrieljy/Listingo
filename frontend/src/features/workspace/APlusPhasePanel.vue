<script setup lang="ts">
import { computed, nextTick, onActivated, ref, watch } from 'vue'
import { message } from 'ant-design-vue'
import {
  CheckOutlined,
  CloseOutlined,
  CloudUploadOutlined,
  DownloadOutlined,
  EditOutlined,
  EyeOutlined,
  LoadingOutlined,
  MinusOutlined,
  PlayCircleOutlined,
  PlusOutlined,
  RocketOutlined,
  ThunderboltOutlined,
} from '@ant-design/icons-vue'
import {
  assistCopywriting,
  aplusDownloadUrl,
  cancelAplusGenerationJob,
  cancelAplusPlanJob,
  createAplusGenerationJob,
  createAplusPlanJob,
  editAplusItem,
  getAplusGenerationJob,
  getAplusPlanJob,
  uploadAsset,
  type AplusItem,
  type AplusJob,
  type Asset,
} from '../../api/client'
import {
  APLUS_MODULE_TOTAL_LIMIT,
  aplusLanguageOptions,
  aplusMarketOptions,
  aplusModuleTotal,
  aplusModules,
  aplusOutputSpecs,
  aplusPlatformOptions,
  aplusTargetLabel,
  buildAplusOutputTargets,
  buildAplusPlanPayload,
  createDefaultAplusForm,
  isAplusAmazon,
  orderedAplusModuleSelections,
  renderMarkdown,
  type AplusOutputSpec,
} from './workspace-model'

const assets = ref<Asset[]>([])
const uploading = ref(false)
const helping = ref(false)
const planning = ref(false)
const generating = ref(false)
const cancelling = ref(false)
const cancelRequested = ref(false)
const form = ref(createDefaultAplusForm())
const planJob = ref<AplusJob | null>(null)
const generationJob = ref<AplusJob | null>(null)
const selectedPlanItemIds = ref<string[]>([])
const selectedResultIds = ref<string[]>([])
const previewItem = ref<AplusItem | null>(null)
const scriptItem = ref<AplusItem | null>(null)
const editItemState = ref<AplusItem | null>(null)
const editInstruction = ref('请保持商品主体一致，优化画面质感和版式')
const aiSuggestion = ref('')
const aiWriteOpen = ref(false)
const productInfoEditing = ref(false)
const aiSuggestionEditing = ref(false)
const productInfoInput = ref<HTMLTextAreaElement | null>(null)
const aiSuggestionInput = ref<HTMLTextAreaElement | null>(null)
const APLUS_JOB_POLL_INTERVAL_MS = 500
const FINAL_APLUS_JOB_STATUSES = new Set(['succeeded', 'partial_failed', 'failed', 'cancelled', 'partial_cancelled'])
const refreshingAplusJobId = ref<string | null>(null)

const productInfoPlaceholder = `可选：填写商品事实、参数、卖点。
建议包含商品名称、核心卖点、适用人群、场景和必须遵循的事实。`

const aplusShowcaseCards = [
  {
    title: '户外场景生成',
    eyebrow: 'SCENE',
    image: '/demo/video-backpack-showcase-01.png',
    description: '把商品带入露营、登山、通勤等真实场景，快速生成详情页首屏视觉。',
  },
  {
    title: '卖点脚本策划',
    eyebrow: 'COPY',
    image: '/demo/video-backpack-showcase-02.png',
    description: '围绕核心卖点组织标题、短句和模块文案，让详情页信息更好扫读。',
  },
  {
    title: '素材智能拆解',
    eyebrow: 'ASSET',
    image: '/demo/video-backpack-showcase-03.png',
    description: '识别容量、内部分区和配件素材，为不同详情页模块匹配合适画面。',
  },
  {
    title: '多平台详情适配',
    eyebrow: 'LAYOUT',
    image: '/demo/video-backpack-showcase-04.png',
    description: '按普通详情、标准 A+、高级 A+ 输出比例，生成适合上架的页面模块。',
  },
  {
    title: '防水细节展示',
    eyebrow: 'DETAIL',
    image: '/demo/video-backpack-showcase-05.png',
    description: '突出面料、防水、拉链和扣具等细节，形成可信的功能证明模块。',
  },
]

const uploadLimitReached = computed(() => assets.value.length >= 3)
const amazonPlatform = computed(() => isAplusAmazon(form.value.platform))
const availableOutputSpecs = computed(() => aplusOutputSpecs.filter((item) => !item.amazonOnly || amazonPlatform.value))
const outputTargets = computed(() => buildAplusOutputTargets(form.value))
const selectedModuleTotal = computed(() => aplusModuleTotal(form.value.selectedModules))
const plannedResultCount = computed(() => selectedModuleTotal.value * outputTargets.value.length)
const canPlan = computed(() => assets.value.length > 0 && selectedModuleTotal.value > 0 && outputTargets.value.length > 0)
const aplusTaskActive = computed(() => Boolean((planJob.value && !FINAL_APLUS_JOB_STATUSES.has(planJob.value.status)) || (generationJob.value && !FINAL_APLUS_JOB_STATUSES.has(generationJob.value.status))))
const previewUrl = computed(() => previewItem.value ? currentUrl(previewItem.value) : '')
const editPreviewUrl = computed(() => editItemState.value ? currentUrl(editItemState.value) : '')
const dryRun = computed(() => form.value.dryRun)
const generationOutputSummary = computed(() => {
  const job = generationJob.value
  if (!job) return ''
  const targetRows = Array.isArray(job.params.output_targets) ? job.params.output_targets : []
  const fromParams = targetRows
    .map((target) => {
      if (!target || typeof target !== 'object') return ''
      const mode = String((target as Record<string, unknown>).mode || '')
      const aspectRatio = String((target as Record<string, unknown>).aspect_ratio || '')
      return mode && aspectRatio ? aplusTargetLabel(mode, aspectRatio) : ''
    })
    .filter(Boolean)
  if (fromParams.length) return [...new Set(fromParams)].join(' / ')
  const fromItems = job.items
    .map((item) => aplusTargetLabel(item.output_mode || 'detail', item.aspect_ratio))
    .filter(Boolean)
  return [...new Set(fromItems)].join(' / ')
})

watch(() => form.value.platform, (platform) => {
  if (!isAplusAmazon(platform) && form.value.outputSpec.startsWith('amazon_aplus')) {
    form.value.outputSpec = '1:1'
    form.value.advancedTargets = ['web']
  }
})
onActivated(() => { void resumeCurrentAplusJobRefresh() })

function requestDetail(error: any): string {
  const detail = error?.response?.data?.detail
  if (Array.isArray(detail)) return detail.map((item) => item?.msg || String(item)).join('；')
  return detail || error?.message || ''
}

async function showProductInfoEditor() {
  productInfoEditing.value = true
  await nextTick()
  productInfoInput.value?.focus()
}

async function editAiSuggestion() {
  aiSuggestionEditing.value = true
  await nextTick()
  aiSuggestionInput.value?.focus()
}

function clearCopywritingState() {
  aiSuggestion.value = ''
  aiWriteOpen.value = false
  aiSuggestionEditing.value = false
  productInfoEditing.value = false
  form.value.productInfo = ''
}

function removeAsset(id: string) {
  assets.value = assets.value.filter((asset) => asset.id !== id)
  clearCopywritingState()
}

async function filesSelected(event: Event) {
  const input = event.target as HTMLInputElement
  if (uploadLimitReached.value) {
    message.warning('最多上传 3 张商品图')
    input.value = ''
    return
  }
  const selectedFiles = Array.from(input.files ?? [])
  const files = selectedFiles.slice(0, 3 - assets.value.length)
  if (!files.length) return
  clearCopywritingState()
  uploading.value = true
  try {
    for (const file of files) assets.value.push(await uploadAsset(file))
    message.success('商品图上传成功')
  } catch {
    message.error('上传失败，请确认后端已启动且图片格式合法')
  } finally {
    uploading.value = false
    input.value = ''
  }
}

async function useSample() {
  uploading.value = true
  try {
    const blob = await (await fetch('/demo/aplus-outdoor-source.png')).blob()
    const demoAsset = await uploadAsset(new File([blob], 'listingo-demo-outdoor-pack.png', { type: 'image/png' }))
    clearCopywritingState()
    assets.value = [demoAsset]
    message.success('已载入演示商品')
  } catch {
    message.error('载入演示商品失败，请确认后端已启动')
  } finally {
    uploading.value = false
  }
}

function moduleCount(moduleName: string): number {
  return form.value.selectedModules.find((item) => item.name === moduleName)?.count ?? 0
}

function setModuleCount(moduleName: string, count: number) {
  const normalized = Math.max(0, Math.min(APLUS_MODULE_TOTAL_LIMIT, Math.floor(count) || 0))
  const next = form.value.selectedModules.filter((item) => item.name !== moduleName)
  if (normalized > 0) next.push({ name: moduleName, count: normalized })
  form.value.selectedModules = next
}

function toggleModule(moduleName: string) {
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
  if (selectedModuleTotal.value >= APLUS_MODULE_TOTAL_LIMIT) {
    message.warning(`详情页模块最多生成 ${APLUS_MODULE_TOTAL_LIMIT} 张`)
    return
  }
  setModuleCount(moduleName, moduleCount(moduleName) + 1)
}

function decrementModule(moduleName: string) {
  setModuleCount(moduleName, moduleCount(moduleName) - 1)
}

function selectOutputSpec(spec: AplusOutputSpec) {
  if (spec.startsWith('amazon_aplus') && !amazonPlatform.value) {
    message.warning('普通 A+ 和高级 A+ 仅亚马逊平台可用')
    return
  }
  form.value.outputSpec = spec
  if (spec === 'amazon_aplus_advanced' && !form.value.advancedTargets.length) {
    form.value.advancedTargets = ['web']
  }
}

function toggleAdvancedTarget(target: 'web' | 'mobile') {
  const exists = form.value.advancedTargets.includes(target)
  if (exists && form.value.advancedTargets.length === 1) {
    message.warning('高级 A+ 至少选择 Web 或移动端中的一个')
    return
  }
  form.value.advancedTargets = exists
    ? form.value.advancedTargets.filter((item) => item !== target)
    : [...form.value.advancedTargets, target]
}

async function aiWrite() {
  helping.value = true
  try {
    const result = await assistCopywriting({
      asset_ids: assets.value.map((asset) => asset.id),
      platform: form.value.platform,
      market: form.value.market,
      language: form.value.language,
      selling_points: form.value.productInfo,
      dry_run: form.value.dryRun,
    })
    aiSuggestion.value = result.selling_points
    aiSuggestionEditing.value = false
    aiWriteOpen.value = true
  } catch (error: any) {
    message.error(requestDetail(error) || 'AI 转写失败，请检查语言模型配置')
  } finally {
    helping.value = false
  }
}

async function regenerateCopywriting() {
  await aiWrite()
}

function applyAiSuggestion() {
  if (!aiSuggestion.value.trim()) return message.warning('AI 转写内容为空，请重新生成')
  form.value.productInfo = aiSuggestion.value.trim()
  productInfoEditing.value = false
  aiWriteOpen.value = false
  message.success('AI 转写已确认回填')
}

function createOptimisticAplusItem(
  id: string,
  index: number,
  moduleIndex: number,
  moduleName: string,
  outputMode = '',
  aspectRatio = '',
): AplusItem {
  return {
    id,
    index,
    module_index: moduleIndex,
    module_name: moduleName,
    output_mode: outputMode,
    aspect_ratio: aspectRatio,
    image_prompt: '',
    copy_requirements: '',
    prompt_text: '',
    status: 'running',
    provider_id: null,
    source_web_item_id: null,
    error: null,
    current_version_id: null,
    versions: [],
  }
}

function createOptimisticPlanJob(payload: Record<string, unknown>): AplusJob {
  let itemIndex = 0
  const items = orderedAplusModuleSelections(form.value.selectedModules).flatMap((selection) =>
    Array.from({ length: selection.count }, () => {
      itemIndex += 1
      return createOptimisticAplusItem(`optimistic-aplus-plan-item-${itemIndex}`, itemIndex - 1, itemIndex, selection.name)
    }),
  )
  return {
    id: `optimistic-aplus-plan-${Date.now()}`,
    job_type: 'plan',
    status: 'running',
    dry_run: Boolean(payload.dry_run),
    progress: 0,
    count: items.length,
    params: { ...payload, global_plan: '正在自动生成模块方案，完成后会直接开始生成图片。' },
    source_plan_job_id: null,
    error: null,
    created_at: new Date().toISOString(),
    completed_at: null,
    items,
  }
}

function createOptimisticGenerationJob(planItems: AplusItem[], payload: Record<string, unknown>): AplusJob {
  const targets = outputTargets.value
  const items = planItems.flatMap((planItem, planIndex) =>
    targets.map((target, targetIndex) =>
      createOptimisticAplusItem(
        `optimistic-aplus-generation-item-${planIndex}-${targetIndex}`,
        planIndex * targets.length + targetIndex,
        planItem.module_index,
        planItem.module_name,
        target.mode,
        target.aspect_ratio,
      ),
    ),
  )
  return {
    id: `optimistic-aplus-generation-${Date.now()}`,
    job_type: 'generation',
    status: 'running',
    dry_run: Boolean(payload.dry_run),
    progress: 0,
    count: items.length,
    params: payload,
    source_plan_job_id: planJob.value?.id ?? null,
    error: null,
    created_at: new Date().toISOString(),
    completed_at: null,
    items,
  }
}

function preservePendingAplusItems(latest: AplusJob, current: AplusJob | null): AplusJob {
  if (latest.items.length || !current?.items.length) return latest
  const items = current.items.map((item) => {
    if (item.status === 'succeeded') return item
    if (latest.status === 'failed' || latest.status === 'partial_failed') {
      return { ...item, status: 'failed', error: item.error || latest.error }
    }
    if (latest.status === 'cancelled' || latest.status === 'partial_cancelled') {
      return { ...item, status: 'cancelled', error: item.error || latest.error }
    }
    return item
  })
  return { ...latest, items, count: latest.count || current.count }
}

function aplusJobNeedsRefresh(latest: AplusJob): boolean {
  if (!FINAL_APLUS_JOB_STATUSES.has(latest.status)) return true
  if (latest.job_type !== 'generation') return false
  if (!['succeeded', 'partial_failed', 'partial_cancelled'].includes(latest.status)) return false
  if (latest.items.length < latest.count) return true
  return latest.items.some((item) => item.status === 'succeeded' && !currentUrl(item))
}

async function resumeCurrentAplusJobRefresh() {
  if (planning.value || generating.value) return
  if (generationJob.value && aplusJobNeedsRefresh(generationJob.value)) {
    await resumeAplusGenerationRefresh(generationJob.value.id)
    return
  }
  if (planJob.value && aplusJobNeedsRefresh(planJob.value)) {
    await resumeAplusPlanRefresh(planJob.value.id)
  }
}

async function resumeAplusPlanRefresh(jobId: string) {
  if (refreshingAplusJobId.value === jobId || planning.value || generating.value) return
  refreshingAplusJobId.value = jobId
  planning.value = true
  try {
    const latest = await waitForPlan(jobId)
    selectedPlanItemIds.value = latest.items.map((item) => item.id)
  } catch {
    // Keep the last visible state; route activation can retry later.
  } finally {
    if (refreshingAplusJobId.value === jobId) refreshingAplusJobId.value = null
    planning.value = false
  }
}

async function resumeAplusGenerationRefresh(jobId: string) {
  if (refreshingAplusJobId.value === jobId || planning.value || generating.value) return
  refreshingAplusJobId.value = jobId
  generating.value = true
  try {
    const latest = await waitForGeneration(jobId)
    selectedResultIds.value = latest.items.filter((item) => item.status === 'succeeded').map((item) => item.id)
  } catch {
    // Keep the last visible state; route activation can retry later.
  } finally {
    if (refreshingAplusJobId.value === jobId) refreshingAplusJobId.value = null
    generating.value = false
  }
}

async function waitForPlan(jobId: string): Promise<AplusJob> {
  for (let attempt = 0; attempt < 300; attempt += 1) {
    const latest = preservePendingAplusItems(await getAplusPlanJob(jobId), planJob.value)
    planJob.value = latest
    if (!aplusJobNeedsRefresh(latest)) return latest
    await new Promise((resolve) => window.setTimeout(resolve, APLUS_JOB_POLL_INTERVAL_MS))
  }
  throw new Error('A+ 方案等待超时')
}

async function waitForGeneration(jobId: string): Promise<AplusJob> {
  for (let attempt = 0; attempt < 900; attempt += 1) {
    const latest = preservePendingAplusItems(await getAplusGenerationJob(jobId), generationJob.value)
    generationJob.value = latest
    if (!aplusJobNeedsRefresh(latest)) return latest
    await new Promise((resolve) => window.setTimeout(resolve, APLUS_JOB_POLL_INTERVAL_MS))
  }
  throw new Error('A+ 图片生成等待超时')
}

async function generateImages() {
  if (!canPlan.value) {
    message.warning('请先上传商品图，并至少生成 1 张详情页模块和 1 个输出比例')
    return
  }
  const planPayload = buildAplusPlanPayload(assets.value.map((asset) => asset.id), form.value)
  const optimisticPlan = createOptimisticPlanJob(planPayload)
  planJob.value = optimisticPlan
  selectedPlanItemIds.value = optimisticPlan.items.map((item) => item.id)
  generationJob.value = createOptimisticGenerationJob(optimisticPlan.items, {
    output_targets: outputTargets.value,
    dry_run: form.value.dryRun,
  })
  selectedResultIds.value = []
  planning.value = true
  generating.value = true
  cancelling.value = false
  cancelRequested.value = false
  try {
    const createdPlan = preservePendingAplusItems(await createAplusPlanJob(planPayload), planJob.value)
    planJob.value = createdPlan
    if (cancelRequested.value) planJob.value = preservePendingAplusItems(await cancelAplusPlanJob(createdPlan.id), planJob.value)
    const finishedPlan = await waitForPlan(createdPlan.id)
    if (finishedPlan.status !== 'succeeded') {
      if (generationJob.value) {
        const cancelled = finishedPlan.status === 'cancelled' || finishedPlan.status === 'partial_cancelled'
        const error = cancelled ? 'A+ 方案任务已取消' : finishedPlan.error || 'A+ 方案生成失败'
        generationJob.value = {
          ...generationJob.value,
          status: cancelled ? finishedPlan.status : 'failed',
          error,
          items: generationJob.value.items.map((item) => ({ ...item, status: cancelled ? 'cancelled' : 'failed', error: item.error || error })),
        }
      }
      message[finishedPlan.status === 'cancelled' || finishedPlan.status === 'partial_cancelled' ? 'success' : 'error'](finishedPlan.status === 'cancelled' || finishedPlan.status === 'partial_cancelled' ? 'A+ 方案任务已取消' : finishedPlan.error || 'A+ 方案生成失败')
      return
    }
    selectedPlanItemIds.value = finishedPlan.items.map((item) => item.id)
    planning.value = false
    const generationPayload = {
      plan_job_id: finishedPlan.id,
      module_item_ids: selectedPlanItemIds.value,
      output_targets: outputTargets.value,
      dry_run: form.value.dryRun,
    }
    const createdGeneration = preservePendingAplusItems(await createAplusGenerationJob(generationPayload), generationJob.value)
    generationJob.value = createdGeneration
    if (cancelRequested.value) generationJob.value = preservePendingAplusItems(await cancelAplusGenerationJob(createdGeneration.id), generationJob.value)
    const finished = await waitForGeneration(createdGeneration.id)
    selectedResultIds.value = finished.items.filter((item) => item.status === 'succeeded').map((item) => item.id)
    message[finished.status === 'failed' ? 'error' : ['partial_failed', 'partial_cancelled'].includes(finished.status) ? 'warning' : 'success'](
      finished.status === 'succeeded'
        ? 'A+ 图片生成完成'
        : finished.status === 'cancelled'
          ? 'A+ 图片任务已取消'
          : finished.status === 'partial_cancelled'
            ? 'A+ 图片任务已部分取消，已完成结果仍可使用'
            : finished.error || 'A+ 图片生成存在失败项',
    )
  } catch (error: any) {
    if (generationJob.value?.id.startsWith('optimistic-aplus-generation-')) {
      const detail = requestDetail(error) || 'A+ 图片生成失败'
      generationJob.value = {
        ...generationJob.value,
        status: 'failed',
        error: detail,
        items: generationJob.value.items.map((item) => ({ ...item, status: 'failed', error: item.error || detail })),
      }
    }
    message.error(requestDetail(error) || 'A+ 图片生成失败')
  } finally {
    planning.value = false
    generating.value = false
    cancelling.value = false
  }
}

function markAplusJobCancelling(current: AplusJob | null): AplusJob | null {
  if (!current) return current
  return {
    ...current,
    status: 'cancelling',
    items: current.items.map((item) => item.status === 'succeeded' ? item : { ...item, status: 'cancelling' }),
  }
}

async function cancelGeneration() {
  if (cancelling.value || !aplusTaskActive.value) return
  cancelRequested.value = true
  cancelling.value = true
  const activeGeneration = generationJob.value && !FINAL_APLUS_JOB_STATUSES.has(generationJob.value.status) ? generationJob.value : null
  const activePlan = planJob.value && !FINAL_APLUS_JOB_STATUSES.has(planJob.value.status) ? planJob.value : null
  if (activeGeneration?.id.startsWith('optimistic-aplus-generation-') || activePlan?.id.startsWith('optimistic-aplus-plan-')) {
    generationJob.value = markAplusJobCancelling(generationJob.value)
    planJob.value = markAplusJobCancelling(planJob.value)
    return
  }
  try {
    if (activeGeneration) {
      generationJob.value = preservePendingAplusItems(await cancelAplusGenerationJob(activeGeneration.id), generationJob.value)
    } else if (activePlan) {
      planJob.value = preservePendingAplusItems(await cancelAplusPlanJob(activePlan.id), planJob.value)
    }
    message.success('已提交取消请求')
  } catch (error: any) {
    message.error(requestDetail(error) || '取消任务失败')
  } finally {
    if (!planning.value && !generating.value) cancelling.value = false
  }
}

async function openHistoryJob(entry: AplusJob) {
  const latest = entry.job_type === 'generation' ? await getAplusGenerationJob(entry.id) : entry
  generationJob.value = latest.job_type === 'generation' ? latest : null
  selectedResultIds.value = latest.items.filter((item) => item.status === 'succeeded').map((item) => item.id)
  if (latest.source_plan_job_id) {
    try {
      planJob.value = await getAplusPlanJob(latest.source_plan_job_id)
      selectedPlanItemIds.value = planJob.value.items.map((item) => item.id)
    } catch {
      planJob.value = null
      selectedPlanItemIds.value = []
    }
  } else if (latest.job_type === 'plan') {
    planJob.value = latest
    selectedPlanItemIds.value = latest.items.map((item) => item.id)
  }
  if (generationJob.value && aplusJobNeedsRefresh(generationJob.value)) void resumeAplusGenerationRefresh(generationJob.value.id)
  else if (planJob.value && aplusJobNeedsRefresh(planJob.value)) void resumeAplusPlanRefresh(planJob.value.id)
}

function currentUrl(item: AplusItem): string | undefined {
  return item.versions.find((version) => version.id === item.current_version_id)?.url ?? item.versions.at(-1)?.url
}

function aplusPlaceholderLabel(item: AplusItem): string {
  if (item.status === 'failed') return '生成失败'
  if (item.status === 'cancelled') return '已取消'
  if (item.status === 'cancelling') return '取消中'
  if (item.status === 'succeeded') return '结果同步中'
  return '生成中'
}

function aplusPlaceholderSpinning(item: AplusItem): boolean {
  return ['queued', 'running', 'succeeded'].includes(item.status)
}

function scriptMarkdown(item: AplusItem): string {
  const sections = [
    `### ${item.module_index || item.index + 1}. ${item.module_name}`,
    `- 输出规格：${aplusTargetLabel(item.output_mode, item.aspect_ratio)}`,
  ]
  if (item.image_prompt.trim()) sections.push(`### 生图脚本\n${item.image_prompt.trim()}`)
  if (item.copy_requirements.trim()) sections.push(`### 文案要求\n${item.copy_requirements.trim()}`)
  if (item.prompt_text.trim()) sections.push(`### 完整 Prompt\n${item.prompt_text.trim()}`)
  if (item.error?.trim()) sections.push(`### 错误信息\n${item.error.trim()}`)
  return sections.join('\n\n')
}

function hasScript(item: AplusItem): boolean {
  return Boolean(item.image_prompt.trim() || item.copy_requirements.trim() || item.prompt_text.trim() || item.error?.trim())
}

function openPreview(item: AplusItem) {
  if (!currentUrl(item)) return
  previewItem.value = item
}

function openEdit(item: AplusItem) {
  if (item.status !== 'succeeded' || !currentUrl(item)) return
  editItemState.value = item
}

async function submitEdit() {
  if (!editItemState.value || !generationJob.value) return
  try {
    const version = await editAplusItem(editItemState.value.id, editInstruction.value)
    generationJob.value = await getAplusGenerationJob(generationJob.value.id)
    editItemState.value = generationJob.value.items.find((item) => item.id === editItemState.value?.id) ?? null
    if (editItemState.value && !editItemState.value.current_version_id) editItemState.value.current_version_id = version.id
    message.success('已创建新的 A+ 子版本')
  } catch (error: any) {
    message.error(requestDetail(error) || 'A+ 二次编辑失败')
  } finally {
    editItemState.value = null
  }
}

function toggleResult(id: string) {
  const item = generationJob.value?.items.find((entry) => entry.id === id)
  if (!item || item.status !== 'succeeded') return
  selectedResultIds.value = selectedResultIds.value.includes(id)
    ? selectedResultIds.value.filter((item) => item !== id)
    : [...selectedResultIds.value, id]
}

function downloadResults() {
  if (!generationJob.value || !selectedResultIds.value.length) {
    message.warning('请至少选择一张成功的 A+ 结果')
    return
  }
  const successfulIds = new Set(generationJob.value.items.filter((item) => item.status === 'succeeded').map((item) => item.id))
  const itemIds = selectedResultIds.value.filter((id) => successfulIds.has(id))
  if (!itemIds.length) return message.warning('请至少选择一张成功的 A+ 结果')
  window.open(aplusDownloadUrl(generationJob.value.id, itemIds), '_blank')
}

function startNewTask() {
  assets.value = []
  uploading.value = false
  helping.value = false
  planning.value = false
  generating.value = false
  cancelling.value = false
  cancelRequested.value = false
  form.value = createDefaultAplusForm()
  planJob.value = null
  generationJob.value = null
  selectedPlanItemIds.value = []
  selectedResultIds.value = []
  previewItem.value = null
  scriptItem.value = null
  editItemState.value = null
  aiSuggestion.value = ''
  aiWriteOpen.value = false
  productInfoEditing.value = false
  aiSuggestionEditing.value = false
}

defineExpose({ openHistoryJob, startNewTask, dryRun })
</script>

<template>
  <aside class="config-panel aplus-config-panel">
    <section class="form-section">
      <div class="section-title"><span>1</span><strong>上传商品图</strong><em>最多 3 张</em></div>
      <label class="upload-zone" :class="{ disabled: uploadLimitReached || uploading }">
        <input type="file" accept="image/png,image/jpeg,image/webp" multiple :disabled="uploadLimitReached || uploading" @change="filesSelected" />
        <CloudUploadOutlined />
        <b>{{ uploading ? '上传中' : uploadLimitReached ? '最多上传 3 张' : '点击上传商品图' }}</b>
        <small>{{ uploadLimitReached ? '删除已有图片后可继续上传' : '建议上传主图、细节图和场景图' }}</small>
      </label>
      <div v-if="assets.length" class="uploaded-row">
        <div v-for="asset in assets" :key="asset.id">
          <img :src="asset.url" :alt="asset.original_name" />
          <button class="remove-uploaded-asset" type="button" @click="removeAsset(asset.id)"><CloseOutlined /></button>
        </div>
      </div>
      <button v-else class="sample-button" type="button" @click="useSample">使用 Listingo 演示商品</button>
    </section>

    <section class="form-section">
      <div class="section-title"><span>2</span><strong>生成设置</strong></div>
      <div class="field-grid">
        <label>目标平台<select v-model="form.platform"><option v-for="value in aplusPlatformOptions" :key="value" :value="value">{{ value }}</option></select></label>
        <label>目标市场<select v-model="form.market"><option v-for="value in aplusMarketOptions" :key="value" :value="value">{{ value }}</option></select></label>
        <label>图片语言<select v-model="form.language"><option v-for="value in aplusLanguageOptions" :key="value" :value="value">{{ value }}</option></select></label>
      </div>
    </section>

    <section class="form-section">
      <div class="section-title"><span>3</span><strong>商品卖点与要求</strong><button :disabled="helping" @click="aiWrite"><ThunderboltOutlined />{{ helping ? '转写中...' : 'AI 转写' }}</button></div>
      <div class="markdown-input-frame aplus-product-info-markdown-frame">
        <div v-if="form.productInfo.trim() && !productInfoEditing" class="markdown-preview main-copy-preview" role="button" tabindex="0" aria-label="编辑商品卖点与要求" @click="showProductInfoEditor" @keydown.enter.prevent="showProductInfoEditor" @keydown.space.prevent="showProductInfoEditor" v-html="renderMarkdown(form.productInfo)"></div>
        <textarea v-else ref="productInfoInput" v-model="form.productInfo" class="aplus-product-info selling-points-input" rows="6" :placeholder="productInfoPlaceholder" @focus="productInfoEditing = true" @blur="productInfoEditing = false" />
      </div>
      <Teleport to="body">
        <div v-if="aiWriteOpen" class="ai-write-popover" role="dialog" aria-label="AI 转写建议">
          <header><strong><ThunderboltOutlined />AI 转写建议</strong><button type="button" aria-label="关闭 AI 转写建议" @click="aiWriteOpen = false"><CloseOutlined /></button></header>
          <div class="markdown-input-frame ai-suggestion-markdown-frame">
            <button v-if="aiSuggestion.trim() && !aiSuggestionEditing" class="markdown-preview" type="button" aria-label="编辑 AI 转写候选内容" @click="editAiSuggestion" v-html="renderMarkdown(aiSuggestion)"></button>
            <textarea v-else ref="aiSuggestionInput" v-model="aiSuggestion" rows="8" aria-label="AI 转写候选内容" @blur="aiSuggestionEditing = false" />
          </div>
          <p>建议内容可直接修改；确认前不会覆盖原输入。</p>
          <footer><button type="button" :disabled="helping" @click="regenerateCopywriting"><ThunderboltOutlined />{{ helping ? '生成中...' : '重新转写' }}</button><button type="button" class="apply" @click="applyAiSuggestion">确认回填</button></footer>
        </div>
      </Teleport>
    </section>

    <section class="form-section">
      <div class="section-title"><span>4</span><strong>输出规格</strong><em>{{ outputTargets.length }} 项</em></div>
      <div class="aplus-output-grid">
        <button v-for="spec in availableOutputSpecs" :key="spec.value" type="button" :class="{ active: form.outputSpec === spec.value }" @click="selectOutputSpec(spec.value)">
          <i><CheckOutlined v-if="form.outputSpec === spec.value" /></i>
          <span><b>{{ spec.label }}</b><small>{{ spec.description }}</small></span>
        </button>
      </div>
      <div v-if="amazonPlatform && form.outputSpec === 'amazon_aplus_advanced'" class="aplus-advanced-targets">
        <b>高级 A+ 端</b>
        <button type="button" :class="{ active: form.advancedTargets.includes('web') }" @click="toggleAdvancedTarget('web')"><CheckOutlined v-if="form.advancedTargets.includes('web')" />Web · 1464:600</button>
        <button type="button" :class="{ active: form.advancedTargets.includes('mobile') }" @click="toggleAdvancedTarget('mobile')"><CheckOutlined v-if="form.advancedTargets.includes('mobile')" />移动端 · 600:450</button>
      </div>
      <p v-else-if="!amazonPlatform" class="aplus-rule-note">普通 A+ 和高级 A+ 仅亚马逊平台可用。</p>
    </section>

    <section class="form-section">
      <div class="section-title"><span>5</span><strong>详情页模块</strong><em>{{ selectedModuleTotal }}/{{ APLUS_MODULE_TOTAL_LIMIT }} 张</em></div>
      <div class="aplus-module-list">
        <article v-for="module in aplusModules" :key="module.name" class="aplus-module-option" :class="{ active: moduleCount(module.name) > 0 }">
          <button class="aplus-module-main" type="button" @click="toggleModule(module.name)">
            <span><b>{{ module.name }}</b><small>{{ module.description }}</small></span>
          </button>
          <div class="aplus-module-stepper" :aria-label="`${module.name} 生成张数`">
            <button type="button" :disabled="moduleCount(module.name) <= 0" :aria-label="`减少 ${module.name}`" @click.stop="decrementModule(module.name)"><MinusOutlined /></button>
            <strong>{{ moduleCount(module.name) }}</strong>
            <button type="button" :disabled="selectedModuleTotal >= APLUS_MODULE_TOTAL_LIMIT" :aria-label="`增加 ${module.name}`" @click.stop="incrementModule(module.name)"><PlusOutlined /></button>
          </div>
        </article>
      </div>
      <label class="switch-row"><span><b>安全演示模式</b><small>本地模拟资产，不调用语言或图片模型</small></span><input v-model="form.dryRun" type="checkbox" /></label>
    </section>

    <div class="panel-footer aplus-actions">
      <button v-if="aplusTaskActive" class="secondary-action cancel-action" :disabled="cancelling" @click="cancelGeneration"><CloseOutlined />{{ cancelling ? '取消中' : '取消任务' }}</button>
      <button class="generate-button" :disabled="planning || generating || !canPlan" @click="generateImages"><RocketOutlined />{{ planning ? '生成方案中' : generating ? '生成图片中' : `生成图片 ${plannedResultCount} 张` }}</button>
    </div>
  </aside>

  <main class="preview-canvas aplus-preview-canvas">
    <div v-if="generationJob?.items.length" class="aplus-workspace">
      <section class="aplus-results">
        <header>
          <div><strong>{{ generationJob.status === 'succeeded' ? 'A+ 已生成' : generationJob.status === 'running' ? 'A+ 正在生成' : 'A+ 生成结果' }}</strong><small>{{ generationJob.items.length }} 张 · {{ generationJob.dry_run ? 'Dryrun' : 'Live' }}<template v-if="generationOutputSummary"> · {{ generationOutputSummary }}</template></small></div>
          <div class="aplus-result-actions">
            <button v-if="aplusTaskActive" class="secondary-action cancel-action" :disabled="cancelling" @click="cancelGeneration"><CloseOutlined />{{ cancelling ? '取消中' : '取消任务' }}</button>
            <button class="secondary-action" @click="selectedResultIds = generationJob.items.filter((item) => item.status === 'succeeded').map((item) => item.id)">全选成功项</button>
            <button class="download-button" :disabled="!selectedResultIds.length" @click="downloadResults"><DownloadOutlined />下载选中 ({{ selectedResultIds.length }})</button>
          </div>
        </header>
        <div class="aplus-result-grid">
          <article v-for="item in generationJob.items" :key="item.id" class="aplus-result-card" :class="{ selected: selectedResultIds.includes(item.id), failed: ['failed', 'cancelled'].includes(item.status) }">
            <button class="select-dot" type="button" :disabled="item.status !== 'succeeded'" @click="toggleResult(item.id)"><CheckOutlined v-if="selectedResultIds.includes(item.id)" /></button>
            <img v-if="currentUrl(item)" :src="currentUrl(item)" :alt="item.module_name" />
            <div v-else class="pending-image" :class="{ terminal: !aplusPlaceholderSpinning(item) }">
              <LoadingOutlined v-if="aplusPlaceholderSpinning(item)" spin />
              <span>{{ aplusPlaceholderLabel(item) }}</span>
            </div>
            <footer>
              <div class="aplus-result-meta">
                <b>{{ item.module_name }}</b>
                <span>第 {{ item.index + 1 }} 张 · {{ aplusTargetLabel(item.output_mode, item.aspect_ratio) }}</span>
                <small v-if="item.error">{{ item.error }}</small>
              </div>
              <div class="aplus-card-actions">
                <button type="button" :disabled="!currentUrl(item)" @click="openPreview(item)"><EyeOutlined />预览</button>
                <button type="button" :disabled="item.status !== 'succeeded'" @click="openEdit(item)"><EditOutlined />编辑</button>
                <button type="button" :disabled="!hasScript(item)" @click="scriptItem = item"><PlayCircleOutlined />脚本</button>
              </div>
            </footer>
          </article>
        </div>
      </section>
    </div>

    <div v-else class="empty-preview aplus-empty-preview">
      <section class="aplus-empty-stage aplus-showcase-stage" aria-label="A+ 详情页五卡展示示例">
        <header class="aplus-showcase-head">
          <span>LISTINGO A+ KIT</span>
          <strong>用商品图生成可上架的详情页模块</strong>
        </header>
        <div class="aplus-showcase-gallery">
          <article v-for="card in aplusShowcaseCards" :key="card.title" class="aplus-showcase-card" tabindex="0">
            <img :src="card.image" :alt="card.title" />
            <span class="aplus-showcase-badge">{{ card.eyebrow }}</span>
            <div class="aplus-showcase-copy">
              <b>{{ card.title }}</b>
              <p>{{ card.description }}</p>
            </div>
          </article>
        </div>
      </section>
    </div>
  </main>

  <a-modal :open="!!previewItem" title="A+ 图片预览" :footer="null" width="760" @update:open="(open) => { if (!open) previewItem = null }">
    <img v-if="previewUrl" class="modal-preview aplus-modal-preview" :src="previewUrl" alt="A+ 图片预览" />
    <div v-if="previewItem?.versions.length" class="version-strip">
      <button v-for="version in previewItem.versions" :key="version.id" @click="previewItem && (previewItem.current_version_id = version.id)">V{{ version.version_no }} · {{ version.instruction }}</button>
    </div>
  </a-modal>

  <a-modal :open="!!editItemState" title="A+ 二次编辑" ok-text="生成新版本" cancel-text="取消" @ok="submitEdit" @update:open="(open) => { if (!open) editItemState = null }">
    <div class="edit-dialog">
      <img v-if="editPreviewUrl" :src="editPreviewUrl" alt="当前 A+ 版本" />
      <label>修改要求<textarea v-model="editInstruction" rows="5" /></label>
    </div>
  </a-modal>

  <a-modal :open="!!scriptItem" title="A+ 图片脚本" :footer="null" width="760" @update:open="(open) => { if (!open) scriptItem = null }">
    <div v-if="scriptItem" class="aplus-script-preview" v-html="renderMarkdown(scriptMarkdown(scriptItem))" />
  </a-modal>
</template>
