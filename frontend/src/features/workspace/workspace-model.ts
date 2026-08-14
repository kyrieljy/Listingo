export type PhaseKey = 'suite' | 'aplus' | 'video' | 'agent'
export type SuiteMode = 'smart' | 'custom'
export type ModelPreference = 'fidelity' | 'layout'
export type CustomCountKey = 'white_background' | 'scene' | 'selling_point' | 'other'

export type CustomCounts = Record<CustomCountKey, number>

export type WorkspaceForm = {
  platform: string
  market: string
  language: string
  ratio: string
  sellingPoints: string
  productName: string
  category: string
  specifications: string
  skuInfo: string
  accessories: string
  certifications: string
  targetAudience: string
  brandStyle: string
  mode: SuiteMode
  smartCount: number
  customCounts: CustomCounts
  modelPreference: ModelPreference
  dryRun: boolean
}

export type VideoForm = {
  platform: string
  market: string
  country: string
  language: string
  ratio: string
  sellingPoints: string
  productName: string
  category: string
  targetAudience: string
  videoTypes: string[]
  duration: number
  resolution: string
  dryRun: boolean
}

export type AplusForm = {
  platform: string
  market: string
  language: string
  category: string
  productInfo: string
  selectedModules: AplusModuleSelection[]
  outputSpec: AplusOutputSpec
  advancedTargets: AplusAdvancedTarget[]
  dryRun: boolean
}
export type AplusDetailRatio = '1:1' | '3:4' | '9:16' | '16:9'
export type AplusOutputSpec = AplusDetailRatio | 'amazon_aplus_standard' | 'amazon_aplus_advanced'
export type AplusAdvancedTarget = 'web' | 'mobile'
export type AplusOutputTargetForm = {
  mode: 'detail' | 'amazon_aplus_standard' | 'amazon_aplus_advanced_web' | 'amazon_aplus_advanced_mobile'
  aspect_ratio: string
}
export type AplusModuleDefinition = { name: string; description: string }
export type AplusModuleSelection = { name: string; count: number }
export const PRODUCT_IMAGE_UPLOAD_LIMIT = 6
export const APLUS_MODULE_TOTAL_LIMIT = 12
export const finalWorkspaceJobStatuses = ['succeeded', 'partial_failed', 'failed', 'cancelled', 'partial_cancelled'] as const
export const restorableWorkspaceJobStatuses = ['queued', 'running'] as const
const restorableWorkspaceJobStatusSet = new Set<string>(restorableWorkspaceJobStatuses)

export function isActiveWorkspaceJob(job: { status: string }): boolean {
  return restorableWorkspaceJobStatusSet.has(job.status)
}

export function latestActiveWorkspaceJob<T extends { status: string; created_at: string }>(jobs: T[]): T | null {
  const active = jobs.filter(isActiveWorkspaceJob)
  active.sort((a, b) => (Date.parse(b.created_at) || 0) - (Date.parse(a.created_at) || 0))
  return active[0] ?? null
}

export const phaseDefinitions = [
  { key: 'suite' as const, label: '商品套图', short: '套图' },
  { key: 'aplus' as const, label: 'A+详情', short: 'A+' },
  { key: 'video' as const, label: '爆款视频生成', short: '视频' },
  { key: 'agent' as const, label: 'Agent与画布', short: 'Agent' },
]

export const platformOptions = [
  '亚马逊', '淘宝天猫', '1688', 'Temu', 'TikTok Shop', '拼多多', '抖音电商', 'OZON', '独立站',
  'Shopee', '阿里国际站', '速卖通', 'SHEIN', '京东', '美客多', 'Coupang', 'Wayfair',
]

export const marketOptions = [
  '美国', '欧洲', '中国', '俄罗斯', '东南亚', '西班牙', '德国', '日本', '韩国', '巴西', '墨西哥',
]

export const languageOptions = [
  '英文', '中文', '俄语', '西语', '德语', '日语', '韩语', '葡萄牙语', '印尼语', '泰语', '无文字',
]

export const ratioOptions = ['1:1', '3:4', '9:16', '16:9']
export const ratioValues: Record<string, string> = {
  '1:1': '1:1',
  '3:4': '3:4',
  '9:16': '9:16',
  '16:9': '16:9',
}

export type PreviewAspectStyle = Record<`--${string}`, string>

