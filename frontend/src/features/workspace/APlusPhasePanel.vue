<script setup lang="ts">
import { computed, ref, watch } from 'vue'
import { message } from 'ant-design-vue'
import {
  CheckOutlined,
  CloseOutlined,
  CloudUploadOutlined,
  DownloadOutlined,
  LoadingOutlined,
  RocketOutlined,
  ThunderboltOutlined,
} from '@ant-design/icons-vue'
import {
  aplusDownloadUrl,
  createAplusGenerationJob,
  createAplusPlanJob,
  getAplusGenerationJob,
  getAplusPlanJob,
  uploadAsset,
  type AplusItem,
  type AplusJob,
  type Asset,
} from '../../api/client'
import {
  aplusLanguageOptions,
  aplusMarketOptions,
  aplusModules,
  aplusOutputSpecs,
  aplusPlatformOptions,
  aplusTargetLabel,
  buildAplusOutputTargets,
  buildAplusPlanPayload,
  createDefaultAplusForm,
  isAplusAmazon,
  type AplusOutputSpec,
} from './workspace-model'

const assets = ref<Asset[]>([])
const uploading = ref(false)
const planning = ref(false)
const generating = ref(false)
const form = ref(createDefaultAplusForm())
const planJob = ref<AplusJob | null>(null)
const generationJob = ref<AplusJob | null>(null)
const selectedPlanItemIds = ref<string[]>([])
const selectedResultIds = ref<string[]>([])

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
const planReady = computed(() => planJob.value?.status === 'succeeded' && planJob.value.items.length > 0)
const canPlan = computed(() => assets.value.length > 0 && form.value.selectedModules.length > 0 && outputTargets.value.length > 0)
const selectedPlanItems = computed(() => (planJob.value?.items ?? []).filter((item) => selectedPlanItemIds.value.includes(item.id)))
const canGenerate = computed(() => planReady.value && selectedPlanItemIds.value.length > 0 && outputTargets.value.length > 0)

watch(() => form.value.platform, (platform) => {
  if (!isAplusAmazon(platform) && form.value.outputSpec.startsWith('amazon_aplus')) {
    form.value.outputSpec = '1:1'
    form.value.advancedTargets = ['web']
  }
})

function requestDetail(error: any): string {
  const detail = error?.response?.data?.detail
  if (Array.isArray(detail)) return detail.map((item) => item?.msg || String(item)).join('；')
  return detail || error?.message || ''
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
    assets.value = [await uploadAsset(new File([blob], 'listingo-demo-outdoor-pack.png', { type: 'image/png' }))]
    message.success('已载入演示商品')
  } catch {
    message.error('载入演示商品失败，请确认后端已启动')
  } finally {
    uploading.value = false
  }
}

