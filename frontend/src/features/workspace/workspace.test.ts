import { readFileSync } from 'node:fs'
import { describe, expect, it } from 'vitest'
import {
  APLUS_MODULE_TOTAL_LIMIT,
  buildAplusOutputTargets,
  buildAplusPlanPayload,
  buildCustomTypes,
  buildGenerationPayload,
  buildVideoPayload,
  aplusModuleTotal,
  aplusModules,
  createDefaultAplusForm,
  createDefaultVideoForm,
  createDefaultWorkspaceForm,
  generationFailureMessage,
  generationCount,
  languageOptions,
  marketOptions,
  platformOptions,
  phaseDefinitions,
  renderMarkdown,
  ratioOptions,
  ratioValues,
  videoPlatformOptions,
  videoTypeOptions,
} from './workspace-model'
import resultGridSource from './ResultGrid.vue?raw'
import aplusPanelSource from './APlusPhasePanel.vue?raw'
import videoPanelSource from './VideoPhasePanel.vue?raw'
import workspaceSource from './WorkspaceView.vue?raw'
import apiClientSource from '../../api/client.ts?raw'

const workspaceSuiteCss = readFileSync(new URL('./workspace-suite.css', import.meta.url), 'utf8')
const workspaceVideoCss = readFileSync(new URL('./workspace-video.css', import.meta.url), 'utf8')