export function previewAspectStyle(aspectRatio: string | null | undefined): PreviewAspectStyle {
  const fallback = { '--preview-aspect-ratio': '1 / 1', '--preview-aspect-number': '1' }
  const match = String(aspectRatio ?? '').trim().match(/^(\d+(?:\.\d+)?)\s*[:/]\s*(\d+(?:\.\d+)?)$/)
  if (!match) return fallback
  const width = Number(match[1])
  const height = Number(match[2])
  if (!Number.isFinite(width) || !Number.isFinite(height) || width <= 0 || height <= 0) return fallback
  return {
    '--preview-aspect-ratio': `${width} / ${height}`,
    '--preview-aspect-number': String(width / height),
  }
}

export const videoPlatformOptions = ['TikTok', '抖音', '小红书', '淘宝', '亚马逊']
export const videoMarketOptions = ['北美', '中国', '东南亚', '欧洲', '日本', '韩国', '拉美', '中东']
export const videoCountryOptions = ['美国', '中国', '英国', '德国', '法国', '日本', '韩国', '新加坡', '泰国', '巴西', '墨西哥']
export const videoLanguageOptions = ['英语', '中文', '日语', '韩语', '西班牙语', '德语', '法语', '葡萄牙语', '泰语', '印尼语', '越南语']
export const videoRatioOptions = [
  { label: 'TikTok/Reels · 9:16', value: '9:16', platform: 'TikTok' },
  { label: '抖音 · 9:16', value: '9:16', platform: '抖音' },
  { label: '小红书 · 3:4', value: '3:4', platform: '小红书' },
  { label: '小红书 · 9:16', value: '9:16', platform: '小红书' },
  { label: '淘宝 · 1:1', value: '1:1', platform: '淘宝' },
  { label: '淘宝 · 3:4', value: '3:4', platform: '淘宝' },
  { label: '亚马逊 · 16:9', value: '16:9', platform: '亚马逊' },
  { label: '亚马逊 · 1:1', value: '1:1', platform: '亚马逊' },
]
export const videoTypeOptions = [
  { key: '痛点解决', title: '痛点解决', subtitle: '痛点场景到产品解决' },
  { key: 'UGC 种草', title: 'UGC 种草', subtitle: '真实体验分享感' },
  { key: '达人口播', title: '达人口播', subtitle: '面对镜头讲清卖点' },
  { key: '测评对比', title: '测评对比', subtitle: '对比挑战证明' },
  { key: '短剧搞笑带货', title: '短剧搞笑带货', subtitle: '轻剧情转化' },
  { key: '视觉展示', title: '视觉展示', subtitle: '产品美感与细节' },
  { key: '反转剧情', title: '反转剧情', subtitle: '前后反差记忆点' },
  { key: '清单榜单推荐', title: '清单榜单推荐', subtitle: '榜单式快速推荐' },
]

export const aplusPlatformOptions = [
  '亚马逊', '淘宝天猫1688', 'Temu', 'TikTok Shop', '拼多多', '抖音电商', 'OZON', '独立站',
  'Shopee', '阿里国际站', '速卖通', 'SHEIN', '京东', '美客多', 'Coupang', 'Wayfair',
]
export const aplusMarketOptions = ['美国', '欧洲', '中国', '俄罗斯', '东南亚', '西班牙', '德国', '日本', '韩国', '巴西', '墨西哥']
export const aplusLanguageOptions = ['英文', '中文', '俄语', '西语', '德语', '日语', '韩语', '葡萄牙语', '印尼语', '泰语', '无文字']
export const aplusDetailRatios: AplusDetailRatio[] = ['1:1', '3:4', '9:16', '16:9']
export const aplusOutputSpecs: Array<{ value: AplusOutputSpec; label: string; description: string; amazonOnly?: boolean }> = [
  { value: '1:1', label: '1:1', description: '方形详情图' },
  { value: '3:4', label: '3:4', description: '竖版详情图' },
  { value: '9:16', label: '9:16', description: '移动长竖图' },
  { value: '16:9', label: '16:9', description: '横版详情图' },
  { value: 'amazon_aplus_standard', label: '普通 A+', description: '970:600', amazonOnly: true },
  { value: 'amazon_aplus_advanced', label: '高级 A+', description: 'Web / Mobile', amazonOnly: true },
]
export const aplusModules: AplusModuleDefinition[] = [
  { name: '商品主视觉', description: '打造商品第一印象' },
  { name: '卖点拆解', description: '提炼核心购买价值' },
  { name: '生活场景', description: '呈现真实使用环境' },
  { name: '全方位展示', description: '展示商品完整形态' },
  { name: '情绪氛围', description: '强化视觉感染力' },
  { name: '品质细看', description: '放大材质与工艺细节' },
  { name: '品牌心智', description: '传递品牌定位与理念' },
  { name: '规格指南', description: '展示尺寸与选择信息' },
  { name: '效果呈现', description: '对比使用前后变化' },
  { name: '产品资料', description: '汇总参数与基础信息' },
  { name: '制造揭秘', description: '展示生产工艺过程' },
  { name: '开箱清单', description: '展示包装与附属内容' },
  { name: '款式矩阵', description: '展示多SKU组合' },
  { name: '材质解析', description: '拆解组成与用料' },
  { name: '服务承诺', description: '展示售后保障' },
  { name: '使用攻略', description: '提供使用方法建议' },
]
export const defaultAplusModules: AplusModuleSelection[] = aplusModules
  .slice(0, 6)
  .map((module) => ({ name: module.name, count: 1 }))