function toggleModule(module: string) {
  const exists = form.value.selectedModules.includes(module)
  if (exists) {
    form.value.selectedModules = form.value.selectedModules.filter((item) => item !== module)
    return
  }
  if (form.value.selectedModules.length >= 10) {
    message.warning('最多选择 10 个详情页模块')
    return
  }
  form.value.selectedModules = [...form.value.selectedModules, module]
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

async function waitForPlan(jobId: string): Promise<AplusJob> {
  for (let attempt = 0; attempt < 300; attempt += 1) {
    const latest = await getAplusPlanJob(jobId)
    planJob.value = latest
    if (['succeeded', 'failed'].includes(latest.status)) return latest
    await new Promise((resolve) => window.setTimeout(resolve, 1000))
  }
  throw new Error('A+ 方案等待超时')
}

async function waitForGeneration(jobId: string): Promise<AplusJob> {
  for (let attempt = 0; attempt < 900; attempt += 1) {
    const latest = await getAplusGenerationJob(jobId)
    generationJob.value = latest
    if (['succeeded', 'partial_failed', 'failed'].includes(latest.status)) return latest
    await new Promise((resolve) => window.setTimeout(resolve, 1000))
  }
  throw new Error('A+ 图片生成等待超时')
}

async function generatePlan() {
  if (!canPlan.value) {
    message.warning('请先上传商品图，并至少选择 1 个模块和 1 个输出比例')
    return
  }
  planning.value = true
  generationJob.value = null
  selectedResultIds.value = []
  try {
    const created = await createAplusPlanJob(buildAplusPlanPayload(assets.value.map((asset) => asset.id), form.value))
    planJob.value = created
    const finished = await waitForPlan(created.id)
    if (finished.status === 'failed') {
      message.error(finished.error || 'A+ 方案生成失败')
      return
    }
    selectedPlanItemIds.value = finished.items.map((item) => item.id)
    message.success('A+ 模块方案已生成')
  } catch (error: any) {
    message.error(requestDetail(error) || 'A+ 方案生成失败')
  } finally {
    planning.value = false
  }
}

async function generateImages() {
  if (!canGenerate.value || !planJob.value) {
    message.warning('请先生成并选择模块方案')
    return
  }
  generating.value = true
  try {
    const created = await createAplusGenerationJob({
      plan_job_id: planJob.value.id,
      module_item_ids: selectedPlanItemIds.value,
      output_targets: outputTargets.value,
      dry_run: form.value.dryRun,
    })
    generationJob.value = created
    const finished = await waitForGeneration(created.id)
    selectedResultIds.value = finished.items.filter((item) => item.status === 'succeeded').map((item) => item.id)
    message[finished.status === 'succeeded' ? 'success' : finished.status === 'partial_failed' ? 'warning' : 'error'](
      finished.status === 'succeeded' ? 'A+ 图片生成完成' : finished.error || 'A+ 图片生成存在失败项',
    )
  } catch (error: any) {
    message.error(requestDetail(error) || 'A+ 图片生成失败')
  } finally {
    generating.value = false
  }
}

function currentUrl(item: AplusItem): string | undefined {
  return item.versions.find((version) => version.id === item.current_version_id)?.url ?? item.versions.at(-1)?.url
}

function togglePlanItem(id: string) {
  selectedPlanItemIds.value = selectedPlanItemIds.value.includes(id)
    ? selectedPlanItemIds.value.filter((item) => item !== id)
    : [...selectedPlanItemIds.value, id]
}

function toggleResult(id: string) {
  selectedResultIds.value = selectedResultIds.value.includes(id)
    ? selectedResultIds.value.filter((item) => item !== id)
    : [...selectedResultIds.value, id]
}

function downloadResults() {
  if (!generationJob.value || !selectedResultIds.value.length) {
    message.warning('请至少选择一张 A+ 结果')
    return
  }
  window.open(aplusDownloadUrl(generationJob.value.id, selectedResultIds.value), '_blank')
}
</script>

<template>
  <aside class="config-panel aplus-config-panel">
    <section class="form-section">
      <div class="section-title"><span>1</span><strong>上传商品图</strong><em>最多 3 张</em></div>
      <label class="upload-zone" :class="{ disabled: uploadLimitReached || uploading }">
        <input type="file" accept="image/png,image/jpeg,image/webp" multiple :disabled="uploadLimitReached || uploading" @change="filesSelected" />
        <CloudUploadOutlined />
        <b>{{ uploading ? '上传中' : uploadLimitReached ? '最多上传 3 张' : '点击上传商品图' }}</b>
        <small>只传图时会先识别商品；图文同时传入时严格按文字事实</small>
      </label>
      <div v-if="assets.length" class="uploaded-row">
        <div v-for="asset in assets" :key="asset.id">
          <img :src="asset.url" :alt="asset.original_name" />
          <button class="remove-uploaded-asset" type="button" @click="assets = assets.filter((item) => item.id !== asset.id)"><CloseOutlined /></button>
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
      <textarea v-model="form.productInfo" class="aplus-product-info" rows="5" placeholder="可选：填写商品事实、参数、卖点。填写后系统会严格遵循这些文字，不虚构额外事实。" />
    </section>

    <section class="form-section">
      <div class="section-title"><span>3</span><strong>输出规格</strong><em>{{ outputTargets.length }} 项</em></div>
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
      <div class="section-title"><span>4</span><strong>详情页模块</strong><em>{{ form.selectedModules.length }}/10</em></div>
      <div class="aplus-module-list">
        <button v-for="module in aplusModules" :key="module" type="button" :class="{ active: form.selectedModules.includes(module) }" @click="toggleModule(module)">
          <i><CheckOutlined v-if="form.selectedModules.includes(module)" /></i><span>{{ module }}</span>
        </button>
      </div>
      <label class="switch-row"><span><b>安全演示模式</b><small>本地模拟资产，不调用语言或图片模型</small></span><input v-model="form.dryRun" type="checkbox" /></label>
    </section>

    <div class="panel-footer aplus-actions">
      <button class="generate-button" :disabled="planning || !canPlan" @click="generatePlan"><ThunderboltOutlined />{{ planning ? `生成方案 ${planJob?.progress || 0}%` : '生成模块方案' }}</button>
      <button class="secondary-action" :disabled="generating || !canGenerate" @click="generateImages"><RocketOutlined />{{ generating ? `生成图片 ${generationJob?.progress || 0}%` : `生成图片 ${selectedPlanItemIds.length * outputTargets.length} 张` }}</button>
    </div>
  </aside>

  <main class="preview-canvas aplus-preview-canvas">
    <div v-if="planReady || generationJob" class="aplus-workspace">
      <section class="aplus-plan-board">
        <header>
          <div><strong>A+ 模块方案</strong><small>{{ planJob?.params.global_plan || '确认模块后生成图片' }}</small></div>
          <span>{{ selectedPlanItemIds.length }} / {{ planJob?.items.length || 0 }}</span>
        </header>
        <article v-for="item in planJob?.items" :key="item.id" class="aplus-plan-card" :class="{ selected: selectedPlanItemIds.includes(item.id) }">
          <button type="button" class="aplus-plan-check" @click="togglePlanItem(item.id)"><CheckOutlined v-if="selectedPlanItemIds.includes(item.id)" /></button>
          <div>
            <b>{{ item.module_index }}. {{ item.module_name }}</b>
            <textarea v-model="item.image_prompt" rows="3" />
            <textarea v-model="item.copy_requirements" rows="2" />
          </div>
        </article>
      </section>

      <section class="aplus-results">
        <header>
          <div><strong>A+ 生成结果</strong><small>{{ outputTargets.map((target) => aplusTargetLabel(target.mode, target.aspect_ratio)).join(' / ') }}</small></div>
          <button class="download-button" :disabled="!selectedResultIds.length" @click="downloadResults"><DownloadOutlined />下载选中 ({{ selectedResultIds.length }})</button>
        </header>
        <div v-if="generationJob?.items.length" class="aplus-result-grid">
          <article v-for="item in generationJob.items" :key="item.id" class="aplus-result-card" :class="{ selected: selectedResultIds.includes(item.id), failed: item.status === 'failed' }">
            <button class="select-dot" type="button" @click="toggleResult(item.id)"><CheckOutlined v-if="selectedResultIds.includes(item.id)" /></button>
            <img v-if="currentUrl(item)" :src="currentUrl(item)" :alt="item.module_name" />
            <div v-else class="pending-image"><LoadingOutlined spin /><span>{{ item.status === 'failed' ? '生成失败' : '生成中' }}</span></div>
            <footer>
              <b>{{ item.module_name }}</b>
              <span>{{ aplusTargetLabel(item.output_mode, item.aspect_ratio) }}</span>
              <small v-if="item.error">{{ item.error }}</small>
            </footer>
          </article>
        </div>
        <div v-else class="aplus-empty-results">
          <RocketOutlined />
          <span>模块方案确认后，会按选中模块和输出规格生成详情页图片。</span>
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
</template>
