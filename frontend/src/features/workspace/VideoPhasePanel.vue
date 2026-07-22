<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
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
const job = ref<VideoJob | null>(null)
const history = ref<VideoJob[]>([])
const selected = ref<string[]>([])
const previewItem = ref<VideoItem | null>(null)
const advancedOpen = ref(false)

const selectedRatioOptions = computed(() => {
  const filtered = videoRatioOptions.filter((item) => item.platform === form.value.platform)
  return filtered.length ? filtered : videoRatioOptions
})
const canGenerate = computed(() => assets.value.length > 0 && form.value.videoTypes.length > 0)
const currentPreviewUrl = computed(() => {
  const item = previewItem.value
  return item?.versions.find((version) => version.id === item.current_version_id)?.url || item?.versions.at(-1)?.url || ''
})

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
  const files = Array.from(input.files ?? []).slice(0, 3 - assets.value.length)
  if (!files.length) return
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
    assets.value = [await uploadAsset(new File([blob], 'listingo-demo-skincare-device.png', { type: 'image/png' }))]
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
    form.value.sellingPoints = result.selling_points
    message.success('AI 转写已回填')
  } catch (error: any) {
    handleRequestError(error, 'AI 转写失败')
  } finally {
    helping.value = false
  }
}
async function waitForVideoJob(jobId: string): Promise<VideoJob> {
  for (let attempt = 0; attempt < 1200; attempt += 1) {
    const latest = await getVideoJob(jobId)
    job.value = latest
    if (['succeeded', 'partial_failed', 'failed'].includes(latest.status)) return latest
    await new Promise((resolve) => window.setTimeout(resolve, 1500))
  }
  throw new Error('视频任务等待超时')
}
async function generate() {
  if (!assets.value.length) return message.warning('请先上传商品图')
  if (!form.value.videoTypes.length) return message.warning('请至少选择一种视频类型')
  generating.value = true
  try {
    const payload = buildVideoPayload(assets.value.map((asset) => asset.id), form.value)
    job.value = createOptimisticVideoJob(payload)
    selected.value = []
    const created = await createVideoJob(payload)
    job.value = created
    const finished = await waitForVideoJob(created.id)
    selected.value = finished.items.filter((item) => item.status === 'succeeded').map((item) => item.id)
    history.value = await listVideoJobs()
    message[finished.status === 'failed' ? 'error' : finished.status === 'partial_failed' ? 'warning' : 'success'](
      finished.status === 'succeeded' ? '视频已生成' : '部分视频生成失败，可查看原因或重试',
    )
  } catch (error: any) {
    if (job.value?.id.startsWith('optimistic-video-')) job.value = null
    handleRequestError(error, '视频任务创建失败')
  } finally {
    generating.value = false
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
function downloadSelected() {
  if (!job.value || !selected.value.length) return message.warning('请先选择视频')
  if (job.value.id.startsWith('optimistic-video-')) return message.warning('视频还在生成中')
  window.open(videoDownloadUrl(job.value.id, selected.value), '_blank')
}
function toggleSelected(id: string) {
  selected.value = selected.value.includes(id) ? selected.value.filter((item) => item !== id) : [...selected.value, id]
}
</script>

<template>
  <section class="video-workspace">
    <aside class="video-panel">
      <div class="video-tabs"><button class="active">生成爆款</button><button>爆款复刻</button></div>

      <section class="video-section">
        <div class="section-title"><span>1</span><strong>上传产品图</strong><em>最多 3 张</em></div>
        <label class="video-upload" :class="{ disabled: uploading || assets.length >= 3 }">
          <input type="file" accept="image/png,image/jpeg,image/webp" multiple :disabled="uploading || assets.length >= 3" @change="filesSelected" />
          <CloudUploadOutlined />
          <b>{{ uploading ? '上传中...' : '上传产品图' }}</b>
          <small>建议上传多张不同角度商品图</small>
        </label>
        <div v-if="assets.length" class="video-assets">
          <figure v-for="asset in assets" :key="asset.id">
            <img :src="asset.url" :alt="asset.original_name" />
            <button class="remove-uploaded-asset" type="button" aria-label="删除已上传商品图" @click="assets = assets.filter((item) => item.id !== asset.id)"><CloseOutlined /></button>
          </figure>
        </div>
        <button v-else class="video-sample" @click="useSample">使用 Listingo 演示商品</button>
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
        <textarea v-model="form.sellingPoints" rows="6" placeholder="输入商品核心卖点、适用人群、使用场景等信息..." />
        <label class="video-full-select">商品名称<input v-model="form.productName" placeholder="可选" /></label>
        <label class="video-full-select">目标人群<input v-model="form.targetAudience" placeholder="可选，例如 20-35 岁通勤人群" /></label>
      </section>

      <section class="video-section">
        <div class="section-title"><span>4</span><strong>视频类型</strong></div>
        <div class="video-type-grid">
          <button v-for="item in videoTypeOptions" :key="item.key" :class="{ active: form.videoTypes.includes(item.key) }" @click="toggleVideoType(item.key)">
            <CheckOutlined v-if="form.videoTypes.includes(item.key)" />
            <span><b>{{ item.title }}</b><small>{{ item.subtitle }}</small></span>
          </button>
        </div>
      </section>

      <section class="video-section">
        <button class="advanced-trigger" @click="advancedOpen = !advancedOpen">高级设置</button>
        <div v-if="advancedOpen" class="video-advanced">
          <label>清晰度<select v-model="form.resolution"><option>1080p</option><option>720p</option></select></label>
          <label class="video-check"><input v-model="form.generateAudio" type="checkbox" />生成音频</label>
          <label class="video-check"><input v-model="form.cameraFixed" type="checkbox" />固定镜头</label>
          <label class="video-check"><input v-model="form.watermark" type="checkbox" />添加水印</label>
        </div>
        <label class="video-switch"><span><b>安全演示模式</b><small>本地模拟，不调用视频模型</small></span><input v-model="form.dryRun" type="checkbox" /></label>
      </section>

      <footer class="video-footer">
        <button :disabled="generating || !canGenerate" @click="generate"><RocketOutlined />{{ generating ? `正在生成 ${job?.progress || 0}%` : `生成 ${form.videoTypes.length} 条 15s 爆款视频` }}</button>
      </footer>
    </aside>

    <main class="video-main">
      <template v-if="job?.items.length">
        <div class="video-toolbar">
          <div><i :class="{ failed: job.status === 'failed', warning: job.status === 'partial_failed' }" /><span><b>{{ job.status === 'succeeded' ? '生成爆款结果' : job.status === 'running' ? '正在生成视频' : '视频任务完成' }}</b><small>{{ job.count }} 条 · {{ job.dry_run ? 'Dryrun' : 'Live' }}</small></span></div>
          <div>
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
              <div><b>{{ item.video_type }}</b><small>第 {{ item.index + 1 }} 条 · {{ item.status }}</small></div>
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