export function aplusModuleTotal(selections: AplusModuleSelection[]): number {
  return selections.reduce((total, selection) => total + Math.max(0, Number(selection.count) || 0), 0)
}

export function orderedAplusModuleSelections(selections: AplusModuleSelection[]): AplusModuleSelection[] {
  const counts = new Map(selections.map((selection) => [selection.name, Math.max(0, Number(selection.count) || 0)]))
  return aplusModules
    .map((module) => ({ name: module.name, count: counts.get(module.name) ?? 0 }))
    .filter((selection) => selection.count > 0)
}

export function createDefaultAplusForm(): AplusForm {
  return {
    platform: '亚马逊',
    market: '美国',
    language: '英文',
    category: '',
    productInfo: '',
    selectedModules: [...defaultAplusModules],
    outputSpec: 'amazon_aplus_standard',
    advancedTargets: ['web'],
    dryRun: true,
  }
}

export function isAplusAmazon(platform: string): boolean {
  return platform === '亚马逊'
}

export function buildAplusOutputTargets(form: AplusForm): AplusOutputTargetForm[] {
  if (aplusDetailRatios.includes(form.outputSpec as AplusDetailRatio)) {
    return [{ mode: 'detail', aspect_ratio: form.outputSpec }]
  }
  if (!isAplusAmazon(form.platform)) return [{ mode: 'detail', aspect_ratio: '1:1' }]
  if (form.outputSpec === 'amazon_aplus_standard') {
    return [{ mode: 'amazon_aplus_standard', aspect_ratio: '970:600' }]
  }
  if (form.outputSpec !== 'amazon_aplus_advanced') return []
  const targets: AplusOutputTargetForm[] = []
  if (form.advancedTargets.includes('web')) {
    targets.push({ mode: 'amazon_aplus_advanced_web', aspect_ratio: '1464:600' })
  }
  if (form.advancedTargets.includes('mobile')) {
    targets.push({ mode: 'amazon_aplus_advanced_mobile', aspect_ratio: '600:450' })
  }
  return targets
}

export function aplusTargetLabel(mode: string, ratio: string): string {
  const labels: Record<string, string> = {
    detail: '详情页',
    amazon_aplus_standard: '普通 A+',
    amazon_aplus_advanced_web: '高级 A+ Web',
    amazon_aplus_advanced_mobile: '高级 A+ 移动端',
  }
  return `${labels[mode] ?? mode} · ${ratio}`
}

export function buildAplusPlanPayload(assetIds: string[], form: AplusForm) {
  const moduleSelections = orderedAplusModuleSelections(form.selectedModules)
  return {
    asset_ids: assetIds,
    platform: form.platform,
    market: form.market,
    language: form.language,
    category: form.category,
    product_info: form.productInfo,
    module_selections: moduleSelections,
    selected_modules: moduleSelections.map((selection) => selection.name),
    output_targets: buildAplusOutputTargets(form),
    dry_run: form.dryRun,
  }
}

export const customTypeDefinitions: Array<{ key: CustomCountKey; label: string; description: string }> = [
  { key: 'white_background', label: '白底图', description: '白底主图，多角度呈现商品细节' },
  { key: 'scene', label: '场景图', description: '展示商品的生活使用场景和人物搭配' },
  { key: 'selling_point', label: '卖点图', description: '展示商品的核心卖点及细节特写' },
  { key: 'other', label: '其他', description: '对比图、尺寸图等，根据商品智能匹配' },
]

export function createDefaultWorkspaceForm(): WorkspaceForm {
  return {
    platform: '亚马逊',
    market: '美国',
    language: '英文',
    ratio: '1:1',
    sellingPoints: '',
    productName: '',
    category: '',
    specifications: '',
    skuInfo: '',
    accessories: '',
    certifications: '',
    targetAudience: '',
    brandStyle: '',
    mode: 'smart',
    smartCount: 7,
    customCounts: { white_background: 1, scene: 2, selling_point: 2, other: 2 },
    modelPreference: 'fidelity',
    dryRun: true,
  }
}

