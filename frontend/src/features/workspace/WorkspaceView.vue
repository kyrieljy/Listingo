<script setup lang="ts">
import { computed, nextTick, onMounted, ref, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { Modal, message } from 'ant-design-vue'
import {
  AppstoreOutlined, BgColorsOutlined, CheckOutlined, ClockCircleOutlined, CloudUploadOutlined,
  CloseOutlined, DownOutlined, DownloadOutlined, HistoryOutlined, MenuFoldOutlined, PlayCircleOutlined, PlusOutlined, RocketOutlined,
  SettingOutlined, ThunderboltOutlined, VideoCameraOutlined,
} from '@ant-design/icons-vue'
import BrandLogo from '../../components/BrandLogo.vue'
import {
  assistCopywriting, cancelJob, createJob, editItem, generationDownloadUrl, getJob, listAplusGenerationJobs, listJobs, listVideoJobs, retryFailedItems, uploadAsset,
  type AplusJob, type Asset, type DownloadFormat, type Job, type JobItem, type VideoJob,
} from '../../api/client'
import APlusPhasePanel from './APlusPhasePanel.vue'
import DemoPhasePanel from './DemoPhasePanel.vue'
import ResultGrid from './ResultGrid.vue'
import VideoPhasePanel from './VideoPhasePanel.vue'
import {
  buildGenerationPayload, createDefaultWorkspaceForm, customTotal, customTypeDefinitions,
  generationCount, generationFailureMessage, languageOptions, marketOptions, phaseDefinitions, platformOptions, renderMarkdown, ratioOptions, ratioValues,
  type CustomCountKey, type PhaseKey,
} from './workspace-model'

const route = useRoute(); const router = useRouter()
const disabledPhaseKeys = new Set<PhaseKey>(['agent'])
function isPhaseDisabled(key: PhaseKey): boolean { return disabledPhaseKeys.has(key) }
const phase = computed<PhaseKey>(() => phaseDefinitions.some((item) => item.key === route.params.phase && !isPhaseDisabled(item.key)) ? route.params.phase as PhaseKey : 'suite')
const mobileOpen = ref(false); const uploading = ref(false); const generating = ref(false); const helping = ref(false); const cancelling = ref(false); const cancelRequested = ref(false)
type HistoryEntry = Job | AplusJob | VideoJob
type HistoryPanelRef<T> = { openHistoryJob: (entry: T) => Promise<void>; startNewTask: () => void; dryRun?: boolean }
const assets = ref<Asset[]>([]); const job = ref<Job | null>(null); const history = ref<HistoryEntry[]>([])
const historyOpen = ref(false); const previewOpen = ref(false); const scriptOpen = ref(false); const editOpen = ref(false); const confirmOpen = ref(false); const activeItem = ref<JobItem | null>(null)
const downloadMenuOpen = ref(false)
const aplusPanel = ref<HistoryPanelRef<AplusJob> | null>(null); const videoPanel = ref<HistoryPanelRef<VideoJob> | null>(null)
const selected = ref<string[]>([]); const editInstruction = ref('背景改为更明亮的淡紫色，保持产品外观不变')
const aiSuggestion = ref(''); const aiWriteOpen = ref(false); const preferenceOpen = ref(false); const sellingPointsEditing = ref(false)
const aiSuggestionEditing = ref(false)
const sellingPointsInput = ref<HTMLTextAreaElement | null>(null); const aiSuggestionInput = ref<HTMLTextAreaElement | null>(null)
const form = ref(createDefaultWorkspaceForm())
const IMAGE_JOB_POLL_INTERVAL_MS = 500
const FINAL_JOB_STATUSES = new Set(['succeeded', 'partial_failed', 'failed', 'cancelled', 'partial_cancelled'])
const refreshingSuiteJobId = ref<string | null>(null)
const sellingPointsPlaceholder = `建议包含以下信息，帮助生成更精准：
1. 商品名称
2. 核心卖点
3. 适用人群
4. 期望场景
5. 具体参数`
const demoImages = ['/demo/tumbler-feature.png','/demo/tumbler-lifestyle.png','/demo/tumbler-commute.png','/demo/tumbler-source.png']
const modelPreferenceOptions = [
  { key: 'fidelity' as const, label: '商品保持优先', description: '优先保持商品外观、颜色、结构和标签一致' },
  { key: 'layout' as const, label: '视觉排版优先', description: '强化画面排版与文字呈现，商品保持度略低' },
]
const currentPreview = computed(() => activeItem.value?.versions.find((v) => v.id === activeItem.value?.current_version_id)?.url ?? activeItem.value?.versions.at(-1)?.url)
const count = computed(() => generationCount(form.value))
const uploadLimitReached = computed(() => assets.value.length >= 3)
const customValid = computed(() => form.value.mode === 'smart' || (count.value >= 7 && count.value <= 12))
const inputValid = computed(() => form.value.sellingPoints.trim().length > 0)
const layoutPreferred = computed(() => form.value.modelPreference === 'layout')
const selectedModelPreference = computed(() => modelPreferenceOptions.find((option) => option.key === form.value.modelPreference) ?? modelPreferenceOptions[0])
const currentFailureMessage = computed(() => generationFailureMessage(job.value))
const suiteJobActive = computed(() => Boolean(job.value && !FINAL_JOB_STATUSES.has(job.value.status)))
const activeItemScript = computed(() => activeItem.value ? scriptMarkdown(activeItem.value) : '')
const currentDryRun = computed(() => phase.value === 'aplus' ? (aplusPanel.value?.dryRun ?? form.value.dryRun) : phase.value === 'video' ? (videoPanel.value?.dryRun ?? form.value.dryRun) : form.value.dryRun)
const historyTitle = computed(() => phase.value === 'video' ? '视频历史' : phase.value === 'aplus' ? 'A+ 详情历史' : '套图历史')
const historyEmptyText = computed(() => phase.value === 'video' ? '暂无视频历史任务' : phase.value === 'aplus' ? '暂无 A+ 详情历史任务' : '暂无套图历史任务')

watch(phase, () => {
  mobileOpen.value = false
  preferenceOpen.value = false
  if (phase.value === 'suite') void resumeCurrentSuiteJobRefresh()
})
onMounted(async () => { await loadPhaseHistory() })

function requestDetail(error: any): string {
  const detail = error?.response?.data?.detail
  if (Array.isArray(detail)) return detail.map((item) => item?.msg || String(item)).join('；')
  return detail || error?.message || ''
}
function handleRequestError(error: any, fallback: string) {
  const detail = requestDetail(error) || fallback
  if (error?.response?.status === 422 && detail.includes('安全拦截')) {
    Modal.error({ title: '内容安全拦截', content: detail })
    return
  }
  message.error(detail || fallback)
}
function createOptimisticJob(payload: Record<string, unknown>): Job {
  const total = Number(payload.count || count.value)
  return {
    id: `optimistic-${Date.now()}`,
    status: 'running',
    dry_run: Boolean(payload.dry_run),
    progress: 0,
    count: total,
    params: payload,
    error: null,
    created_at: new Date().toISOString(),
    items: Array.from({ length: total }, (_, index) => ({
      id: `optimistic-${index}`,
      index,
      image_type: '',
      prompt_text: '',
      status: 'running',
      error: null,
      current_version_id: null,
      versions: [],
    })),
  }
}

function preservePendingJobItems(latest: Job): Job {
  if (latest.items.length || !job.value?.items.length) return latest
  const items = job.value.items.map((item) => {
    if (item.status === 'succeeded') return item
    if (latest.status === 'failed' || latest.status === 'partial_failed') {
      return { ...item, status: 'failed', error: item.error || latest.error }
    }
    if (latest.status === 'cancelled' || latest.status === 'partial_cancelled') {
      return { ...item, status: 'cancelled', error: item.error || latest.error }
    }
    return item
  })
  return { ...latest, items, count: latest.count || job.value.count }
}

function itemResultUrl(item: JobItem): string | undefined {
  return item.versions.find((version) => version.id === item.current_version_id)?.url ?? item.versions.at(-1)?.url
}

function suiteJobNeedsRefresh(latest: Job): boolean {
  if (!FINAL_JOB_STATUSES.has(latest.status)) return true
  if (!['succeeded', 'partial_failed', 'partial_cancelled'].includes(latest.status)) return false
  if (latest.items.length < latest.count) return true
  return latest.items.some((item) => item.status === 'succeeded' && !itemResultUrl(item))
}

async function resumeCurrentSuiteJobRefresh() {
  if (!job.value || !suiteJobNeedsRefresh(job.value) || generating.value) return
  await resumeSuiteJobRefresh(job.value.id)
}

async function resumeSuiteJobRefresh(jobId: string) {
  if (refreshingSuiteJobId.value === jobId || generating.value) return
  refreshingSuiteJobId.value = jobId
  generating.value = true
  try {
    const latest = await waitForJob(jobId)
    selected.value = latest.items.filter((item) => item.status === 'succeeded').map((item) => item.id)
    if (FINAL_JOB_STATUSES.has(latest.status)) history.value = await listJobs()
  } catch {
    // Keep the last visible state; the next history open or route activation can retry.
  } finally {
    if (refreshingSuiteJobId.value === jobId) refreshingSuiteJobId.value = null
    generating.value = false
  }
}

function navigate(key: PhaseKey) {
  if (isPhaseDisabled(key)) return
  router.push(`/app/${key}`)
}
async function loadPhaseHistory() {
  try {
    if (phase.value === 'video') history.value = await listVideoJobs()
    else if (phase.value === 'aplus') history.value = await listAplusGenerationJobs()
    else if (phase.value === 'suite') history.value = await listJobs()
    else history.value = []
  } catch {
    history.value = []
  }
}
async function openHistoryDrawer() {
  historyOpen.value = true
  await loadPhaseHistory()
}
function selectModelPreference(key: (typeof modelPreferenceOptions)[number]['key']) { form.value.modelPreference = key; preferenceOpen.value = false }
async function showSellingPointsEditor() { sellingPointsEditing.value = true; await nextTick(); sellingPointsInput.value?.focus() }
async function editAiSuggestion() { aiSuggestionEditing.value = true; await nextTick(); aiSuggestionInput.value?.focus() }
function clearCopywritingState() {
  aiSuggestion.value = ''
  aiWriteOpen.value = false
  aiSuggestionEditing.value = false
  sellingPointsEditing.value = false
  form.value.sellingPoints = ''
}
function removeAsset(id: string) {
  assets.value = assets.value.filter((asset) => asset.id !== id)
  clearCopywritingState()
}
function resetSuiteTask() {
  assets.value = []; job.value = null; selected.value = []; activeItem.value = null
  previewOpen.value = false; editOpen.value = false; confirmOpen.value = false; aiWriteOpen.value = false; aiSuggestion.value = ''; historyOpen.value = false; mobileOpen.value = false; preferenceOpen.value = false; sellingPointsEditing.value = false; aiSuggestionEditing.value = false
  form.value = createDefaultWorkspaceForm()
}
function startNewTask() {
  historyOpen.value = false
  mobileOpen.value = false
  preferenceOpen.value = false
  if (phase.value === 'aplus') {
    aplusPanel.value?.startNewTask()
    message.success('已新建 A+ 空白任务')
    return
  }
  if (phase.value === 'video') {
    videoPanel.value?.startNewTask()
    message.success('已新建视频空白任务')
    return
  }
  resetSuiteTask()
  if (phase.value !== 'suite') navigate('suite')
  message.success('已新建套图空白任务')
}
async function filesSelected(event: Event) {
  const input = event.target as HTMLInputElement
  if (uploadLimitReached.value) {
    message.warning('最多上传 3 张商品图，请先删除已有图片')
    input.value = ''
    return
  }
  const selectedFiles = Array.from(input.files ?? [])
  const remaining = 3 - assets.value.length
  const files = selectedFiles.slice(0, remaining)
  if (selectedFiles.length > remaining) message.warning(`最多上传 3 张商品图，本次只添加 ${remaining} 张`)
  if (!files.length) return
  clearCopywritingState()
  uploading.value = true
  try { for (const file of files) assets.value.push(await uploadAsset(file)); message.success('商品图上传成功') }
  catch (error) { message.error('上传失败，请确认后端已启动且图片格式合法') }
  finally { uploading.value = false; input.value = '' }
}
async function useSample() {
  uploading.value = true
  try { const blob = await (await fetch('/demo/tumbler-source.png')).blob(); const demoAsset = await uploadAsset(new File([blob], 'listingo-demo-tumbler.png', { type: 'image/png' })); clearCopywritingState(); assets.value = [demoAsset]; message.success('已载入演示商品') }
  catch { message.error('载入演示商品失败，请确认后端已启动') } finally { uploading.value = false }
}
async function aiWrite() {
  helping.value = true
  try {
    const result = await assistCopywriting({ asset_ids: assets.value.map((asset) => asset.id), platform: form.value.platform, market: form.value.market, language: form.value.language, selling_points: form.value.sellingPoints, dry_run: form.value.dryRun })
    aiSuggestion.value = result.selling_points; aiSuggestionEditing.value = false; aiWriteOpen.value = true
  } catch (error: any) { handleRequestError(error, 'AI 帮写失败，请检查语言模型配置') }
  finally { helping.value = false }
}
async function regenerateCopywriting() { await aiWrite() }
function applyAiSuggestion() {
  if (!aiSuggestion.value.trim()) return message.warning('AI 建议为空，请重新帮写')
  form.value.sellingPoints = aiSuggestion.value.trim(); sellingPointsEditing.value = false; aiWriteOpen.value = false; message.success('AI 建议已确认回填')
}
function adjustCustomCount(key: CustomCountKey, delta: number) {
  const current = form.value.customCounts[key]
  const total = customTotal(form.value.customCounts)
  if (delta > 0 && (current >= 4 || total >= 12)) return
  if (delta < 0 && (current <= 0 || total <= 7)) return
  form.value.customCounts[key] = current + delta
}
async function waitForJob(jobId: string): Promise<Job> {
  for (let attempt = 0; attempt < 900; attempt += 1) {
    const latest = preservePendingJobItems(await getJob(jobId)); job.value = latest
    if (!suiteJobNeedsRefresh(latest)) return latest
    await new Promise((resolve) => window.setTimeout(resolve, IMAGE_JOB_POLL_INTERVAL_MS))
  }
  throw new Error('任务等待超时')
}
function generate() {
  if (!assets.value.length) { message.warning('请先上传商品图或载入演示商品'); return }
  if (!inputValid.value) { message.warning('请填写商品卖点与要求'); return }
  if (!customValid.value) { message.warning('套图总数需为 7–12 张'); return }
  confirmOpen.value = true
}
async function runConfirmedGeneration() {
  confirmOpen.value = false
  generating.value = true
  cancelling.value = false
  cancelRequested.value = false
  try {
    const payload = buildGenerationPayload(assets.value.map((a) => a.id), form.value.sellingPoints, form.value)
    job.value = createOptimisticJob(payload)
    selected.value = []
    const created = preservePendingJobItems(await createJob(payload)); job.value = created
    if (cancelRequested.value) job.value = preservePendingJobItems(await cancelJob(created.id))
    const finished = await waitForJob(created.id); job.value = finished
    selected.value = finished.items.filter((i) => i.status === 'succeeded').map((i) => i.id); history.value = await listJobs()
    const failureMessage = generationFailureMessage(finished)
    message[finished.status === 'failed' ? 'error' : ['partial_failed', 'partial_cancelled'].includes(finished.status) ? 'warning' : 'success'](
      finished.status === 'succeeded'
        ? '套图任务完成'
        : finished.status === 'cancelled'
          ? '套图任务已取消'
          : finished.status === 'partial_cancelled'
            ? '套图任务已部分取消，已完成结果仍可使用'
            : finished.status === 'partial_failed'
              ? (failureMessage ? `部分图片生成失败：${failureMessage}` : '部分图片生成失败，可单独重试')
              : (failureMessage ? `套图任务失败：${failureMessage}` : '套图任务失败'),
    )
  } catch (error: any) {
    if (job.value?.id.startsWith('optimistic-')) job.value = null
    handleRequestError(error, '任务创建失败，请检查配置与后端日志')
  } finally { generating.value = false; cancelling.value = false }
}
async function retryFailed() {
  if (!job.value) return
  generating.value = true
  try {
    await retryFailedItems(job.value.id)
    const finished = await waitForJob(job.value.id)
    selected.value = finished.items.filter((item) => item.status === 'succeeded').map((item) => item.id)
    history.value = await listJobs()
    message[finished.status === 'succeeded' ? 'success' : 'warning'](finished.status === 'succeeded' ? '失败图片已全部重试成功' : '重试完成，仍有图片生成失败')
  } catch (error: any) { message.error(error.response?.data?.detail || '失败项重试失败') }
  finally { generating.value = false }
}
function markJobCancelling(current: Job | null): Job | null {
  if (!current) return current
  return {
    ...current,
    status: 'cancelling',
    items: current.items.map((item) => item.status === 'succeeded' ? item : { ...item, status: 'cancelling' }),
  }
}
async function cancelGeneration() {
  if (!job.value || cancelling.value || FINAL_JOB_STATUSES.has(job.value.status)) return
  cancelRequested.value = true
  cancelling.value = true
  if (job.value.id.startsWith('optimistic-')) {
    job.value = markJobCancelling(job.value)
    return
  }
  try {
    job.value = preservePendingJobItems(await cancelJob(job.value.id))
    message.success('已提交取消请求')
  } catch (error: any) {
    message.error(error.response?.data?.detail || '取消任务失败')
  } finally {
    if (!generating.value) cancelling.value = false
  }
}
function toggleSelected(id: string) {
  const item = job.value?.items.find((entry) => entry.id === id)
  if (!item || item.status !== 'succeeded') return
  selected.value = selected.value.includes(id) ? selected.value.filter((item) => item !== id) : [...selected.value, id]
}
function preview(item: JobItem) { activeItem.value = item; previewOpen.value = true }
function openEdit(item: JobItem) { activeItem.value = item; editOpen.value = true }
function openScript(item: JobItem) { activeItem.value = item; scriptOpen.value = true }
function scriptMarkdown(item: JobItem): string {
  let rawPrompt = item.prompt_text?.trim() || ''
  try {
    const parsed = JSON.parse(rawPrompt || '{}')
    const sections: string[] = []
    if (parsed.image_type) sections.push(`**图片类型**\n${String(parsed.image_type)}`)
    if (parsed.image_requirements) sections.push(`**图片要求**\n${String(parsed.image_requirements)}`)
    if (parsed.copywriting_requirements) sections.push(`**文案要求**\n${String(parsed.copywriting_requirements)}`)
    if (rawPrompt) sections.push(`**Raw Prompt**\n${rawPrompt}`)
    if (item.error) sections.push(`**错误信息**\n${item.error}`)
    return sections.join('\n\n') || '暂无脚本内容'
  } catch {
    return [`**Raw Prompt**\n${rawPrompt || '暂无脚本内容'}`, item.error ? `**错误信息**\n${item.error}` : ''].filter(Boolean).join('\n\n')
  }
}
async function submitEdit() {
  if (!activeItem.value || !job.value) return
  try { await editItem(activeItem.value.id, editInstruction.value); job.value = await getJob(job.value.id); activeItem.value = job.value.items.find((item) => item.id === activeItem.value?.id) ?? null; editOpen.value = false; message.success('已创建新的子版本') } catch (error: any) { handleRequestError(error, '二次编辑失败') }
}
function download(format: DownloadFormat = 'zip') {
  downloadMenuOpen.value = false
  if (!job.value || !selected.value.length) return message.warning('请至少选择一张成功结果')
  if (job.value.id.startsWith('optimistic-')) return message.warning('任务仍在生成中，请稍后下载')
  const successfulIds = new Set(job.value.items.filter((item) => item.status === 'succeeded').map((item) => item.id))
  const itemIds = selected.value.filter((id) => successfulIds.has(id))
  if (!itemIds.length) return message.warning('请选择至少一张成功结果')
  window.open(generationDownloadUrl(job.value.id, itemIds, format), '_blank')
}
function historyThumbnail(entry: HistoryEntry): string {
  const url = entry.items[0]?.versions.at(-1)?.url || entry.items[0]?.versions[0]?.url || ''
  if (phase.value === 'video') return '/demo/video-skincare-result.png'
  if (url) return url
  return phase.value === 'aplus' ? '/demo/video-backpack-showcase-01.png' : '/demo/tumbler-source.png'
}
function historySummary(entry: HistoryEntry): string {
  if (phase.value === 'video') return `${String(entry.params.platform || '视频')} · ${entry.count} 条`
  if (phase.value === 'aplus') return `${String(entry.params.platform || 'A+ 详情')} · ${entry.items.length || entry.count} 张`
  return `${String(entry.params.platform || '商品套图')} · ${entry.count} 张`
}
async function openHistoryJob(entry: HistoryEntry) {
  if (phase.value === 'video') await videoPanel.value?.openHistoryJob(entry as VideoJob)
  else if (phase.value === 'aplus') await aplusPanel.value?.openHistoryJob(entry as AplusJob)
  else {
    job.value = preservePendingJobItems(await getJob(entry.id))
    selected.value = job.value.items.filter((item) => item.status === 'succeeded').map((item) => item.id)
    if (suiteJobNeedsRefresh(job.value)) void resumeSuiteJobRefresh(job.value.id)
  }
  historyOpen.value = false
}
</script>

<template>
  <div class="workspace-shell">
    <header class="topbar">
      <BrandLogo />
      <button class="new-task" @click="startNewTask"><PlusOutlined />新建任务</button>
      <div class="topbar-spacer" />
      <span class="mode-status"><i />{{ currentDryRun ? 'Dryrun 安全模式' : 'Live 模式' }}</span>
      <button class="header-link" @click="openHistoryDrawer"><HistoryOutlined />历史记录</button>
      <button class="header-link" @click="router.push('/admin/providers')"><SettingOutlined />运营后台</button>
    </header>
    <nav class="phase-rail">
      <button v-for="(item,index) in phaseDefinitions" :key="item.key" :class="{ active: phase === item.key, disabled: isPhaseDisabled(item.key) }" :disabled="isPhaseDisabled(item.key)" :aria-disabled="isPhaseDisabled(item.key)" @click="navigate(item.key)">
        <AppstoreOutlined v-if="index===0"/><BgColorsOutlined v-else-if="index===1"/><VideoCameraOutlined v-else-if="index===2"/><ThunderboltOutlined v-else/>
        <span>{{ item.short }}</span>
        <small v-if="isPhaseDisabled(item.key)" class="phase-soon-badge">即将上线</small>
      </button>
    </nav>
    <KeepAlive>
      <APlusPhasePanel v-if="phase==='aplus'" ref="aplusPanel" />
    </KeepAlive>
    <button v-if="phase==='suite'" class="mobile-config-trigger" @click="mobileOpen = true"><MenuFoldOutlined />参数</button>
    <div v-if="phase==='suite' && mobileOpen" class="mobile-scrim" @click="mobileOpen=false" />
    <aside v-if="phase==='suite'" class="config-panel" :class="{ 'mobile-open': mobileOpen }">
      <button class="mobile-close" @click="mobileOpen=false">×</button>
      <template v-if="phase==='suite'">
        <section class="form-section"><div class="section-title"><span>1</span><strong>上传商品图</strong><em>最多 3 张</em></div>
          <label class="upload-zone" :class="{ disabled: uploadLimitReached || uploading }" :aria-disabled="uploadLimitReached || uploading"><input type="file" accept="image/png,image/jpeg,image/webp" multiple :disabled="uploadLimitReached || uploading" @change="filesSelected"/><CloudUploadOutlined/><b>{{ uploading ? '上传中…' : uploadLimitReached ? '最多上传 3 张' : '点击或拖拽上传' }}</b><small>{{ uploadLimitReached ? '删除已有图片后可继续上传' : 'JPG / PNG / WebP · 单张不超过 15MB' }}</small></label>
          <div v-if="assets.length" class="uploaded-row"><div v-for="asset in assets" :key="asset.id"><img :src="asset.url" :alt="asset.original_name"/><button class="remove-uploaded-asset" type="button" aria-label="删除已上传商品图" @click="removeAsset(asset.id)"><CloseOutlined/></button></div></div>
          <button v-else class="sample-button" @click="useSample">使用 Listingo 演示商品</button>
        </section>
        <section class="form-section">
          <div class="section-title"><span>2</span><strong>生成设置</strong></div>
          <div class="field-grid">
            <label>电商平台<select v-model="form.platform"><option v-for="value in platformOptions" :key="value" :value="value">{{ value }}</option></select></label>
            <label>目标市场<select v-model="form.market"><option v-for="value in marketOptions" :key="value" :value="value">{{ value }}</option></select></label>
            <label>图片语言<select v-model="form.language"><option v-for="value in languageOptions" :key="value" :value="value">{{ value }}</option></select></label>
            <label>画面比例<select v-model="form.ratio"><option v-for="value in ratioOptions" :key="value" :value="value">{{ value }}</option></select></label>
          </div>
        </section>
        <section class="form-section copywriting-section"><div class="section-title"><span>3</span><strong>商品卖点与要求</strong><button :disabled="helping" @click="aiWrite"><ThunderboltOutlined/>{{ helping ? '帮写中…' : 'AI 帮写' }}</button></div>
          <div class="markdown-input-frame selling-points-markdown-frame">
            <div v-if="form.sellingPoints.trim() && !sellingPointsEditing" class="markdown-preview main-copy-preview" role="button" tabindex="0" aria-label="编辑商品卖点与要求" @click="showSellingPointsEditor" @keydown.enter.prevent="showSellingPointsEditor" @keydown.space.prevent="showSellingPointsEditor" v-html="renderMarkdown(form.sellingPoints)"></div>
            <textarea v-else ref="sellingPointsInput" v-model="form.sellingPoints" class="selling-points-input" rows="8" :placeholder="sellingPointsPlaceholder" @focus="sellingPointsEditing = true" @blur="sellingPointsEditing = false"/>
          </div>
          <div class="model-preference-row">
            <span><b>生成偏好</b><small>{{ selectedModelPreference.description }}</small></span>
            <div class="model-preference-select">
              <button class="model-preference-trigger" type="button" :aria-expanded="preferenceOpen" aria-haspopup="listbox" @click="preferenceOpen = !preferenceOpen">{{ selectedModelPreference.label }}<DownOutlined/></button>
              <div v-if="preferenceOpen" class="model-preference-menu" role="listbox" aria-label="生成偏好">
                <button v-for="option in modelPreferenceOptions" :key="option.key" type="button" role="option" :aria-selected="option.key === form.modelPreference" @click="selectModelPreference(option.key)">
                  <span><b>{{ option.label }}</b><small>{{ option.description }}</small></span>
                  <CheckOutlined v-if="option.key === form.modelPreference"/>
                </button>
              </div>
            </div>
          </div>
          <Teleport to="body">
            <div v-if="aiWriteOpen" class="ai-write-popover" role="dialog" aria-label="AI 帮写建议">
              <header><strong><ThunderboltOutlined/>AI 帮写建议</strong><button type="button" aria-label="关闭 AI 帮写建议" @click="aiWriteOpen=false"><CloseOutlined/></button></header>
              <div class="markdown-input-frame ai-suggestion-markdown-frame">
                <button v-if="aiSuggestion.trim() && !aiSuggestionEditing" class="markdown-preview" type="button" aria-label="编辑 AI 帮写候选内容" @click="editAiSuggestion" v-html="renderMarkdown(aiSuggestion)"></button>
                <textarea v-else ref="aiSuggestionInput" v-model="aiSuggestion" rows="8" aria-label="AI 帮写候选内容" @blur="aiSuggestionEditing=false"/>
              </div>
              <p>建议内容可直接修改；确认前不会覆盖原输入。</p>
              <footer><button type="button" :disabled="helping" @click="regenerateCopywriting"><ThunderboltOutlined/>{{ helping ? '生成中…' : '重新帮写' }}</button><button type="button" class="apply" @click="applyAiSuggestion">确认回填</button></footer>
            </div>
          </Teleport>
        </section>
        <section class="form-section suite-config">
          <div class="section-title"><span>4</span><strong>套图结构配置</strong><em>{{ count }} 张</em></div>
          <div class="suite-choice-list">
            <button :class="{active:form.mode==='smart'}" @click="form.mode='smart'">
              <i>{{ form.mode==='smart' ? '✓' : '' }}</i><span><b>智能匹配</b><small>分析商品与平台规则，匹配最佳套图结构</small></span>
            </button>
            <button :class="{active:form.mode==='custom'}" @click="form.mode='custom'">
              <i>{{ form.mode==='custom' ? '✓' : '' }}</i><span><b>自定义配置</b><small>自由调整各类型图片数量，至少选择 7 张</small></span>
            </button>
          </div>
          <div v-if="form.mode==='custom'" class="custom-type-list">
            <article v-for="item in customTypeDefinitions" :key="item.key">
              <span><b>{{ item.label }}<em v-if="item.key==='other'">AI 智能匹配</em></b><small>{{ item.description }}</small></span>
              <div><button :disabled="form.customCounts[item.key]===0 || count<=7" @click="adjustCustomCount(item.key,-1)">−</button><b>{{ form.customCounts[item.key] }}</b><button :disabled="form.customCounts[item.key]===4 || count>=12" @click="adjustCustomCount(item.key,1)">＋</button></div>
            </article>
          </div>
          <label class="switch-row"><span><b>安全演示模式</b><small>本地模拟资产，不调用语言或图片模型</small></span><input v-model="form.dryRun" type="checkbox"/></label>
        </section>
        <div class="panel-footer">
          <button v-if="suiteJobActive" class="secondary-action cancel-action" :disabled="cancelling" @click="cancelGeneration"><CloseOutlined/>{{ cancelling ? '取消中' : '取消任务' }}</button>
          <button class="generate-button" :disabled="generating || !assets.length || !inputValid || !customValid" @click="generate"><RocketOutlined/>{{ generating ? '正在处理' : `开始生成 ${count} 张套图` }}</button>
        </div>
      </template>
      <template v-else><section class="form-section demo-config"><div class="section-title"><span>1</span><strong>输入素材</strong></div><label class="upload-zone compact"><CloudUploadOutlined/><b>上传商品或参考素材</b><small>演示入口，不会上传到模型</small></label></section><section class="form-section"><div class="section-title"><span>2</span><strong>演示配置</strong></div><div class="field-grid"><label>目标平台<select><option>亚马逊</option><option>抖音海外商城</option></select></label><label>输出语言<select><option>简体中文</option><option>英语</option></select></label></div><textarea rows="5" value="突出通勤场景、简洁质感与易用性，生成可继续编辑的结果。"/></section><div class="demo-notice"><ThunderboltOutlined/><div><b>功能演示</b><p>表单、节点与状态可交互，二至四期不会调用模型。</p></div></div></template>
    </aside>
    <main v-if="phase==='suite'" class="preview-canvas">
      <template v-if="phase==='suite'">
        <div v-if="job?.items.length" class="result-workspace">
          <div class="result-toolbar">
            <div><span class="success-dot" :class="{ failed: ['failed', 'cancelled'].includes(job.status), warning: ['partial_failed', 'partial_cancelled', 'cancelling'].includes(job.status) }"/><span class="result-status-text"><strong>{{ job.status==='succeeded' ? '套图已生成' : job.status==='partial_failed' ? '部分图片生成失败，可重试' : job.status==='cancelled' ? '任务已取消' : job.status==='partial_cancelled' ? '任务已部分取消' : job.status==='failed' ? '任务失败' : '任务处理中' }}</strong><small>{{ job.items.length }} 张 · {{ job.dry_run ? 'Dryrun' : 'Live' }}</small><small v-if="currentFailureMessage" class="result-error">{{ currentFailureMessage }}</small></span></div>
            <div>
              <button v-if="suiteJobActive" class="secondary-action cancel-action" :disabled="cancelling" @click="cancelGeneration"><CloseOutlined/>{{ cancelling ? '取消中' : '取消任务' }}</button>
              <button v-if="job.items.some((item)=>item.status==='failed')" class="secondary-action retry-all" :disabled="generating" @click="retryFailed"><ThunderboltOutlined/>重试失败项</button>
              <button class="secondary-action" @click="selected=job.items.filter((i)=>i.status==='succeeded').map((i)=>i.id)">全选成功项</button>
              <div class="download-menu"><button class="download-button" @click="download('zip')"><DownloadOutlined/>下载选中 ({{ selected.length }})</button><button class="download-toggle" type="button" aria-label="选择下载格式" :aria-expanded="downloadMenuOpen" @click="downloadMenuOpen=!downloadMenuOpen"><DownOutlined/></button><div v-if="downloadMenuOpen" class="download-menu-panel"><button type="button" @click="download('zip')">下载套图 ZIP</button><button type="button" @click="download('long_image')">下载长拼图 PNG</button></div></div>
            </div>
          </div>
          <ResultGrid :items="job.items" :selected="selected" @toggle="toggleSelected" @edit="openEdit" @preview="preview" @retry="retryFailed" @script="openScript"/>
        </div>
        <div v-else class="empty-preview"><div class="preview-copy"><span>LISTINGO PRODUCT SUITE</span><h2>一件商品，生成一整套<br/>可直接上架的视觉内容</h2><p>基于商品图与销售目标自动规划画面职责，从主图、场景图到卖点证明，保持产品一致。</p></div><div class="demo-mosaic"><figure v-for="(image,index) in demoImages" :key="image"><img :src="image" alt="Listingo 演示套图"/><figcaption>{{ ['首屏主视觉','真实使用场景','通勤生活方式','标准商品主图'][index] }}</figcaption></figure></div><div class="empty-hint"><CloudUploadOutlined/><span>从左侧上传商品图开始</span></div></div>
      </template>
    </main>
    <main v-else-if="phase==='agent'" class="preview-canvas"><DemoPhasePanel :phase="phase"/></main>
    <KeepAlive>
      <VideoPhasePanel v-if="phase==='video'" ref="videoPanel" />
    </KeepAlive>
    <a-drawer v-model:open="historyOpen" :title="historyTitle" width="420"><div class="history-list"><button v-for="entry in history" :key="entry.id" @click="openHistoryJob(entry)"><img :src="historyThumbnail(entry)" alt="历史缩略图"/><span><b>{{ historySummary(entry) }}</b><small><ClockCircleOutlined/>{{ new Date(entry.created_at).toLocaleString() }}</small><em>{{ entry.status }} · {{ entry.dry_run ? 'Dryrun' : 'Live' }}</em></span></button><p v-if="!history.length">{{ historyEmptyText }}</p></div></a-drawer>
    <a-modal v-model:open="previewOpen" title="结果预览" :footer="null" width="720"><img class="modal-preview" :src="currentPreview" alt="结果预览"/><div class="version-strip"><button v-for="version in activeItem?.versions" :key="version.id" @click="activeItem && (activeItem.current_version_id=version.id)">V{{ version.version_no }} · {{ version.instruction }}</button></div></a-modal>
    <a-modal v-model:open="scriptOpen" title="图片脚本" :footer="null" width="760"><div v-if="activeItem" class="aplus-script-preview" v-html="renderMarkdown(activeItemScript)" /></a-modal>
    <a-modal v-model:open="editOpen" title="二次编辑 · 创建子版本" ok-text="生成新版本" cancel-text="取消" @ok="submitEdit"><div class="edit-dialog"><img :src="currentPreview" alt="当前版本"/><label>修改要求<textarea v-model="editInstruction" rows="5"/></label><p>Live 时将使用“当前版本图 + 原始商品图 + 修改要求”调用 generate；Dryrun 使用本地资产演示版本链。</p></div></a-modal>
    <a-modal v-model:open="confirmOpen" title="确认生成策略" ok-text="确认并开始生成" cancel-text="返回修改" @ok="runConfirmedGeneration"><div class="generation-confirm"><p>系统将先读取商品图提取事实，再由当前 Meta Prompt 规划套图；生成前后会拦截黄赌毒、政治内容和政治领导人等安全风险。</p><dl><div><dt>平台 / 市场</dt><dd>{{ form.platform }} / {{ form.market }}</dd></div><div><dt>语言 / 比例</dt><dd>{{ form.language }} / {{ ratioValues[form.ratio] || '1:1' }}</dd></div><div><dt>套图结构</dt><dd>{{ form.mode==='smart' ? `智能匹配 ${count} 张` : `自定义 ${count} 张` }}</dd></div><div><dt>生成偏好</dt><dd>{{ layoutPreferred ? '视觉排版优先' : '商品保持优先' }}</dd></div><div><dt>内容安全</dt><dd>输入、规划文本和最终图片均会进行安全审计</dd></div></dl></div></a-modal>
  </div>
</template>

<style src="./workspace.css" />
<style src="./workspace-suite.css" />