describe('workspace model', () => {
  it('keeps the four planned phase entries in order', () => {
    expect(phaseDefinitions.map((item) => item.label)).toEqual([
      '商品套图',
      'A+详情',
      '爆款视频生成',
      'Agent与画布',
    ])
  })

  it('builds a valid default dryrun payload', () => {
    const payload = buildGenerationPayload(['asset-1'], '通勤保温，防滑握持')
    expect(payload.dry_run).toBe(true)
    expect(payload.count).toBe(7)
    expect(payload.aspect_ratio).toBe('1:1')
    expect(payload.asset_ids).toEqual(['asset-1'])
  })

  it('treats detail, standard A+ and advanced A+ as mutually exclusive output specs', () => {
    const form = createDefaultAplusForm()
    expect(buildAplusOutputTargets(form)).toEqual([{ mode: 'amazon_aplus_standard', aspect_ratio: '970:600' }])
    form.outputSpec = '3:4'
    expect(buildAplusOutputTargets(form)).toEqual([{ mode: 'detail', aspect_ratio: '3:4' }])
    form.outputSpec = 'amazon_aplus_advanced'
    form.advancedTargets = ['mobile']
    expect(buildAplusOutputTargets(form)).toEqual([{ mode: 'amazon_aplus_advanced_mobile', aspect_ratio: '600:450' }])
    form.advancedTargets = ['web', 'mobile']
    expect(buildAplusOutputTargets(form).map((target) => target.aspect_ratio)).toEqual(['1464:600', '600:450'])
    form.platform = 'Temu'
    expect(buildAplusPlanPayload(['asset-1'], form).output_targets).toEqual([{ mode: 'detail', aspect_ratio: '1:1' }])
  })

  it('exposes the new A+ module catalog with per-module quantities', () => {
    expect(APLUS_MODULE_TOTAL_LIMIT).toBe(12)
    expect(aplusModules).toEqual([
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
    ])
  })

  it('builds A+ plan payloads with ordered module selections and total counts', () => {
    const form = createDefaultAplusForm()
    form.selectedModules = [
      { name: '生活场景', count: 2 },
      { name: '商品主视觉', count: 1 },
      { name: '卖点拆解', count: 3 },
      { name: '服务承诺', count: 0 },
    ]
    const payload = buildAplusPlanPayload(['asset-1'], form)

    expect(aplusModuleTotal(form.selectedModules)).toBe(6)
    expect(payload.module_selections).toEqual([
      { name: '商品主视觉', count: 1 },
      { name: '卖点拆解', count: 3 },
      { name: '生活场景', count: 2 },
    ])
    expect(payload.selected_modules).toEqual(['商品主视觉', '卖点拆解', '生活场景'])
  })

  it('surfaces exact generation failure details from job and item errors', () => {
    expect(generationFailureMessage({
      status: 'failed',
      error: '语义重规划后仍不合格：第 1 张未显式声明画面比例 1:1',
      items: [],
    })).toBe('语义重规划后仍不合格：第 1 张未显式声明画面比例 1:1')

    expect(generationFailureMessage({
      status: 'partial_failed',
      error: '',
      items: [
        { index: 0, image_type: '首屏主视觉', status: 'succeeded', error: null },
        { index: 1, image_type: '核心卖点图', status: 'failed', error: 'Nano 调用超时' },
      ],
    })).toBe('核心卖点图：Nano 调用超时')
  })

  it('centers the result selection icon without native button padding', () => {
    const rule = resultGridSource.match(/\.select-dot\s*\{([^}]*)\}/)?.[1] ?? ''
    const normalized = rule.replace(/\s+/g, '')
    expect(normalized).toContain('display:grid')
    expect(normalized).toContain('place-items:center')
    expect(normalized).toContain('padding:0')
    expect(normalized).toContain('line-height:0')
  })

  it('renders the uploaded asset remove control with a centered icon', () => {
    expect(workspaceSource).toContain('class="remove-uploaded-asset"')
    expect(workspaceSource).toContain('aria-label="删除已上传商品图"')
    expect(workspaceSource).toContain('<CloseOutlined/>')
  })

  it('disables the upload entry and shows a clear hint after three product images', () => {
    const disabledRule = workspaceSuiteCss.match(/\.upload-zone\.disabled\s*\{([^}]*)\}/)?.[1] ?? ''
    const normalizedDisabledRule = disabledRule.replace(/\s+/g, '')

    expect(workspaceSource).toContain('const uploadLimitReached = computed(() => assets.value.length >= 3)')
    expect(workspaceSource).toContain(':disabled="uploadLimitReached || uploading"')
    expect(workspaceSource).toContain(':aria-disabled="uploadLimitReached || uploading"')
    expect(workspaceSource).toContain("uploadLimitReached ? '最多上传 3 张'")
    expect(workspaceSource).toContain("uploadLimitReached ? '删除已有图片后可继续上传'")
    expect(workspaceSource).toContain("message.warning('最多上传 3 张商品图，请先删除已有图片')")
    expect(normalizedDisabledRule).toContain('cursor:not-allowed')
    expect(normalizedDisabledRule).toContain('opacity:.68')
  })

  it('removes the redundant suite panel title while keeping the mobile close control', () => {
    expect(workspaceSource).not.toContain('上传商品图，一键生成完整电商套图')
    expect(workspaceSource).not.toContain('class="panel-heading"')
    expect(workspaceSource).toContain('class="mobile-close"')
  })

  it('builds custom image allocation with a maximum of four per category', () => {
    const form = createDefaultWorkspaceForm()
    form.mode = 'custom'
    form.customCounts = { white_background: 1, scene: 2, selling_point: 2, other: 2 }
    expect(buildCustomTypes(form.customCounts)).toEqual([
      '白底图 1', '场景图 1', '场景图 2', '卖点图 1', '卖点图 2', '其他图 1', '其他图 2',
    ])
    expect(Object.values(form.customCounts).every((count) => count <= 4)).toBe(true)
  })

  it('keeps generation setting options aligned with DesignKit product-kit', () => {
    expect(platformOptions).toEqual([
      '亚马逊', '淘宝天猫', '1688', 'Temu', 'TikTok Shop', '拼多多', '抖音电商', 'OZON', '独立站',
      'Shopee', '阿里国际站', '速卖通', 'SHEIN', '京东', '美客多', 'Coupang', 'Wayfair',
    ])
    expect(marketOptions).toEqual(['美国', '欧洲', '中国', '俄罗斯', '东南亚', '西班牙', '德国', '日本', '韩国', '巴西', '墨西哥'])
    expect(languageOptions).toEqual(['英文', '中文', '俄语', '西语', '德语', '日语', '韩语', '葡萄牙语', '印尼语', '泰语', '无文字'])
    expect(ratioOptions).toEqual(['1:1', '3:4', '9:16', '16:9'])
    expect(ratioValues).toEqual({ '1:1': '1:1', '3:4': '3:4', '9:16': '9:16', '16:9': '16:9' })
    expect(createDefaultWorkspaceForm()).toMatchObject({ platform: '亚马逊', market: '美国', language: '英文', ratio: '1:1' })
  })

  it('hides model names behind business preferences', () => {
    expect(workspaceSource).toContain('商品保持优先')
    expect(workspaceSource).toContain('视觉排版优先')
    expect(workspaceSource).not.toContain('Nano Pro')
    expect(workspaceSource).not.toContain('Image 2')
  })

  it('places model preference as a dropdown directly under the selling points input', () => {
    const inputIndex = workspaceSource.indexOf('class="selling-points-input"')
    const selectorIndex = workspaceSource.indexOf('class="model-preference-row"')
    const suiteConfigIndex = workspaceSource.indexOf('class="form-section suite-config"')

    expect(inputIndex).toBeGreaterThan(-1)
    expect(selectorIndex).toBeGreaterThan(inputIndex)
    expect(selectorIndex).toBeLessThan(suiteConfigIndex)
    expect(workspaceSource).toContain('class="model-preference-trigger"')
    expect(workspaceSource).toContain('class="model-preference-menu"')
    expect(workspaceSource).toContain('selectModelPreference')
    expect(workspaceSource).not.toContain('Live 会读取商品图，并把这里的自然语言与视觉信息解析为结构化事实')
    expect(workspaceSource).not.toContain('class="preference-switch"')
  })

  it('keeps the model preference dropdown visually compact', () => {
    const triggerRule = workspaceSuiteCss.match(/\.model-preference-trigger\s*\{([^}]*)\}/)?.[1] ?? ''
    const titleRule = workspaceSuiteCss.match(/\.model-preference-row > span b\s*\{([^}]*)\}/)?.[1] ?? ''
    const descRule = workspaceSuiteCss.match(/\.model-preference-row > span small\s*\{([^}]*)\}/)?.[1] ?? ''
    const menuRule = workspaceSuiteCss.match(/\.model-preference-menu\s*\{([^}]*)\}/)?.[1] ?? ''
    const optionRule = workspaceSuiteCss.match(/\.model-preference-menu button\s*\{([^}]*)\}/)?.[1] ?? ''
    const normalizedTrigger = triggerRule.replace(/\s+/g, '')
    const normalizedTitle = titleRule.replace(/\s+/g, '')
    const normalizedDesc = descRule.replace(/\s+/g, '')
    const normalizedMenu = menuRule.replace(/\s+/g, '')
    const normalizedOption = optionRule.replace(/\s+/g, '')

    expect(normalizedTrigger).toContain('height:30px')
    expect(normalizedTrigger).toContain('font-size:12px')
    expect(normalizedTrigger).toContain('min-width:110px')
    expect(normalizedTitle).toContain('font-size:13px')
    expect(normalizedTitle).toContain('white-space:nowrap')
    expect(normalizedDesc).toContain('font-size:10px')
    expect(normalizedDesc).toContain('white-space:nowrap')
    expect(normalizedMenu).toContain('width:206px')
    expect(normalizedOption).toContain('min-height:46px')
  })

  it('uses smaller placeholder guidance in the selling points textarea', () => {
    const placeholderRule = workspaceSuiteCss.match(/\.selling-points-input::placeholder\s*\{([^}]*)\}/)?.[1] ?? ''
    const normalizedPlaceholder = placeholderRule.replace(/\s+/g, '')

    expect(normalizedPlaceholder).toContain('font-size:13px')
    expect(normalizedPlaceholder).toContain('line-height:1.5')
  })

  it('wires the new task button to a real reset action', () => {
    expect(workspaceSource).toContain('class="new-task" @click="startNewTask"')
  })

  it('passes structured product facts, brand style and all core prompt ratios', () => {
    const form = createDefaultWorkspaceForm()
    form.productName = '通勤保温杯'
    form.category = '饮水器具'
    form.brandStyle = '现代、克制、蓝灰色'
    form.smartCount = 9
    const payload = buildGenerationPayload(['asset-1'], '双层保温', form)
    expect(payload.product_name).toBe('通勤保温杯')
    expect(payload.category).toBe('饮水器具')
    expect(payload.brand_style).toBe('现代、克制、蓝灰色')
    expect(payload.count).toBe(7)
    expect(ratioOptions).toHaveLength(4)
  })

  it('keeps smart matching on the meta prompt default seven images without a count selector', () => {
    const form = createDefaultWorkspaceForm()
    form.mode = 'smart'
    form.smartCount = 12
    const payload = buildGenerationPayload(['asset-1'], '双层保温', form)

    expect(payload.count).toBe(7)
    expect(generationCount(form)).toBe(7)
    expect(workspaceSource).not.toContain('class="smart-count"')
    expect(workspaceSource).not.toContain('智能套图张数')
    expect(workspaceSource).not.toContain('v-model.number="form.smartCount"')
  })

  it('requires a generation strategy confirmation and wires failed retry to the API', () => {
    expect(workspaceSource).toContain('v-model:open="confirmOpen"')
    expect(workspaceSource).toContain('runConfirmedGeneration')
    expect(workspaceSource).toContain('retryFailedItems')
    expect(workspaceSource).not.toContain("@retry=\"message.info('仅失败项会进入重试')\"")
  })

  it('uses generation status copy without QA wording', () => {
    expect(workspaceSource).toContain('套图已生成')
    expect(workspaceSource).toContain('部分图片生成失败，可重试')
    expect(workspaceSource).not.toContain('质量审查')
    expect(workspaceSource).not.toContain('未通过')
  })

  it('does not render QA failure controls in result cards', () => {
    expect(resultGridSource).not.toContain('qa-failure-button')
    expect(resultGridSource).not.toContain('qa_status')
    expect(resultGridSource).not.toContain('qa_issues')
    expect(resultGridSource).not.toContain('QA 未通过原因')
    expect(resultGridSource).not.toContain('qa-failure-list')
  })

  it('hides image type names from result cards', () => {
    expect(resultGridSource).not.toContain('item.image_type')
    expect(resultGridSource).toContain('第 {{ item.index + 1 }} 张 · {{ item.status }}')
  })

  it('offers ZIP and long image download formats', () => {
    expect(workspaceSource).toContain('generationDownloadUrl')
    expect(workspaceSource).toContain("download('zip')")
    expect(workspaceSource).toContain("download('long_image')")
    expect(workspaceSource).toContain('下载套图 ZIP')
    expect(workspaceSource).toContain('下载长拼图 PNG')
    expect(workspaceSuiteCss).toContain('.download-menu-panel')
  })

  it('shows optimistic running cards immediately after generation confirmation', () => {
    expect(workspaceSource).toContain('function createOptimisticJob')
    expect(workspaceSource).toContain('function preservePendingJobItems')
    expect(workspaceSource).toContain("status: 'running'")
    expect(workspaceSource).toContain('job.value = createOptimisticJob(payload)')
    expect(workspaceSource).toContain('const created = preservePendingJobItems(await createJob(payload)); job.value = created')
  })

  it('polls running jobs frequently so finished cards appear without a refresh', () => {
    expect(workspaceSource).toContain('const IMAGE_JOB_POLL_INTERVAL_MS = 500')
    expect(workspaceSource).toContain('window.setTimeout(resolve, IMAGE_JOB_POLL_INTERVAL_MS)')
    expect(aplusPanelSource).toContain('const APLUS_JOB_POLL_INTERVAL_MS = 500')
    expect(aplusPanelSource).toContain('window.setTimeout(resolve, APLUS_JOB_POLL_INTERVAL_MS)')
    expect(videoPanelSource).toContain('const VIDEO_JOB_POLL_INTERVAL_MS = 1000')
    expect(videoPanelSource).toContain('window.setTimeout(resolve, VIDEO_JOB_POLL_INTERVAL_MS)')
  })

  it('uses a modal for content safety interception errors', () => {
    expect(workspaceSource).toContain("Modal.error({ title: '内容安全拦截'")
    expect(workspaceSource).toContain("detail.includes('安全拦截')")
  })

  it('previews AI copywriting before applying and supports regeneration', () => {
    expect(workspaceSource).toContain('aiSuggestion')
    expect(workspaceSource).toContain('aiWriteOpen')
    expect(workspaceSource).toContain('regenerateCopywriting')
    expect(workspaceSource).toContain('applyAiSuggestion')
    expect(workspaceSource).toContain('重新帮写')
    expect(workspaceSource).toContain('确认回填')
    expect(workspaceSource).toContain('<Teleport to="body">')
    expect(workspaceSource).not.toContain('form.value.sellingPoints = result.selling_points')
  })

  it('keeps main copywriting fields as stable textareas with automatic markdown preview on blur', () => {
    expect(renderMarkdown('### 1. 商品定位\n- 品名：<保温杯>')).toBe('<h3>1. 商品定位</h3><ul><li>品名：&lt;保温杯&gt;</li></ul>')
    expect(workspaceSource).toContain('class="markdown-input-frame selling-points-markdown-frame"')
    expect(workspaceSource).toContain('v-model="form.sellingPoints" class="selling-points-input"')
    expect(aplusPanelSource).toContain('v-model="form.productInfo" class="aplus-product-info selling-points-input"')
    expect(videoPanelSource).toContain('v-model="form.sellingPoints" class="selling-points-input video-selling-points-input"')
    expect(workspaceSource).toContain('form.sellingPoints.trim() && !sellingPointsEditing')
    expect(aplusPanelSource).toContain('form.productInfo.trim() && !productInfoEditing')
    expect(videoPanelSource).toContain('form.sellingPoints.trim() && !sellingPointsEditing')
    expect(workspaceSource).toContain('@focus="sellingPointsEditing = true" @blur="sellingPointsEditing = false"')
    expect(aplusPanelSource).toContain('@focus="productInfoEditing = true" @blur="productInfoEditing = false"')
    expect(videoPanelSource).toContain('@focus="sellingPointsEditing = true" @blur="sellingPointsEditing = false"')
    expect(workspaceSource).toContain('v-html="renderMarkdown(form.sellingPoints)"')
    expect(aplusPanelSource).toContain('v-html="renderMarkdown(form.productInfo)"')
    expect(videoPanelSource).toContain('v-html="renderMarkdown(form.sellingPoints)"')
    expect(workspaceSource).toContain('showSellingPointsEditor')
    expect(aplusPanelSource).toContain('showProductInfoEditor')
    expect(workspaceSuiteCss).not.toContain('.markdown-editor-toggle')
    expect(workspaceSource).toContain('class="markdown-input-frame ai-suggestion-markdown-frame"')
    expect(workspaceSource).toContain('v-html="renderMarkdown(aiSuggestion)"')
  })

  it('keeps structured facts behind the workflow and guides users in one textarea', () => {
    expect(createDefaultWorkspaceForm().sellingPoints).toBe('')
    expect(workspaceSource).toContain('商品卖点与要求')
    expect(workspaceSource).toContain('建议包含以下信息，帮助生成更精准')
    expect(workspaceSource).toContain('1. 商品名称')
    expect(workspaceSource).toContain('5. 具体参数')
    expect(workspaceSource).not.toContain('v-model="form.productName"')
    expect(workspaceSource).not.toContain('v-model="form.certifications"')
    expect(workspaceSource).not.toContain('v-model="form.brandStyle"')
    expect(workspaceSource).toContain('inputValid')
  })

  it('wires the video phase to the real video workspace instead of the demo panel', () => {
    expect(workspaceSource).toContain("import VideoPhasePanel from './VideoPhasePanel.vue'")
    expect(workspaceSource).toContain('<KeepAlive>')
    expect(workspaceSource).toContain('<VideoPhasePanel v-if="phase===\'video\'" ref="videoPanel" />')
    expect(workspaceSource).toContain('APlusPhasePanel v-if="phase===\'aplus\'" ref="aplusPanel"')
  })

  it('wires best-effort cancellation for suite, A+ and video jobs', () => {
    expect(apiClientSource).toContain('cancelJob')
    expect(apiClientSource).toContain('api.post(`/generation-jobs/${id}/cancel`)')
    expect(apiClientSource).toContain('api.post(`/aplus-plan-jobs/${id}/cancel`)')
    expect(apiClientSource).toContain('api.post(`/aplus-generation-jobs/${id}/cancel`)')
    expect(apiClientSource).toContain('api.post(`/video-jobs/${id}/cancel`)')
    expect(workspaceSource).toContain('cancelRequested.value')
    expect(workspaceSource).toContain('cancelGeneration')
    expect(aplusPanelSource).toContain('cancelAplusPlanJob')
    expect(aplusPanelSource).toContain('cancelAplusGenerationJob')
    expect(videoPanelSource).toContain('cancelVideoJob')
    expect(workspaceSource).toContain('取消任务')
    expect(aplusPanelSource).toContain('取消任务')
    expect(videoPanelSource).toContain('取消任务')
  })

  it('dispatches the topbar new-task action to the active module only', () => {
    expect(workspaceSource).toContain("if (phase.value === 'aplus')")
    expect(workspaceSource).toContain('aplusPanel.value?.startNewTask()')
    expect(workspaceSource).toContain("if (phase.value === 'video')")
    expect(workspaceSource).toContain('videoPanel.value?.startNewTask()')
    expect(workspaceSource).toContain('function resetSuiteTask')
    expect(workspaceSource).toContain('currentDryRun')
    expect(aplusPanelSource).toContain('defineExpose({ openHistoryJob, startNewTask, dryRun })')
    expect(videoPanelSource).toContain('defineExpose({ openHistoryJob, startNewTask, dryRun })')
  })

  it('clears AI copywriting and main inputs when product images change', () => {
    expect(workspaceSource).toContain('function clearCopywritingState')
    expect(workspaceSource).toContain("form.value.sellingPoints = ''")
    expect(workspaceSource).toContain('@click="removeAsset(asset.id)"')
    expect(aplusPanelSource).toContain('function clearCopywritingState')
    expect(aplusPanelSource).toContain("form.value.productInfo = ''")
    expect(aplusPanelSource).toContain('@click="removeAsset(asset.id)"')
    expect(videoPanelSource).toContain('function clearCopywritingState')
    expect(videoPanelSource).toContain("form.value.sellingPoints = ''")
    expect(videoPanelSource).toContain('@click="removeAsset(asset.id)"')
  })

  it('loads topbar history from the current workspace phase', () => {
    expect(apiClientSource).toContain("api.get('/aplus-generation-jobs')")
    expect(workspaceSource).toContain("if (phase.value === 'video') history.value = await listVideoJobs()")
    expect(workspaceSource).toContain("else if (phase.value === 'aplus') history.value = await listAplusGenerationJobs()")
    expect(workspaceSource).toContain("else if (phase.value === 'suite') history.value = await listJobs()")
    expect(workspaceSource).toContain("phase.value === 'video' ? '视频历史'")
    expect(workspaceSource).toContain("phase.value === 'aplus' ? 'A+ 详情历史'")
    expect(workspaceSource).toContain("await videoPanel.value?.openHistoryJob(entry as VideoJob)")
    expect(workspaceSource).toContain("await aplusPanel.value?.openHistoryJob(entry as AplusJob)")
  })

  it('wires A+ module cards to count steppers and one-click image generation', () => {
    expect(aplusPanelSource).toContain('selectedModuleTotal')
    expect(aplusPanelSource).toContain('plannedResultCount')
    expect(aplusPanelSource).toContain('toggleModule(module.name)')
    expect(aplusPanelSource).toContain('incrementModule(module.name)')
    expect(aplusPanelSource).toContain('decrementModule(module.name)')
    expect(aplusPanelSource).toContain('module.description')
    expect(aplusPanelSource).toContain('createOptimisticPlanJob')
    expect(aplusPanelSource).toContain('createOptimisticGenerationJob')
    expect(aplusPanelSource).toContain('const createdPlan = preservePendingAplusItems(await createAplusPlanJob(planPayload), planJob.value)')
    expect(aplusPanelSource).toContain('const createdGeneration = preservePendingAplusItems(await createAplusGenerationJob(generationPayload), generationJob.value)')
    expect(aplusPanelSource).toContain('生成图片 ${plannedResultCount} 张')
    expect(aplusPanelSource).not.toContain('生成模块方案 · 共 ${selectedModuleTotal} 张')
    expect(aplusPanelSource).not.toContain('确认模块后生成图片')
    expect(aplusPanelSource).not.toContain('模块方案确认后')
    expect(aplusPanelSource).toContain('详情页模块最多生成 ${APLUS_MODULE_TOTAL_LIMIT} 张')
  })

  it('shows A+ results as a single image grid and hides scripts behind card actions', () => {
    const workspaceRule = workspaceSuiteCss.match(/\.aplus-workspace\s*\{([^}]*)\}/)?.[1] ?? ''
    const gridRule = workspaceSuiteCss.match(/\.aplus-result-grid\s*\{([^}]*)\}/)?.[1] ?? ''
    const normalizedWorkspace = workspaceRule.replace(/\s+/g, '')
    const normalizedGrid = gridRule.replace(/\s+/g, '')

    expect(aplusPanelSource).not.toContain('class="aplus-plan-board"')
    expect(aplusPanelSource).not.toContain('class="aplus-plan-card"')
    expect(aplusPanelSource).toContain('previewItem')
    expect(aplusPanelSource).toContain('editAplusItem')
    expect(aplusPanelSource).toContain('A+ 二次编辑')
    expect(aplusPanelSource).toContain('generationOutputSummary')
    expect(aplusPanelSource).toContain('job.params.output_targets')
    expect(aplusPanelSource).not.toContain('outputTargets.map((target) => aplusTargetLabel(target.mode, target.aspect_ratio)).join')
    expect(aplusPanelSource).toContain('function scriptMarkdown')
    expect(aplusPanelSource).toContain('A+ 图片脚本')
    expect(aplusPanelSource).toContain('<PlayCircleOutlined />脚本')
    expect(apiClientSource).toContain('api.post(`/aplus-items/${id}/versions`')
    expect(resultGridSource).toContain('script: [item: JobItem]')
    expect(resultGridSource).toContain('PlayCircleOutlined')
    expect(normalizedWorkspace).toContain('display:block')
    expect(normalizedGrid).toContain('grid-template-columns:repeat(3,minmax(240px,1fr))')
    expect(workspaceSuiteCss).toContain('aspect-ratio: 1 / 1;')
    expect(workspaceSuiteCss).toContain('object-fit: contain;')
    expect(workspaceSuiteCss).toContain('.aplus-results > header > div:first-child')
    expect(workspaceSuiteCss).toContain('.aplus-result-actions')
    expect(workspaceSuiteCss).toContain('flex-wrap: nowrap;')
    expect(workspaceSuiteCss).toContain('white-space: nowrap;')
    expect(workspaceSuiteCss).toContain('.aplus-script-preview')
  })

  it('uses user-facing A+ upload guidance instead of implementation wording', () => {
    expect(aplusPanelSource).toContain('建议上传主图、细节图和场景图')
    expect(aplusPanelSource).toContain('删除已有图片后可继续上传')
    expect(aplusPanelSource).not.toContain('只传图时会先识别商品')
    expect(aplusPanelSource).not.toContain('严格按文字事实')
  })

  it('uses the prior skincare video detail empty state', () => {
    expect(videoPanelSource).toContain('/demo/video-skincare-source.png')
    expect(videoPanelSource).toContain('/demo/video-skincare-hero.png')
    expect(videoPanelSource).toContain('/demo/video-skincare-result.png')
    expect(videoPanelSource).toContain('/demo/video-skincare-frame-01.png')
    expect(videoPanelSource).toContain('/demo/video-skincare-frame-02.png')
    expect(videoPanelSource).toContain('/demo/video-skincare-frame-03.png')
    expect(videoPanelSource).toContain('爆款视频生成')
    expect(videoPanelSource).not.toContain('爆款视频复刻')
    expect(videoPanelSource).toContain('class="video-empty-stage"')
    expect(videoPanelSource).toContain('class="video-empty-copy"')
    expect(videoPanelSource).toContain('class="video-empty-visual"')
    expect(videoPanelSource).toContain('class="video-source-card"')
    expect(videoPanelSource).toContain('class="video-preview-phone"')
    expect(videoPanelSource).toContain('class="video-result-poster"')
    expect(videoPanelSource).toContain('class="video-frame-strip"')
    expect(videoPanelSource).not.toContain('const showcaseCards = [')
    expect(videoPanelSource).not.toContain('video-showcase-card')
    expect(videoPanelSource).not.toContain('class="video-source-rail"')
    expect(videoPanelSource).not.toContain('class="video-output-board"')
    expect(videoPanelSource).not.toContain('video-storyboard-matrix')
    expect(videoPanelSource).not.toContain('<span><PlayCircleOutlined /></span>')
    expect(videoPanelSource).not.toContain('/demo/video-backpack-showcase-')
    expect(videoPanelSource).not.toContain('/demo/tumbler-')
  })

  it('keeps the prior video detail visual composition in the light workspace', () => {
    const stageRule = workspaceVideoCss.match(/\.video-empty-stage\s*\{([^}]*)\}/)?.[1] ?? ''
    const mobileRule = workspaceVideoCss.match(/@media\(max-width: 760px\)\s*\{([\s\S]*)\}\s*$/)?.[1] ?? ''
    const normalizedStage = stageRule.replace(/\s+/g, '')
    const normalizedMobile = mobileRule.replace(/\s+/g, '')

    expect(workspaceVideoCss).toContain('.video-workspace { position: absolute; inset: 54px 0 0 72px; display: grid; grid-template-columns: 398px 1fr; background: #f3f4f6;')
    expect(normalizedStage).toContain('width:min(1080px,100%)')
    expect(normalizedStage).toContain('grid-template-columns:minmax(240px,300px)minmax(560px,1fr)')
    expect(workspaceVideoCss).toContain('.video-empty-copy h2')
    expect(workspaceVideoCss).toContain('.video-empty-visual')
    expect(workspaceVideoCss).toContain('.video-source-card')
    expect(workspaceVideoCss).toContain('.video-result-poster')
    expect(workspaceVideoCss).toContain('.video-preview-phone')
    expect(workspaceVideoCss).toContain('.video-frame-strip')
    expect(workspaceVideoCss).not.toContain('video-source-rail')
    expect(workspaceVideoCss).not.toContain('video-output-board')
    expect(workspaceVideoCss).not.toContain('video-showcase-card')
    expect(workspaceVideoCss).not.toContain('bg-black')
    expect(workspaceVideoCss).not.toContain('background: #000')
    expect(normalizedMobile).toContain('.video-empty-stage{min-height:auto;padding:0;grid-template-columns:1fr')
    expect(normalizedMobile).toContain('.video-source-card{left:0;top:88px')
    expect(normalizedMobile).toContain('.video-result-poster{left:98px;top:132px')
    expect(normalizedMobile).toContain('.video-empty-arrow{display:none')
  })

  it('uses five backpack showcase cards for the A+ detail empty state', () => {
    for (let index = 1; index <= 5; index += 1) {
      expect(aplusPanelSource).toContain(`/demo/video-backpack-showcase-${String(index).padStart(2, '0')}.png`)
    }
    expect(aplusPanelSource).toContain('const aplusShowcaseCards = [')
    expect(aplusPanelSource).toContain('class="aplus-empty-stage aplus-showcase-stage"')
    expect(aplusPanelSource).toContain('class="aplus-showcase-gallery"')
    expect(aplusPanelSource).toContain('class="aplus-showcase-card"')
    expect(aplusPanelSource).toContain('户外场景生成')
    expect(aplusPanelSource).toContain('卖点脚本策划')
    expect(aplusPanelSource).toContain('素材智能拆解')
    expect(aplusPanelSource).toContain('多平台详情适配')
    expect(aplusPanelSource).toContain('防水细节展示')
    expect(aplusPanelSource).not.toContain('class="aplus-source-rail"')
    expect(aplusPanelSource).not.toContain('class="aplus-output-board"')
    expect(aplusPanelSource).not.toContain('class="aplus-module-card hero"')
    expect(aplusPanelSource).not.toContain('/demo/aplus-outdoor-module-')
    expect(aplusPanelSource).not.toContain('/demo/tumbler-')
  })

  it('keeps the A+ showcase unframed, compact and horizontally scrollable on mobile', () => {
    const stageRule = workspaceSuiteCss.match(/\.aplus-empty-stage\.aplus-showcase-stage\s*\{([^}]*)\}/)?.[1] ?? ''
    const hoverRule = workspaceSuiteCss.match(/\.aplus-showcase-card:hover,[^{]+\.aplus-showcase-card:focus-visible\s*\{([^}]*)\}/)?.[1] ?? ''
    const mobileRule = workspaceSuiteCss.match(/\.aplus-showcase-gallery\s*\{\s*height: 336px;([^}]*)\}/)?.[1] ?? ''
    const normalizedStage = stageRule.replace(/\s+/g, '')
    const normalizedHover = hoverRule.replace(/\s+/g, '')
    const normalizedMobile = mobileRule.replace(/\s+/g, '')

    expect(normalizedStage).toContain('width:min(1040px,92%)')
    expect(normalizedStage).toContain('background:transparent')
    expect(normalizedStage).toContain('box-shadow:none')
    expect(normalizedStage).toContain('border:0')
    expect(normalizedHover).toContain('flex:1.9')
    expect(normalizedMobile).toContain('overflow-x:auto')
    expect(normalizedMobile).toContain('scroll-snap-type:xmandatory')
    expect(workspaceSuiteCss).not.toContain('bg-black')
    expect(workspaceSuiteCss).not.toContain('background: #000')
  })

  it('builds video payloads from the selected templates and platform settings', () => {
    const form = createDefaultVideoForm()
    form.videoTypes = ['UGC 种草', '痛点解决']
    form.sellingPoints = '便携、防漏、适合通勤'
    const payload = buildVideoPayload(['asset-1'], form)

    expect(payload.asset_ids).toEqual(['asset-1'])
    expect(payload.platform).toBe('TikTok')
    expect(payload.aspect_ratio).toBe('9:16')
    expect(payload.video_types).toEqual(['UGC 种草', '痛点解决'])
    expect(payload.duration).toBe(15)
    expect(payload.resolution).toBe('1080p')
    expect(payload).not.toHaveProperty('generate_audio')
    expect(payload).not.toHaveProperty('camera_fixed')
    expect(payload).not.toHaveProperty('watermark')
  })

  it('exposes the requested video platform and type options', () => {
    expect(videoPlatformOptions).toEqual(['TikTok', '抖音', '小红书', '淘宝', '亚马逊'])
    expect(videoTypeOptions.map((item) => item.key)).toEqual([
      '痛点解决',
      'UGC 种草',
      '达人口播',
      '测评对比',
      '短剧搞笑带货',
      '视觉展示',
      '反转剧情',
      '清单榜单推荐',
    ])
  })

  it('creates optimistic video cards immediately and calls the video APIs', () => {
    expect(videoPanelSource).toContain('function createOptimisticVideoJob')
    expect(videoPanelSource).toContain("status: 'running'")
    expect(videoPanelSource).toContain('job.value = createOptimisticVideoJob(payload)')
    expect(videoPanelSource).toContain('createVideoJob(payload)')
    expect(videoPanelSource).toContain('waitForVideoJob(created.id)')
    expect(apiClientSource).toContain("api.post('/video-jobs'")
    expect(apiClientSource).toContain("api.post('/video-copywriting-assist'")
    expect(apiClientSource).toContain('/api/v1/video-jobs/')
  })

  it('renders video result actions for preview, download and retry', () => {
    expect(videoPanelSource).toContain('下载选中')
    expect(videoPanelSource).toContain('重试失败')
    expect(videoPanelSource).toContain('视频导演脚本')
    expect(videoPanelSource).toContain('远程任务号 {{ item.provider_task_id }}')
    expect(videoPanelSource).toContain('AI 转写')
    expect(videoPanelSource).toContain('安全演示模式')
  })
})
