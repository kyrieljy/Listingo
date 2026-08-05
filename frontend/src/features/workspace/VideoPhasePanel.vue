<script setup lang="ts">
import { computed, nextTick, onMounted, ref } from 'vue'
import { Modal, message } from 'ant-design-vue'
import {
  CheckOutlined,
  CloseOutlined,
  CloudUploadOutlined,
  DownloadOutlined,
  PlayCircleOutlined,
  ReloadOutlined,
  RocketOutlined,
  ThunderboltOutlined,
} from '@ant-design/icons-vue'
import {
  assistVideoCopywriting,
  cancelVideoJob,
  createVideoJob,
  getVideoJob,
  listVideoJobs,
  retryFailedVideoItems,
  uploadAsset,
  videoDownloadUrl,
  type Asset,
  type VideoItem,
  type VideoJob,
} from '../../api/client'
import {
  buildVideoPayload,
  createDefaultVideoForm,
  renderMarkdown,
  videoCountryOptions,
  videoLanguageOptions,
  videoMarketOptions,
  videoPlatformOptions,
  videoRatioOptions,
  videoTypeOptions,
} from './workspace-model'

const assets = ref<Asset[]>([])
const form = ref(createDefaultVideoForm())
const uploading = ref(false)
const helping = ref(false)
const generating = ref(false)
const cancelling = ref(false)
const cancelRequested = ref(false)
const job = ref<VideoJob | null>(null)
const history = ref<VideoJob[]>([])
const selected = ref<string[]>([])
const previewItem = ref<VideoItem | null>(null)
const advancedOpen = ref(false)
const aiSuggestion = ref('')
const aiWriteOpen = ref(false)
const sellingPointsEditing = ref(false)
const aiSuggestionEditing = ref(false)
const sellingPointsInput = ref<HTMLTextAreaElement | null>(null)
const aiSuggestionInput = ref<HTMLTextAreaElement | null>(null)
const VIDEO_JOB_POLL_INTERVAL_MS = 1000
const FINAL_VIDEO_JOB_STATUSES = new Set(['succeeded', 'partial_failed', 'failed', 'cancelled', 'partial_cancelled'])

const videoSellingPointsPlaceholder = `建议包含以下信息：
1. 商品名称
2. 核心卖点
3. 适用人群
4. 使用场景
5. 视频转化目标`

const selectedRatioOptions = computed(() => {
  const filtered = videoRatioOptions.filter((item) => item.platform === form.value.platform)
  return filtered.length ? filtered : videoRatioOptions
})
const uploadLimitReached = computed(() => assets.value.length >= 3)
const canGenerate = computed(() => assets.value.length > 0 && form.value.videoTypes.length > 0)
const videoJobActive = computed(() => Boolean(job.value && !FINAL_VIDEO_JOB_STATUSES.has(job.value.status)))
const dryRun = computed(() => form.value.dryRun)
onMounted(async () => {
  try { history.value = await listVideoJobs() } catch { history.value = [] }
})

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
  Modal.error({ title: fallback, content: detail })
}
function isVideoUrl(url: string) {
  return /\.(mp4|webm|mov)(\?|$)/i.test(url)
}
async function showSellingPointsEditor() {
  sellingPointsEditing.value = true
  await nextTick()
  sellingPointsInput.value?.focus()
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
  sellingPointsEditing.value = false
  form.value.sellingPoints = ''
}
function removeAsset(id: string) {
  assets.value = assets.value.filter((asset) => asset.id !== id)
  clearCopywritingState()
}
function createOptimisticVideoJob(payload: Record<string, unknown>): VideoJob {
  const types = Array.isArray(payload.video_types) ? payload.video_types as string[] : form.value.videoTypes
  return {
    id: `optimistic-video-${Date.now()}`,
    status: 'running',
    dry_run: Boolean(payload.dry_run),
    progress: 0,
    count: types.length,
    params: payload,
    error: null,
    created_at: new Date().toISOString(),
    items: types.map((type, index) => ({
      id: `optimistic-video-item-${index}`,
      index,
      video_type: type,
      status: 'running',
      provider_id: null,
      provider_task_id: null,
      error: null,
      prompt_text: '',
      script_markdown: '',
      current_version_id: null,
      versions: [],
    })),
  }
}