export function createDefaultVideoForm(): VideoForm {
  return {
    platform: 'TikTok',
    market: '北美',
    country: '美国',
    language: '英语',
    ratio: '9:16',
    sellingPoints: '',
    productName: '',
    category: '',
    targetAudience: '',
    videoTypes: ['UGC 种草'],
    duration: 15,
    resolution: '1080p',
    dryRun: true,
  }
}

export function customTotal(counts: CustomCounts): number {
  return Object.values(counts).reduce((total, count) => total + count, 0)
}

export function buildCustomTypes(counts: CustomCounts): string[] {
  return customTypeDefinitions.flatMap(({ key, label }) =>
    Array.from({ length: counts[key] }, (_, index) => `${label === '其他' ? '其他图' : label} ${index + 1}`),
  )
}

export function generationCount(form: WorkspaceForm): number {
  return form.mode === 'custom' ? customTotal(form.customCounts) : 7
}

export function buildGenerationPayload(
  assetIds: string[],
  sellingPoints: string,
  form: WorkspaceForm = createDefaultWorkspaceForm(),
) {
  const count = generationCount(form)
  return {
    asset_ids: assetIds,
    platform: form.platform,
    market: form.market,
    language: form.language,
    aspect_ratio: ratioValues[form.ratio] ?? '1:1',
    selling_points: sellingPoints,
    product_name: form.productName,
    category: form.category,
    specifications: form.specifications,
    sku_info: form.skuInfo,
    accessories: form.accessories,
    certifications: form.certifications,
    target_audience: form.targetAudience,
    brand_style: form.brandStyle,
    mode: form.mode,
    count,
    custom_counts: form.mode === 'custom' ? form.customCounts : undefined,
    model_preference: form.modelPreference,
    dry_run: form.dryRun,
  }
}

export function buildVideoPayload(assetIds: string[], form: VideoForm) {
  return {
    asset_ids: assetIds,
    platform: form.platform,
    market: form.market,
    country: form.country,
    language: form.language,
    aspect_ratio: form.ratio,
    selling_points: form.sellingPoints,
    product_name: form.productName,
    category: form.category,
    target_audience: form.targetAudience,
    video_types: form.videoTypes,
    duration: form.duration,
    resolution: form.resolution,
    dry_run: form.dryRun,
  }
}

function escapeHtml(value: string): string {
  return value
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;')
    .replace(/"/g, '&quot;')
    .replace(/'/g, '&#39;')
}

export function renderMarkdown(value: string): string {
  const lines = value.split(/\r?\n/)
  const blocks: string[] = []
  let listItems: string[] = []

  const flushList = () => {
    if (!listItems.length) return
    blocks.push(`<ul>${listItems.map((item) => `<li>${item}</li>`).join('')}</ul>`)
    listItems = []
  }

  for (const line of lines) {
    const trimmed = line.trim()
    if (!trimmed) {
      flushList()
      continue
    }
    const heading = trimmed.match(/^(#{1,6})\s+(.+)$/)
    if (heading) {
      flushList()
      const level = Math.min(heading[1].length, 4)
      blocks.push(`<h${level}>${escapeHtml(heading[2])}</h${level}>`)
      continue
    }
    const bullet = trimmed.match(/^[-*]\s+(.+)$/)
    if (bullet) {
      listItems.push(escapeHtml(bullet[1]))
      continue
    }
    flushList()
    blocks.push(`<p>${escapeHtml(trimmed)}</p>`)
  }
  flushList()
  return blocks.join('')
}

export type GenerationFailureLike = {
  status: string
  error?: string | null
  items?: Array<{
    index?: number | null
    image_type?: string | null
    status?: string | null
    error?: string | null
  }>
}

export function generationFailureMessage(job: GenerationFailureLike | null | undefined): string {
  if (!job) return ''
  const jobError = job.error?.trim()
  if (jobError) return jobError

  const itemErrors = (job.items ?? [])
    .filter((item) => item.status === 'failed')
    .filter((item) => item.error?.trim())
    .map((item) => {
      const label = item.image_type?.trim() || (typeof item.index === 'number' ? `第 ${item.index + 1} 张` : '失败项')
      return `${label}：${item.error?.trim()}`
    })

  if (itemErrors.length) return itemErrors.join('；')
  return job.status === 'failed' ? '任务失败，请查看运营后台日志' : ''
}