async function filesSelected(event: Event) {
  const input = event.target as HTMLInputElement
  if (uploadLimitReached.value) {
    message.warning('最多上传 3 张商品图')
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
  try {
    for (const file of files) assets.value.push(await uploadAsset(file))
    message.success('商品图上传成功')
  } catch (error: any) {
    handleRequestError(error, '上传失败')
  } finally {
    uploading.value = false
    input.value = ''
  }
}
async function useSample() {
  uploading.value = true
  try {
    const blob = await (await fetch('/demo/video-skincare-source.png')).blob()
    const demoAsset = await uploadAsset(new File([blob], 'listingo-demo-skincare-device.png', { type: 'image/png' }))
    clearCopywritingState()
    assets.value = [demoAsset]
    message.success('已载入演示商品')
  } catch (error: any) {
    handleRequestError(error, '载入演示商品失败')
  } finally {
    uploading.value = false
  }
}
function toggleVideoType(type: string) {
  form.value.videoTypes = form.value.videoTypes.includes(type)
    ? form.value.videoTypes.filter((item) => item !== type)
    : [...form.value.videoTypes, type]
}
async function aiWrite() {
  helping.value = true
  try {
    const result = await assistVideoCopywriting({
      asset_ids: assets.value.map((asset) => asset.id),
      platform: form.value.platform,
      market: form.value.market,
      country: form.value.country,
      language: form.value.language,
      selling_points: form.value.sellingPoints,
      video_types: form.value.videoTypes,
      dry_run: form.value.dryRun,
    })
    aiSuggestion.value = result.selling_points
    aiSuggestionEditing.value = false
    aiWriteOpen.value = true
  } catch (error: any) {
    handleRequestError(error, 'AI 转写失败')
  } finally {
    helping.value = false
  }
}
async function regenerateCopywriting() {
  await aiWrite()
}
function applyAiSuggestion() {
  if (!aiSuggestion.value.trim()) return message.warning('AI 转写内容为空，请重新生成')
  form.value.sellingPoints = aiSuggestion.value.trim()
  sellingPointsEditing.value = false
  aiWriteOpen.value = false
  message.success('AI 转写已确认回填')
}
async function waitForVideoJob(jobId: string): Promise<VideoJob> {
  for (let attempt = 0; attempt < 1200; attempt += 1) {
    const latest = await getVideoJob(jobId)
    job.value = latest
    if (FINAL_VIDEO_JOB_STATUSES.has(latest.status)) return latest
    await new Promise((resolve) => window.setTimeout(resolve, VIDEO_JOB_POLL_INTERVAL_MS))
  }
  throw new Error('视频任务等待超时')
}
async function generate() {
  if (!assets.value.length) return message.warning('请先上传商品图')
  if (!form.value.videoTypes.length) return message.warning('请至少选择一种视频类型')
  generating.value = true
  cancelling.value = false
  cancelRequested.value = false
  try {
    const payload = buildVideoPayload(assets.value.map((asset) => asset.id), form.value)
    job.value = createOptimisticVideoJob(payload)
    selected.value = []
    const created = await createVideoJob(payload)
    job.value = created
    if (cancelRequested.value) job.value = await cancelVideoJob(created.id)
    const finished = await waitForVideoJob(created.id)
    selected.value = finished.items.filter((item) => item.status === 'succeeded').map((item) => item.id)
    history.value = await listVideoJobs()
    message[finished.status === 'failed' ? 'error' : ['partial_failed', 'partial_cancelled'].includes(finished.status) ? 'warning' : 'success'](
      finished.status === 'succeeded'
        ? '视频已生成'
        : finished.status === 'cancelled'
          ? '视频任务已取消'
          : finished.status === 'partial_cancelled'
            ? '视频任务已部分取消，已完成结果仍可使用'
            : '部分视频生成失败，可查看原因或重试',
    )
  } catch (error: any) {
    if (job.value?.id.startsWith('optimistic-video-')) job.value = null
    handleRequestError(error, '视频任务创建失败')
  } finally {
    generating.value = false
    cancelling.value = false
  }
}
async function cancelGeneration() {
  if (!job.value || cancelling.value || FINAL_VIDEO_JOB_STATUSES.has(job.value.status)) return
  cancelRequested.value = true
  cancelling.value = true
  if (job.value.id.startsWith('optimistic-video-')) {
    job.value = {
      ...job.value,
      status: 'cancelling',
      items: job.value.items.map((item) => item.status === 'succeeded' ? item : { ...item, status: 'cancelling' }),
    }
    return
  }
  try {
    job.value = await cancelVideoJob(job.value.id)
    message.success('已提交取消请求')
  } catch (error: any) {
    handleRequestError(error, '取消视频任务失败')
  } finally {
    if (!generating.value) cancelling.value = false
  }
}
async function retryFailed() {
  if (!job.value || job.value.id.startsWith('optimistic-video-')) return
  generating.value = true
  try {
    await retryFailedVideoItems(job.value.id)
    const finished = await waitForVideoJob(job.value.id)
    selected.value = finished.items.filter((item) => item.status === 'succeeded').map((item) => item.id)
  } catch (error: any) {
    handleRequestError(error, '视频重试失败')
  } finally {
    generating.value = false
  }
}
async function openHistoryJob(entry: VideoJob) {
  job.value = await getVideoJob(entry.id)
  selected.value = job.value.items.filter((item) => item.status === 'succeeded').map((item) => item.id)
}
function downloadSelected() {
  if (!job.value || !selected.value.length) return message.warning('请先选择成功视频')
  if (job.value.id.startsWith('optimistic-video-')) return message.warning('视频还在生成中')
  const successfulIds = new Set(job.value.items.filter((item) => item.status === 'succeeded').map((item) => item.id))
  const itemIds = selected.value.filter((id) => successfulIds.has(id))
  if (!itemIds.length) return message.warning('请先选择成功视频')
  window.open(videoDownloadUrl(job.value.id, itemIds), '_blank')
}
function toggleSelected(id: string) {
  const item = job.value?.items.find((entry) => entry.id === id)
  if (!item || item.status !== 'succeeded') return
  selected.value = selected.value.includes(id) ? selected.value.filter((item) => item !== id) : [...selected.value, id]
}

function startNewTask() {
  assets.value = []
  form.value = createDefaultVideoForm()
  uploading.value = false
  helping.value = false
  generating.value = false
  cancelling.value = false
  cancelRequested.value = false
  job.value = null
  selected.value = []
  previewItem.value = null
  advancedOpen.value = false
  aiSuggestion.value = ''
  aiWriteOpen.value = false
  sellingPointsEditing.value = false
  aiSuggestionEditing.value = false
}

defineExpose({ openHistoryJob, startNewTask, dryRun })
</script>

<template>
  <section class="video-workspace">
    <aside class="video-panel">
      <section class="video-section">
        <div class="section-title"><span>1</span><strong>上传产品图</strong><em>最多 3 张</em></div>
        <label class="upload-zone" :class="{ disabled: uploading || uploadLimitReached }">
          <input type="file" accept="image/png,image/jpeg,image/webp" multiple :disabled="uploading || uploadLimitReached" @change="filesSelected" />
          <CloudUploadOutlined />
          <b>{{ uploading ? '上传中...' : uploadLimitReached ? '最多上传 3 张' : '点击上传产品图' }}</b>
          <small>{{ uploadLimitReached ? '删除已有图片后可继续上传' : '建议上传多张不同角度商品图' }}</small>
        </label>
        <div v-if="assets.length" class="uploaded-row">
          <div v-for="asset in assets" :key="asset.id">
            <img :src="asset.url" :alt="asset.original_name" />
            <button class="remove-uploaded-asset" type="button" aria-label="删除已上传商品图" @click="removeAsset(asset.id)"><CloseOutlined /></button>
          </div>
        </div>
        <button v-else class="sample-button" @click="useSample">使用 Listingo 演示商品</button>
      </section>

      <section class="video-section">
        <div class="section-title"><span>2</span><strong>目标市场与语言</strong></div>
        <div class="video-field-grid">
          <label>市场<select v-model="form.market"><option v-for="value in videoMarketOptions" :key="value">{{ value }}</option></select></label>
          <label>国家<select v-model="form.country"><option v-for="value in videoCountryOptions" :key="value">{{ value }}</option></select></label>
          <label>语言<select v-model="form.language"><option v-for="value in videoLanguageOptions" :key="value">{{ value }}</option></select></label>
          <label>平台<select v-model="form.platform"><option v-for="value in videoPlatformOptions" :key="value">{{ value }}</option></select></label>
        </div>
        <label class="video-full-select">发布版式<select v-model="form.ratio"><option v-for="item in selectedRatioOptions" :key="item.label" :value="item.value">{{ item.label }}</option></select></label>
      </section>

      <section class="video-section">
        <div class="section-title"><span>3</span><strong>商品卖点</strong><button :disabled="helping" @click="aiWrite"><ThunderboltOutlined />{{ helping ? '转写中...' : 'AI 转写' }}</button></div>
        <div class="markdown-input-frame video-selling-points-markdown-frame">
          <div v-if="form.sellingPoints.trim() && !sellingPointsEditing" class="markdown-preview main-copy-preview" role="button" tabindex="0" aria-label="编辑商品卖点" @click="showSellingPointsEditor" @keydown.enter.prevent="showSellingPointsEditor" @keydown.space.prevent="showSellingPointsEditor" v-html="renderMarkdown(form.sellingPoints)"></div>
          <textarea v-else ref="sellingPointsInput" v-model="form.sellingPoints" class="selling-points-input video-selling-points-input" rows="6" :placeholder="videoSellingPointsPlaceholder" @focus="sellingPointsEditing = true" @blur="sellingPointsEditing = false" />
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
        <label class="video-full-select">商品名称<input v-model="form.productName" placeholder="可选" /></label>
        <label class="video-full-select">目标人群<input v-model="form.targetAudience" placeholder="可选，例如 20-35 岁通勤人群" /></label>
      </section>

      <section class="video-section">
        <div class="section-title"><span>4</span><strong>视频类型</strong></div>
        <div class="video-type-grid">
          <button v-for="item in videoTypeOptions" :key="item.key" :class="{ active: form.videoTypes.includes(item.key) }" @click="toggleVideoType(item.key)">
            <i><CheckOutlined v-if="form.videoTypes.includes(item.key)" /></i>
            <span><b>{{ item.title }}</b><small>{{ item.subtitle }}</small></span>
          </button>
        </div>
      </section>

      <section class="video-section">
        <button class="advanced-trigger" @click="advancedOpen = !advancedOpen">高级设置</button>
        <div v-if="advancedOpen" class="video-advanced">
          <label>时长<select v-model.number="form.duration"><option :value="5">5 秒</option><option :value="10">10 秒</option><option :value="15">15 秒</option></select></label>
          <label>清晰度<select v-model="form.resolution"><option>1080p</option><option>720p</option></select></label>
        </div>
        <label class="video-switch"><span><b>安全演示模式</b><small>本地模拟，不调用视频模型</small></span><input v-model="form.dryRun" type="checkbox" /></label>
      </section>

      <footer class="video-footer">
        <button v-if="videoJobActive" class="secondary-action cancel-action" :disabled="cancelling" @click="cancelGeneration"><CloseOutlined />{{ cancelling ? '取消中' : '取消任务' }}</button>
        <button :disabled="generating || !canGenerate" @click="generate"><RocketOutlined />{{ generating ? `正在生成 ${job?.progress || 0}%` : `生成 ${form.videoTypes.length} 条 15s 爆款视频` }}</button>
      </footer>
    </aside>

    <main class="video-main">
      <template v-if="job?.items.length">
        <div class="video-toolbar">
          <div><i :class="{ failed: ['failed', 'cancelled'].includes(job.status), warning: ['partial_failed', 'partial_cancelled', 'cancelling'].includes(job.status) }" /><span><b>{{ job.status === 'succeeded' ? '生成爆款结果' : job.status === 'cancelled' ? '视频任务已取消' : job.status === 'partial_cancelled' ? '视频任务已部分取消' : job.status === 'running' ? '正在生成视频' : '视频任务完成' }}</b><small>{{ job.count }} 条 · {{ job.dry_run ? 'Dryrun' : 'Live' }}</small></span></div>
          <div>
            <button v-if="videoJobActive" :disabled="cancelling" @click="cancelGeneration"><CloseOutlined />{{ cancelling ? '取消中' : '取消任务' }}</button>
            <button v-if="job.items.some((item) => item.status === 'failed')" @click="retryFailed"><ReloadOutlined />重试失败</button>
            <button @click="selected = job.items.filter((item) => item.status === 'succeeded').map((item) => item.id)">全选成功项</button>
            <button class="video-download" @click="downloadSelected"><DownloadOutlined />下载选中 ({{ selected.length }})</button>
          </div>
        </div>
        <div class="video-result-grid">
          <article v-for="item in job.items" :key="item.id" class="video-card" :class="{ selected: selected.includes(item.id), failed: item.status === 'failed' }">
            <button class="video-select" :disabled="item.status !== 'succeeded'" @click="toggleSelected(item.id)"><CheckOutlined v-if="selected.includes(item.id)" /></button>
            <div class="video-frame">
              <template v-if="item.status === 'succeeded' && item.versions.length">
                <video v-if="isVideoUrl(item.versions.at(-1)?.url || '')" :src="item.versions.at(-1)?.url" muted loop playsinline controls />
                <img v-else :src="item.versions.at(-1)?.url" alt="视频占位预览" />
              </template>
              <div v-else-if="item.status === 'failed'" class="video-failed"><b>生成失败</b><small>{{ item.error }}</small></div>
              <div v-else class="video-loading"><span />正在生成视频...</div>
            </div>
            <footer>
              <div>
                <b>{{ item.video_type }}</b>
                <small>第 {{ item.index + 1 }} 条 · {{ item.status }}</small>
                <small v-if="item.provider_task_id">远程任务号 {{ item.provider_task_id }}</small>
              </div>
              <button :disabled="!item.script_markdown" @click="previewItem = item"><PlayCircleOutlined />脚本</button>
            </footer>
          </article>
        </div>
      </template>

      <template v-else>
        <div class="video-empty">
          <section class="video-empty-stage" aria-label="爆款视频生成示例">
            <div class="video-empty-copy">
              <h2>爆款视频生成</h2>
              <p>15 秒短视频生成</p>
            </div>
            <div class="video-empty-visual" aria-hidden="true">
              <figure class="video-source-card">
                <img src="/demo/video-skincare-source.png" alt="" />
              </figure>
              <i class="video-empty-arrow" />
              <figure class="video-result-poster">
                <img src="/demo/video-skincare-result.png" alt="" />
              </figure>
              <article class="video-preview-phone">
                <img src="/demo/video-skincare-hero.png" alt="" />
              </article>
              <div class="video-frame-strip">
                <img src="/demo/video-skincare-frame-01.png" alt="" />
                <img src="/demo/video-skincare-frame-02.png" alt="" />
                <img src="/demo/video-skincare-frame-03.png" alt="" />
              </div>
            </div>
          </section>
        </div>
      </template>
    </main>

    <a-modal :open="!!previewItem" title="视频导演脚本" :footer="null" width="760" @update:open="(open) => { if (!open) previewItem = null }">
      <div v-if="previewItem" class="video-script-preview" v-html="renderMarkdown(previewItem.script_markdown || previewItem.prompt_text)" />
    </a-modal>
  </section>
</template>

<style src="./workspace-video.css" />

