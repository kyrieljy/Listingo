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
  isActiveWorkspaceJob,
  languageOptions,
  latestActiveWorkspaceJob,
  marketOptions,
  platformOptions,
  previewAspectStyle,
  PRODUCT_IMAGE_UPLOAD_LIMIT,
  phaseDefinitions,
  renderMarkdown,
  ratioOptions,
  ratioValues,
  videoPlatformOptions,
  videoTypeOptions,
} from './workspace-model'
import {
  BATCH_UPLOAD_CONCURRENCY,
  batchValidationSummary,
  buildBatchPayload,
  createBatchGlobalParams,
  createDefaultBatchTasks,
  createBatchTaskDraft,
  estimateBatchOutputs,
  estimateTaskOutputs,
  extractBatchProductName,
} from './batch-model'
import resultGridSource from './ResultGrid.vue?raw'
import aplusPanelRawSource from './APlusPhasePanel.vue?raw'
import generationErrorsRawSource from './generation-errors.ts?raw'
import batchHistoryRawSource from './BatchHistoryDrawer.vue?raw'
import batchModalRawSource from './BatchHostingModal.vue?raw'
import batchTaskCardSource from './BatchTaskCard.vue?raw'
import imageTextEditPanelSource from './ImageTextEditPanel.vue?raw'
import watermarkMenuSource from './WatermarkDownloadMenu.vue?raw'
import videoPanelRawSource from './VideoPhasePanel.vue?raw'
import workspaceRawSource from './WorkspaceView.vue?raw'
import apiClientSource from '../../api/client.ts?raw'

const normalizeSourceLineEndings = (source: string) => source.replace(/\r\n/g, '\n').replace(/\r/g, '\n')
const aplusPanelSource = normalizeSourceLineEndings(aplusPanelRawSource)
const batchHistorySource = normalizeSourceLineEndings(batchHistoryRawSource)
const batchModalSource = normalizeSourceLineEndings(batchModalRawSource)
const videoPanelSource = normalizeSourceLineEndings(videoPanelRawSource)
const workspaceSource = normalizeSourceLineEndings(workspaceRawSource)
const workspaceSuiteCss = readFileSync(new URL('./workspace-suite.css', import.meta.url), 'utf8')
const workspaceVideoCss = readFileSync(new URL('./workspace-video.css', import.meta.url), 'utf8')
const frontendNginxConf = readFileSync(new URL('../../../nginx.conf', import.meta.url), 'utf8')

describe('workspace model', () => {
  it('keeps the four planned phase entries in order', () => {
    expect(phaseDefinitions.map((item) => item.label)).toEqual([
      '商品套图',
      'A+详情',
      '爆款视频生成',
      'Agent与画布',
    ])
  })

  it('closes the Agent phase entry as a disabled coming soon nav item', () => {
    const disabledRule = workspaceSuiteCss.match(/\.phase-rail button\.disabled\s*\{([^}]*)\}/)?.[1] ?? ''
    const badgeRule = workspaceSuiteCss.match(/\.phase-rail \.phase-soon-badge\s*\{([^}]*)\}/)?.[1] ?? ''
    const normalizedDisabledRule = disabledRule.replace(/\s+/g, '')
    const normalizedBadgeRule = badgeRule.replace(/\s+/g, '')

    expect(workspaceSource).toContain("const disabledPhaseKeys = new Set<PhaseKey>(['agent'])")
    expect(workspaceSource).toContain('!isPhaseDisabled(item.key)')
    expect(workspaceSource).toContain('if (isPhaseDisabled(key)) return')
    expect(workspaceSource).toContain(':class="{ active: phase === item.key, disabled: isPhaseDisabled(item.key) }"')
    expect(workspaceSource).toContain(':disabled="isPhaseDisabled(item.key)"')
    expect(workspaceSource).toContain(':aria-disabled="isPhaseDisabled(item.key)"')
    expect(workspaceSource).toContain('class="phase-soon-badge">即将上线</small>')
    expect(normalizedDisabledRule).toContain('cursor:not-allowed')
    expect(normalizedDisabledRule).toContain('opacity:.68')
    expect(normalizedBadgeRule).toContain('border-radius:99px')
    expect(normalizedBadgeRule).toContain('white-space:nowrap')
  })

  it('selects the newest unfinished workspace job across history payloads', () => {
    const jobs = [
      { id: 'done-latest', status: 'succeeded', created_at: '2026-08-11T10:00:00.000Z' },
      { id: 'running-old', status: 'running', created_at: '2026-08-11T08:00:00.000Z' },
      { id: 'queued-new', status: 'queued', created_at: '2026-08-11T09:00:00.000Z' },
      { id: 'cancelling-newer', status: 'cancelling', created_at: '2026-08-11T12:00:00.000Z' },
      { id: 'failed-newer', status: 'failed', created_at: '2026-08-11T11:00:00.000Z' },
    ]

    expect(isActiveWorkspaceJob(jobs[0])).toBe(false)
    expect(isActiveWorkspaceJob(jobs[1])).toBe(true)
    expect(isActiveWorkspaceJob(jobs[3])).toBe(false)
    expect(latestActiveWorkspaceJob(jobs)?.id).toBe('queued-new')
  })

  it('builds a valid default dryrun payload', () => {
    const payload = buildGenerationPayload(['asset-1'], '通勤保温，防滑握持')
    expect(payload.dry_run).toBe(true)
    expect(payload.count).toBe(7)
    expect(payload.aspect_ratio).toBe('1:1')
    expect(payload.asset_ids).toEqual(['asset-1'])
  })

  it('parses result preview aspect ratios for contained watermark placement', () => {
    expect(previewAspectStyle('970:600')).toEqual({
      '--preview-aspect-ratio': '970 / 600',
      '--preview-aspect-number': String(970 / 600),
    })
    expect(previewAspectStyle('16/9')).toEqual({
      '--preview-aspect-ratio': '16 / 9',
      '--preview-aspect-number': String(16 / 9),
    })
    expect(previewAspectStyle('bad')).toEqual({
      '--preview-aspect-ratio': '1 / 1',
      '--preview-aspect-number': '1',
    })
  })

  it('builds batch payloads with inherited globals and item overrides only', () => {
    const suiteForm = createDefaultWorkspaceForm()
    suiteForm.mode = 'custom'
    suiteForm.customCounts = { white_background: 4, scene: 4, selling_point: 2, other: 2 }
    const globalParams = { ...createBatchGlobalParams('suite', suiteForm), platform: 'Amazon' }
    const task = createBatchTaskDraft(1)
    task.sellingPoints = '### 1. 商品定位\n- 品名： 防滑随行保温杯\n- 核心卖点：Waterproof'
    task.assets = [{ id: 'asset-1', original_name: 'a.png', url: '/a.png', width: 100, height: 100 }]
    task.overrides = { market: 'Canada' }

    const payload = buildBatchPayload('suite', globalParams, [task])

    expect(payload.business_type).toBe('suite')
    expect(payload.global_params).toMatchObject({ platform: 'Amazon', count: 7, mode: 'smart' })
    expect(payload.global_params).not.toHaveProperty('custom_counts')
    expect(payload.items[0]).toMatchObject({
      asset_ids: ['asset-1'],
      name: '防滑随行保温杯',
      selling_points: '### 1. 商品定位\n- 品名： 防滑随行保温杯\n- 核心卖点：Waterproof',
      overrides: { market: 'Canada' },
    })
  })

  it('extracts batch product names only from explicit product-name labels', () => {
    expect(extractBatchProductName('### 1. 商品定位\n- 品名： 突出产品用途、材质体验与使用场景')).toBe('突出产品用途、材质体验与使用场景')
    expect(extractBatchProductName('1、商品名称: 米色硅胶防滑不锈钢随行 tumbler')).toBe('米色硅胶防滑不锈钢随行 tumbler')
    expect(extractBatchProductName('### 1. 商品定位\n- 核心卖点：防滑保温')).toBe('')
    expect(extractBatchProductName('- 品名： ---')).toBe('')
  })

  it('validates batch limits from workspace config and estimates outputs', () => {
    const config = { max_upload_bytes: 1, max_batch_tasks: 2, max_batch_item_assets: 2, max_active_batch_items: 1, max_provider_concurrency: 4 }
    const complete = createBatchTaskDraft(1)
    complete.assets = [{ id: 'asset-1', original_name: 'a.png', url: '/a.png', width: 100, height: 100 }]
    complete.sellingPoints = 'Durable'
    const incomplete = createBatchTaskDraft(2)
    incomplete.uploadError = 'failed'

    const summary = batchValidationSummary('suite', [complete, incomplete], { count: 8 }, config)

    expect(summary.taskCount).toBe(2)
    expect(summary.estimatedImages).toBe(14)
    expect(summary.uploadFailedCount).toBe(1)
    expect(summary.incompleteCount).toBe(1)
    expect(estimateBatchOutputs('aplus', { module_selections: [{ count: 2 }], output_targets: [{}, {}] })).toBe(4)
    expect(estimateTaskOutputs('aplus', { module_selections: [{ count: 2 }], output_targets: [{}] }, { module_selections: [{ count: 4 }] })).toBe(4)
    expect(batchValidationSummary('aplus', [complete], { module_selections: [], output_targets: [] }, config).incompleteCount).toBe(1)
  })

  it('wires batch hosting modal, config endpoint, upload concurrency and history actions', () => {
    expect(BATCH_UPLOAD_CONCURRENCY).toBe(3)
    expect(createDefaultBatchTasks()).toHaveLength(2)
    expect(apiClientSource).toContain("api.get('/workspace-config')")
    expect(apiClientSource).toContain('const GENERATION_REQUEST_TIMEOUT_MS = 900_000')
    expect(apiClientSource).toContain("api.post('/batch-jobs', payload, { timeout: GENERATION_REQUEST_TIMEOUT_MS })")
    expect(apiClientSource).toContain("api.post('/batch-jobs/validation-fixtures', { business_type: businessType }, { timeout: GENERATION_REQUEST_TIMEOUT_MS })")
    expect(apiClientSource).toContain('/api/v1/batch-jobs/selection-download')
    expect(workspaceSource).toContain("import BatchHostingModal from './BatchHostingModal.vue'")
    expect(workspaceSource).toContain('批量生成托管')
    expect(aplusPanelSource).toContain('批量生成托管')
    expect(workspaceSource).toContain('business-type="suite"')
    expect(aplusPanelSource).toContain('business-type="aplus"')
    expect(batchModalSource).toContain('getWorkspaceConfig')
    expect(batchModalSource).toContain('BATCH_UPLOAD_CONCURRENCY')
    expect(batchModalSource).toContain('aiWriteRuns')
    expect(batchModalSource).toContain('nextAiWriteRun')
    expect(batchModalSource).toContain('invalidateAiWriteRun')
    expect(batchModalSource).toContain('submitButtonDisabled')
    expect(batchModalSource).toContain('function clearBatchDraft()')
    expect(batchModalSource).toContain("trackBatchEvent('batch_clear_click', 'click')")
    expect(batchModalSource).toContain('aiWriteRuns.clear()')
    expect(batchModalSource).toContain(':disabled="submitting" @click="clearBatchDraft"')
    expect(batchModalSource).toContain('if (!latest || latest.id !== taskId) return')
    expect(batchModalSource).toContain('showSubmitValidation')
    expect(batchModalSource).toContain('缺少商品图')
    expect(batchModalSource).toContain(':disabled="submitButtonDisabled"')
    expect(batchModalSource).toContain('extractBatchProductName(task.sellingPoints)')
    expect(batchModalSource).toContain('createDefaultBatchTasks')
    expect(batchModalSource).toContain(':can-delete="tasks.length > 1"')
    expect(batchTaskCardSource).toContain('config.max_batch_item_assets')
    expect(batchTaskCardSource).toContain('batch-task-summary-card')
    expect(batchTaskCardSource).toContain('validationMessages')
    expect(batchTaskCardSource).toContain(':class="{ invalid: highlighted }"')
    expect(batchTaskCardSource).toContain('CopyOutlined')
    expect(batchTaskCardSource).toContain('跟随全局-平台')
    expect(batchTaskCardSource).toContain('跟随全局-生成偏好')
    expect(batchHistorySource).toContain('createBatchValidationFixtures')
    expect(batchHistorySource).toContain('selectTasks')
    expect(batchHistorySource).toContain('completed_image_count')
    expect(batchHistorySource).toContain('thumbnail_url')
    expect(batchHistorySource).toContain("queued: '等待中'")
    expect(batchHistorySource).toContain("running: '生成中'")
    expect(batchHistorySource).toContain("succeeded: '已生成'")
    expect(batchHistorySource).toContain("partial_failed: '失败'")
    expect(batchHistorySource).toContain("cancelled: '已取消'")
    expect(batchHistorySource).toContain('cancelBatchJob')
    expect(batchHistorySource).toContain('批量任务正在生成中，无法取消')
    expect(batchHistorySource).toContain('batch-task-generating')
    expect(batchHistorySource).toContain('width="600"')
    expect(batchHistorySource).toContain('batch-history-batch-main')
    expect(batchHistorySource).toContain(':class="{ checked: taskChecked(item.id) }"')
    expect(batchHistorySource).toContain('if (selectedCount.value > 0)')
    expect(batchHistorySource).toContain('toggleTask(item)')
    expect(batchHistorySource).not.toContain('batch-progress-track')
    expect(workspaceSuiteCss).not.toContain('.batch-progress-track')
    expect(batchHistorySource).not.toContain('retryFailedBatchJob')
    expect(batchHistorySource).not.toContain('batchDownloadUrl')
    expect(batchModalSource).toContain('任务已在后台运行，可在消息中心查看结果')
    expect(batchModalSource).toContain('selectHistory: [BatchSelectionPayload]')
    expect(workspaceSource).toContain('openSuiteBatchSelection')
    expect(aplusPanelSource).toContain('openBatchSelection')
    expect(workspaceSource).toContain('batch-suite-workspace')
    expect(aplusPanelSource).toContain('batch-aplus-workspace')
    expect(workspaceSource).toContain('downloadSuiteBatchGroup')
    expect(aplusPanelSource).toContain('downloadAplusBatchGroup')
    expect(workspaceSource).toContain('toggleSelectionScope')
    expect(aplusPanelSource).toContain('toggleSelectionScope')
    expect(workspaceSource).toContain('toggleSuiteBatchSuccess')
    expect(aplusPanelSource).toContain('toggleAplusBatchSuccess')
    expect(workspaceSource).toContain('toggleSuiteGroupSuccess')
    expect(aplusPanelSource).toContain('toggleAplusGroupSuccess')
    expect(workspaceSource).toContain('toggleSuiteJobSuccess')
    expect(aplusPanelSource).toContain('toggleGenerationSuccess')
    expect(workspaceSource).toContain("{{ batchSuiteAllSelected ? '取消全选' : '全选成功项' }}")
    expect(aplusPanelSource).toContain("{{ batchAplusAllSelected ? '取消全选' : '全选成功项' }}")
    expect(workspaceSource).toContain('selected.value = []')
    expect(aplusPanelSource).toContain('selectedResultIds.value = []')
    expect(workspaceSource).not.toContain('selected.value = batchSuiteSuccessfulIds.value')
    expect(aplusPanelSource).not.toContain('selectedResultIds.value = batchAplusSuccessfulIds.value')
    expect(resultGridSource).toContain('@click.stop="emit(\'toggle\', item.id)"')
    expect(aplusPanelSource).toContain('@click.stop="toggleResult(item.id)"')
    expect(workspaceSource).toContain('button-label="下载"')
    expect(aplusPanelSource).toContain('button-label="下载"')
    expect(workspaceSource).toContain("batchSelectionDownloadUrl('suite'")
    expect(aplusPanelSource).toContain("batchSelectionDownloadUrl('aplus'")
    expect(workspaceSuiteCss).toContain('.batch-result-group-actions')
    expect(workspaceSuiteCss).toContain('.batch-group-download-menu .download-button')
    expect(workspaceSuiteCss).toContain('min-width: 74px;')
    expect(workspaceSource).toContain("{{ suiteGroupAllSelected(group) ? '取消全选' : '全选本任务' }}")
    expect(aplusPanelSource).toContain("{{ aplusGroupAllSelected(group) ? '取消全选' : '全选本任务' }}")
    expect(workspaceSource).not.toContain('取消本任务')
    expect(aplusPanelSource).not.toContain('取消本任务')
    expect(workspaceSuiteCss).toContain('grid-template-columns: 200px 330px;')
    expect(workspaceSuiteCss).toContain('width: 542px;')
    expect(workspaceSuiteCss).toContain('overflow-x: hidden;')
    expect(workspaceSuiteCss).toContain('object-fit: contain;')
    expect(batchModalSource).toContain('批量生成托管')
    expect(batchModalSource).not.toContain('请选择托管业务类型')
    expect(batchModalSource).not.toContain('生成张数')
    expect(batchModalSource).not.toContain('模型偏好')
    expect(batchModalSource).toContain('生成偏好')
    expect(batchTaskCardSource).not.toContain('<input :value="task.name"')
    expect(batchTaskCardSource).toContain('ref="copyInput"')
    expect(batchTaskCardSource).toContain('@pointerdown.stop="openCopyEditor"')
    expect(batchTaskCardSource).toContain('class="markdown-preview main-copy-preview"')
    expect(batchTaskCardSource).toContain('task.sellingPoints.trim() && !task.copyEditing')
    expect(batchTaskCardSource).toContain('v-html="renderMarkdown(task.sellingPoints)"')
    expect(batchTaskCardSource).toContain('copyEditing: false')
    expect(batchTaskCardSource).toContain('确认回填')
    expect(batchTaskCardSource).toContain('extractBatchProductName(props.task.sellingPoints)')
    expect(batchTaskCardSource).toContain('nextTask.aiWriteOpen = false')
    expect(batchTaskCardSource).toContain('nextTask.aiSuggestion =')
    expect(workspaceSuiteCss).toContain('.batch-global-grid.suite-global-grid')
    expect(workspaceSuiteCss).toContain('.batch-summary-media')
    expect(workspaceSuiteCss).toContain('.batch-submit-notice')
    expect(workspaceSuiteCss).toContain('.batch-task-card.invalid')
    expect(apiClientSource).toContain('/aplus-items/${id}/retry')
    expect(apiClientSource).toContain("api.post('/aplus-plan-jobs', payload, { timeout: GENERATION_REQUEST_TIMEOUT_MS })")
    expect(apiClientSource).toContain("api.post('/aplus-generation-jobs', payload, { timeout: GENERATION_REQUEST_TIMEOUT_MS })")
    expect(apiClientSource).toContain('api.post(`/aplus-generation-jobs/${jobId}/retry-failed`, undefined, { timeout: GENERATION_REQUEST_TIMEOUT_MS })')
    expect(apiClientSource).toContain('api.post(`/aplus-items/${id}/retry`, undefined, { timeout: GENERATION_REQUEST_TIMEOUT_MS })')
    expect(aplusPanelSource).toContain('retryFailedAplusItems')
    expect(aplusPanelSource).toContain('retryAplusItem')
    expect(aplusPanelSource).toContain('重试失败项')
    expect(aplusPanelSource).toContain('title="重新生成"')
  })

  it('shows selected output size and exits editing mode after AI backfill', () => {
    expect(resultGridSource).toContain('selectedSizeLabel')
    expect(resultGridSource).toContain('class="image-size-meta"')
    expect(workspaceSuiteCss).toContain('.image-size-meta')
    expect(resultGridSource).not.toContain('naturalImageSizes')
    expect(resultGridSource).not.toContain('imageSizeLabel')
    expect(aplusPanelSource).not.toContain('naturalImageSizes')
    expect(aplusPanelSource).not.toContain('imageSizeLabel')
    expect(aplusPanelSource).not.toContain('class="image-size-meta"')
    expect(resultGridSource).not.toContain('class="image-size-badge"')
    expect(aplusPanelSource).not.toContain('class="image-size-badge"')
    expect(workspaceSuiteCss).not.toContain('.image-size-badge')
    expect(workspaceSource).toContain('sellingPointsEditing.value = false')
    expect(videoPanelSource).toContain('sellingPointsEditing.value = false')
    expect(aplusPanelSource).toContain('productInfoEditing.value = false')
  })

  it('keeps batch A+ configuration aligned with the main A+ panel', () => {
    expect(batchModalSource).toContain('aplusModules')
    expect(batchModalSource).toContain('moduleCount(module.name)')
    expect(batchModalSource).toContain('incrementModule(module.name)')
    expect(batchModalSource).toContain('decrementModule(module.name)')
    expect(batchModalSource).toContain('普通 A+ 和高级 A+ 仅亚马逊平台可用')
    expect(batchModalSource).toContain('availableAplusOutputSpecs')
    expect(batchModalSource).toContain('buildAplusOutputTargets')
    expect(batchTaskCardSource).toContain('跟随全局-输出规格')
    expect(batchTaskCardSource).toContain('itemOutputSpecChoices')
    expect(batchTaskCardSource).toContain('applyAplusOutputOverride')
    expect(batchTaskCardSource).toContain('batch-override-module-panel')
    expect(batchTaskCardSource).toContain('setTaskModuleFollow')
    expect(batchTaskCardSource).toContain(':aria-pressed="taskFollowsGlobalModules"')
    expect(batchTaskCardSource).toContain('class="aplus-module-option batch-module-option batch-task-module-option"')
    expect(batchTaskCardSource).toContain('module.description')
    expect(batchTaskCardSource).toContain('batch-task-module-stepper')
    expect(batchTaskCardSource).toContain('module_selections')
    expect(batchTaskCardSource).not.toContain('checkedValue($event)')
    expect(batchTaskCardSource).not.toContain("v-if=\"businessType === 'aplus'\">比例")
    expect(createBatchGlobalParams('aplus').module_selections).toEqual(createDefaultAplusForm().selectedModules)
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

  it('disables the upload entry and shows a clear hint after six product images', () => {
    const disabledRule = workspaceSuiteCss.match(/\.upload-zone\.disabled\s*\{([^}]*)\}/)?.[1] ?? ''
    const normalizedDisabledRule = disabledRule.replace(/\s+/g, '')

    expect(PRODUCT_IMAGE_UPLOAD_LIMIT).toBe(6)
    expect(workspaceSource).toContain('const uploadLimitReached = computed(() => assets.value.length >= PRODUCT_IMAGE_UPLOAD_LIMIT)')
    expect(aplusPanelSource).toContain('const uploadLimitReached = computed(() => assets.value.length >= PRODUCT_IMAGE_UPLOAD_LIMIT)')
    expect(videoPanelSource).toContain('const uploadLimitReached = computed(() => assets.value.length >= PRODUCT_IMAGE_UPLOAD_LIMIT)')
    expect(workspaceSource).toContain('const remaining = PRODUCT_IMAGE_UPLOAD_LIMIT - assets.value.length')
    expect(aplusPanelSource).toContain('const remaining = PRODUCT_IMAGE_UPLOAD_LIMIT - assets.value.length')
    expect(videoPanelSource).toContain('const remaining = PRODUCT_IMAGE_UPLOAD_LIMIT - assets.value.length')
    expect(workspaceSource).toContain(':disabled="uploadLimitReached || uploading"')
    expect(workspaceSource).toContain(':aria-disabled="uploadLimitReached || uploading"')
    expect(workspaceSource).toContain("uploadLimitReached ? `最多上传 ${PRODUCT_IMAGE_UPLOAD_LIMIT} 张`")
    expect(aplusPanelSource).toContain("uploadLimitReached ? `最多上传 ${PRODUCT_IMAGE_UPLOAD_LIMIT} 张`")
    expect(videoPanelSource).toContain("uploadLimitReached ? `最多上传 ${PRODUCT_IMAGE_UPLOAD_LIMIT} 张`")
    expect(workspaceSource).toContain("uploadLimitReached ? '删除已有图片后可继续上传'")
    expect(workspaceSource).toContain('最多上传 ${PRODUCT_IMAGE_UPLOAD_LIMIT} 张商品图，请先删除已有图片')
    expect(aplusPanelSource).toContain('最多上传 ${PRODUCT_IMAGE_UPLOAD_LIMIT} 张商品图，本次只添加 ${remaining} 张')
    expect(videoPanelSource).toContain('最多上传 ${PRODUCT_IMAGE_UPLOAD_LIMIT} 张商品图，本次只添加 ${remaining} 张')
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

  it('removes product category from workspace inputs and upload analytics payloads', () => {
    expect(workspaceSource).not.toContain('商品类目')
    expect(aplusPanelSource).not.toContain('商品类目')
    expect(videoPanelSource).not.toContain('商品类目')
    expect(workspaceSource).not.toContain('product_category: form.value.category')
    expect(aplusPanelSource).not.toContain('product_category: form.value.category')
    expect(videoPanelSource).not.toContain('product_category: form.value.category')
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
    expect(workspaceSource).toContain('retryItem')
    expect(workspaceSource).toContain('async function retrySingleItem(item: JobItem)')
    expect(workspaceSource).toContain('@retry="retrySingleItem"')
    expect(apiClientSource).toContain('api.post(`/generation-items/${id}/retry`, undefined, { timeout: GENERATION_REQUEST_TIMEOUT_MS })')
    expect(apiClientSource).toContain('api.post(`/generation-jobs/${jobId}/retry-failed`, undefined, { timeout: GENERATION_REQUEST_TIMEOUT_MS })')
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
    expect(workspaceSource).toContain('WatermarkDownloadMenu')
    expect(workspaceSource).toContain("format: 'zip'")
    expect(workspaceSource).toContain("format: 'long_image'")
    expect(workspaceSource).toContain('下载套图 ZIP')
    expect(workspaceSource).toContain('下载长拼图 PNG')
    expect(aplusPanelSource).toContain('下载 A+ ZIP')
    expect(aplusPanelSource).toContain('下载长拼图 PNG')
    expect(watermarkMenuSource).toContain('buttonLabel?: string')
    expect(watermarkMenuSource).toContain("buttonLabel: '下载选中'")
    expect(watermarkMenuSource).toContain('{{ buttonLabel }}')
    expect(watermarkMenuSource).toContain("openMenu === 'formats'")
    expect(workspaceSuiteCss).toContain('.download-menu-panel')
    expect(workspaceSuiteCss).toContain('.download-format-panel')
  })

  it('routes image downloads through watermark preferences', () => {
    expect(apiClientSource).toContain('include_watermark: String(includeWatermark)')
    expect(workspaceSource).toContain('const includeWatermark = ref(true)')
    expect(workspaceSource).toContain('const batchSuiteWatermarkByItemId = ref<Record<string, boolean>>({})')
    expect(workspaceSource).toContain('function updateSuiteGroupIncludeWatermark')
    expect(workspaceSource).toContain('function suiteGroupIncludeWatermark')
    expect(workspaceSource).toContain("batchSelectionDownloadUrl('suite', [group.item.id], itemIds, format, suiteGroupIncludeWatermark(group))")
    expect(workspaceSource).toContain(':include-watermark="suiteGroupIncludeWatermark(group)"')
    expect(workspaceSource).toContain('@update:include-watermark="(value) => updateSuiteGroupIncludeWatermark(group, value)"')
    expect(workspaceSource).toContain(':show-watermark="suiteGroupIncludeWatermark(group)"')
    expect(workspaceSource).toContain('v-if="activeItemIncludeWatermark"')
    expect(workspaceSource).toContain('generationDownloadUrl(job.value.id, itemIds, format, includeWatermark.value)')
    expect(workspaceSource).toContain(':show-watermark="includeWatermark"')
    expect(resultGridSource).toContain('/watermarks/ai-generated-badge-v2.svg')
    expect(resultGridSource).toContain('image-watermark-box')
    expect(aplusPanelSource).toContain('const batchAplusWatermarkByItemId = ref<Record<string, boolean>>({})')
    expect(aplusPanelSource).toContain('function updateAplusGroupIncludeWatermark')
    expect(aplusPanelSource).toContain('function aplusGroupIncludeWatermark')
    expect(aplusPanelSource).toContain("batchSelectionDownloadUrl('aplus', [group.item.id], itemIds, format, aplusGroupIncludeWatermark(group))")
    expect(aplusPanelSource).toContain(':include-watermark="aplusGroupIncludeWatermark(group)"')
    expect(aplusPanelSource).toContain('@update:include-watermark="(value) => updateAplusGroupIncludeWatermark(group, value)"')
    expect(aplusPanelSource).toContain('v-if="aplusGroupIncludeWatermark(group)"')
    expect(aplusPanelSource).toContain('v-if="previewItemIncludeWatermark"')
    expect(aplusPanelSource).toContain('aplusDownloadUrl(generationJob.value.id, itemIds, format, includeWatermark.value)')
    expect(aplusPanelSource).toContain("@upgrade=\"emit('open-pricing')\"")
    expect(workspaceSuiteCss).toContain('.ai-watermark-overlay')
    expect(workspaceSuiteCss).toContain('.image-watermark-box')
    expect(workspaceSuiteCss).toContain('.watermark-download-panel')
    expect(watermarkMenuSource).toContain("openMenu === 'watermark'")
    expect(watermarkMenuSource).toContain('watermark-upgrade-link')
  })

  it('tracks core workspace actions for business monitoring', () => {
    expect(apiClientSource).toContain('/analytics/events')
    expect(workspaceSource).toContain("import { trackWorkspaceEvent } from './analytics'")
    expect(workspaceSource).toContain('suite_generate_submit')
    expect(workspaceSource).toContain('suite_batch_click')
    expect(workspaceSource).toContain('suite_download')
    expect(aplusPanelSource).toContain('aplus_output_spec_click')
    expect(aplusPanelSource).toContain('aplus_module_click')
    expect(aplusPanelSource).toContain('aplus_generate_submit')
    expect(videoPanelSource).toContain('video_type_click')
    expect(videoPanelSource).toContain('video_generate_submit')
    expect(batchModalSource).toContain('batch_submit')
  })

  it('requires login before home workspace model-backed actions', () => {
    expect(workspaceSource).toContain('function requireAuthForModelAction(): boolean')
    expect(workspaceSource).not.toContain("message.info('请先登录后再使用 AI 生成功能')")
    expect(workspaceSource).toMatch(
      /function openSuiteBatch\(\)\s*\{\s*trackSuiteEvent\('suite_batch_click', 'click', 'batch_suite'\)\s*if \(requireAuthForModelAction\(\)\) return/,
    )
    expect(workspaceSource).toContain('@require-auth="requireAuthForModelAction"')
    expect(workspaceSource).toContain('<APlusPhasePanel v-if="phase===\'aplus\'" ref="aplusPanel" @open-pricing="openPricing" @require-auth="requireAuthForModelAction" />')
    expect(workspaceSource).toContain('<VideoPhasePanel v-if="phase===\'video\'" ref="videoPanel" @require-auth="requireAuthForModelAction" />')
    expect(workspaceSource).toContain('<BatchHostingModal v-model:open="suiteBatchOpen" business-type="suite" :suite-form="form" @select-history="openSuiteBatchSelection" @require-auth="requireAuthForModelAction" />')

    expect(aplusPanelSource).toContain("'require-auth': []")
    expect(aplusPanelSource).toContain('function openBatchHosting()')
    expect(aplusPanelSource).toContain("trackAplusEvent('aplus_batch_click', 'click', 'batch_aplus')")
    expect(aplusPanelSource).toContain('@click="openBatchHosting"')
    expect(aplusPanelSource).toContain('@require-auth="emit(\'require-auth\')"')
    expect(videoPanelSource).toContain("const emit = defineEmits<{ 'require-auth': [] }>()")
    expect(batchModalSource).toContain("'require-auth': []")
    expect(batchModalSource).toMatch(/emit\('update:open', false\)\s*emit\('require-auth'\)/)

    expect((workspaceSource.match(/if \(requireAuthForModelAction\(\)\) return/g) ?? []).length).toBeGreaterThanOrEqual(8)
    expect((aplusPanelSource.match(/if \(requireAuthForModelAction\(\)\) return/g) ?? []).length).toBeGreaterThanOrEqual(7)
    expect((videoPanelSource.match(/if \(requireAuthForModelAction\(\)\) return/g) ?? []).length).toBeGreaterThanOrEqual(4)
    expect((batchModalSource.match(/if \(requireAuthForModelAction\(\)\) return/g) ?? []).length).toBeGreaterThanOrEqual(2)

    expect(aplusPanelSource).toContain('async function regenerateCopywriting() {\n  await aiWrite()\n}')
    expect(videoPanelSource).toContain('async function regenerateCopywriting() {\n  await aiWrite()\n}')
    expect(batchModalSource).toContain('async function aiWriteTask(index: number) {\n  if (requireAuthForModelAction()) return')
  })

  it('shows optimistic running cards immediately after generation confirmation', () => {
    expect(workspaceSource).toContain('function createOptimisticJob')
    expect(workspaceSource).toContain('function preservePendingJobItems')
    expect(workspaceSource).toContain("status: 'running'")
    expect(workspaceSource).toContain('job.value = createOptimisticJob(payload)')
    expect(workspaceSource).toContain('const created = preservePendingJobItems(await createJob(payload)); job.value = created')
    expect(apiClientSource).toContain("api.post('/generation-jobs', payload, { timeout: GENERATION_REQUEST_TIMEOUT_MS })")
  })

  it('polls running jobs frequently so finished cards appear without a refresh', () => {
    expect(workspaceSource).toContain('const IMAGE_JOB_POLL_INTERVAL_MS = 500')
    expect(workspaceSource).toContain('window.setTimeout(resolve, IMAGE_JOB_POLL_INTERVAL_MS)')
    expect(aplusPanelSource).toContain('const APLUS_JOB_POLL_INTERVAL_MS = 500')
    expect(aplusPanelSource).toContain('window.setTimeout(resolve, APLUS_JOB_POLL_INTERVAL_MS)')
    expect(videoPanelSource).toContain('const VIDEO_JOB_POLL_INTERVAL_MS = 1000')
    expect(videoPanelSource).toContain('window.setTimeout(resolve, VIDEO_JOB_POLL_INTERVAL_MS)')
  })

  it('keeps polling when terminal jobs still lack renderable result URLs', () => {
    expect(workspaceSource).toContain('function suiteJobNeedsRefresh')
    expect(workspaceSource).toContain("item.status === 'succeeded' && !itemResultUrl(item)")
    expect(workspaceSource).toContain('if (!suiteJobNeedsRefresh(latest)) return latest')

    expect(aplusPanelSource).toContain('function aplusJobNeedsRefresh')
    expect(aplusPanelSource).toContain("item.status === 'succeeded' && !currentUrl(item)")
    expect(aplusPanelSource).toContain('if (!aplusJobNeedsRefresh(latest)) return latest')

    expect(videoPanelSource).toContain('function videoJobNeedsRefresh')
    expect(videoPanelSource).toContain("item.status === 'succeeded' && !currentVideoUrl(item)")
    expect(videoPanelSource).toContain('if (!videoJobNeedsRefresh(latest)) return latest')
  })

  it('resumes job polling from history and kept-alive module returns', () => {
    expect(workspaceSource).toContain('void resumeSuiteJobRefresh(job.value.id)')
    expect(workspaceSource).toContain("if (phase.value === 'suite') void resumeCurrentSuiteJobRefresh()")

    expect(aplusPanelSource).toContain('onActivated(() => { void resumeCurrentAplusJobRefresh() })')
    expect(aplusPanelSource).toContain('void resumeAplusGenerationRefresh(generationJob.value.id)')
    expect(aplusPanelSource).toContain('void resumeAplusPlanRefresh(planJob.value.id)')

    expect(videoPanelSource).toContain('onActivated(() => { void resumeCurrentVideoJobRefresh() })')
    expect(videoPanelSource).toContain('void resumeVideoJobRefresh(job.value.id)')
  })

  it('restores the latest unfinished generation task after page refresh', () => {
    expect(apiClientSource).toContain("api.get('/aplus-plan-jobs')")
    expect(workspaceSource).toContain('latestActiveWorkspaceJob(entries)')
    expect(workspaceSource).toContain('const [planJobs, generationJobs] = await Promise.all([listAplusPlanJobs(), listAplusGenerationJobs()])')
    expect(workspaceSource).toContain("await router.replace(`/app/${candidate.phase}`)")
    expect(workspaceSource).toContain("await aplusPanel.value?.openHistoryJob(candidate.entry as AplusJob, { continuePlan: true })")
    expect(workspaceSource).toContain('suppressedAutoRestorePhases.value = copyPhaseSet(suppressedAutoRestorePhases.value, phase.value)')
    expect(aplusPanelSource).toContain('function outputTargetsFromPlan')
    expect(aplusPanelSource).toContain('function placeholderPlanItemsFromJob')
    expect(aplusPanelSource).toContain('async function continueGenerationFromPlan')
    expect(aplusPanelSource).toContain("options.continuePlan && planJob.value?.status === 'succeeded'")
  })

  it('shows terminal card placeholders without spinning as generating', () => {
    expect(resultGridSource).toContain("if (item.status === 'failed') return '生成失败'")
    expect(resultGridSource).toContain("if (item.status === 'cancelled') return '已取消'")
    expect(resultGridSource).toContain("if (item.status === 'succeeded') return '结果同步中'")
    expect(resultGridSource).toContain("['queued', 'running', 'succeeded'].includes(item.status)")
    expect(resultGridSource).toContain('v-if="placeholderSpinning(item)"')

    expect(aplusPanelSource).toContain("if (item.status === 'failed') return '生成失败'")
    expect(aplusPanelSource).toContain("if (item.status === 'cancelled') return '已取消'")
    expect(aplusPanelSource).toContain("if (item.status === 'succeeded') return '结果同步中'")
    expect(aplusPanelSource).toContain('v-if="aplusPlaceholderSpinning(item)"')

    expect(videoPanelSource).toContain("if (item.status === 'failed') return '生成失败'")
    expect(videoPanelSource).toContain("if (item.status === 'cancelled') return '已取消'")
    expect(videoPanelSource).toContain("if (item.status === 'succeeded') return '结果同步中'")
    expect(videoPanelSource).toContain('v-else-if="!videoPlaceholderSpinning(item)"')
  })

  it('removes user-facing progress percentages from active generation buttons', () => {
    expect(workspaceSource).toContain("submittingGeneration ? '正在提交'")
    expect(workspaceSource).toContain('followSubmittedSuiteJob')
    expect(workspaceSource).not.toContain('正在处理 ${job?.progress')
    expect(aplusPanelSource).toContain("planning ? '生成方案中' : generating ? '生成图片中'")
    expect(aplusPanelSource).not.toContain('生成方案 ${planJob?.progress')
    expect(aplusPanelSource).not.toContain('生成图片 ${generationJob?.progress')
    expect(videoPanelSource).toContain("generating ? '正在生成视频'")
    expect(videoPanelSource).not.toContain('正在生成 ${job?.progress')
  })

  it('routes generation and content-safety failures through the top message area', () => {
    expect(workspaceSource).not.toContain('Modal.error')
    expect(aplusPanelSource).not.toContain('Modal.error')
    expect(videoPanelSource).not.toContain('Modal.error')
    expect(workspaceSource).toContain("message.error(generationFailureMessageFor('image', source))")
    expect(aplusPanelSource).toContain("message.error(generationFailureMessageFor('image', source))")
    expect(videoPanelSource).toContain("message.error(generationFailureMessageFor('video', source))")
    expect(generationErrorsRawSource).toContain("image: '生成图片失败，请稍后重试'")
    expect(generationErrorsRawSource).toContain("video: '生成视频失败，请稍后重试'")
    expect(generationErrorsRawSource).toContain('import.meta.env.DEV')
    expect(generationErrorsRawSource).toContain("import.meta.env.VITE_SHOW_DETAILED_GENERATION_ERRORS === 'true'")
    expect(videoPanelSource).not.toContain('{{ item.error }}')
    expect(aplusPanelSource).not.toContain('{{ item.error }}')
    expect(workspaceSource).not.toContain('{{ item.error }}')
  })

  it('previews AI copywriting before applying and supports regeneration', () => {
    expect(workspaceSource).toContain('aiSuggestion')
    expect(workspaceSource).toContain('aiWriteOpen')
    expect(workspaceSource).toContain('regenerateCopywriting')
    expect(workspaceSource).toContain('applyAiSuggestion')
    expect(workspaceSource).toContain('重新帮写')
    expect(workspaceSource).toContain('确认回填')
    expect(workspaceSource).toContain('<Teleport to="body">')
    expect(workspaceSource).toContain("aiSuggestion.value = ''")
    expect(workspaceSource).toContain('sellingPointsEditing.value = true')
    expect(aplusPanelSource).toContain('productInfoEditing.value = true')
    expect(videoPanelSource).toContain('sellingPointsEditing.value = true')
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
    expect(workspaceSuiteCss).toContain('.selling-points-markdown-frame .markdown-preview')
    expect(workspaceSuiteCss).toContain('height: 190px')
    expect(workspaceSuiteCss).toContain('resize: vertical')
    expect(workspaceSuiteCss).toContain('.batch-hosting-modal-wrap .ant-modal')
    expect(workspaceSuiteCss).toContain('top: 28px')
    expect(workspaceSuiteCss).toContain('height: 240px')
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
    expect(workspaceSource).toContain('<VideoPhasePanel v-if="phase===\'video\'" ref="videoPanel" @require-auth="requireAuthForModelAction" />')
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
    expect(aplusPanelSource).toContain('defineExpose({ openHistoryJob, openBatchSelection, startNewTask, dryRun })')
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
    expect(aplusPanelSource).toContain('title="预览" aria-label="预览"')
    expect(aplusPanelSource).toContain('function canPreviewAplusItem')
    expect(aplusPanelSource).toContain("return item.status === 'succeeded' && Boolean(currentUrl(item))")
    expect(aplusPanelSource).toContain(':disabled="!canPreviewAplusItem(item)"')
    expect(aplusPanelSource).toContain('title="二次编辑" aria-label="二次编辑"')
    expect(aplusPanelSource).toContain('title="编辑文字" aria-label="编辑文字"')
    expect(aplusPanelSource).toContain('title="脚本" aria-label="脚本"')
    expect(aplusPanelSource).not.toContain('<EyeOutlined />预览')
    expect(aplusPanelSource).not.toContain('<EditOutlined />编辑')
    expect(aplusPanelSource).not.toContain('<FileTextOutlined />文字')
    expect(aplusPanelSource).not.toContain('<PlayCircleOutlined />脚本')
    expect(apiClientSource).toContain('api.post(`/aplus-items/${id}/versions`')
    expect(apiClientSource).toContain('api.post(`/aplus-items/${id}/text-ocr`')
    expect(apiClientSource).toContain('api.post(`/aplus-items/${id}/text-versions`')
    expect(resultGridSource).toContain('script: [item: JobItem]')
    expect(resultGridSource).toContain('textEdit: [item: JobItem]')
    expect(resultGridSource).toContain('title="预览" aria-label="预览"')
    expect(resultGridSource).toContain("const canUseResult = (item: JobItem) => item.status === 'succeeded' && Boolean(currentUrl(item))")
    expect(resultGridSource).toContain(':disabled="!canUseResult(item)"')
    expect(resultGridSource).toContain('function previewItem(item: JobItem)')
    expect(resultGridSource).toContain('title="二次编辑" aria-label="二次编辑"')
    expect(resultGridSource).toContain('title="编辑文字" aria-label="编辑文字"')
    expect(resultGridSource).toContain('title="脚本" aria-label="脚本"')
    expect(resultGridSource).not.toContain('<EyeOutlined />预览')
    expect(resultGridSource).not.toContain('<EditOutlined />编辑')
    expect(resultGridSource).not.toContain('<FileTextOutlined />文字')
    expect(resultGridSource).not.toContain('<PlayCircleOutlined />脚本')
    expect(normalizedWorkspace).toContain('display:block')
    expect(normalizedGrid).toContain('grid-template-columns:repeat(3,minmax(240px,1fr))')
    expect(workspaceSuiteCss).toContain('aspect-ratio: 1 / 1;')
    expect(workspaceSuiteCss).toContain('object-fit: contain;')
    const aplusCardButtonRule = workspaceSuiteCss.match(/\.aplus-result-card footer button\s*\{([^}]*)\}/)?.[1]?.replace(/\s+/g, '') ?? ''
    expect(aplusCardButtonRule).toContain('width:28px')
    expect(aplusCardButtonRule).toContain('height:28px')
    expect(aplusCardButtonRule).toContain('color:#6d7480')
    expect(workspaceSuiteCss).toContain('.aplus-results > header > div:first-child')
    expect(workspaceSuiteCss).toContain('.aplus-result-actions')
    expect(workspaceSuiteCss).toContain('flex-wrap: nowrap;')
    expect(workspaceSuiteCss).toContain('white-space: nowrap;')
    expect(workspaceSuiteCss).toContain('.aplus-script-preview')
    expect(workspaceSuiteCss).toContain('.text-edit-side-panel')
    expect(workspaceSuiteCss).toContain('.text-edit-confirm.ready')
  })

  it('uses regeneration copy and guarded loading for image edit modals', () => {
    const editPlaceholderRule = workspaceSuiteCss.match(/\.edit-dialog textarea::placeholder\s*\{([^}]*)\}/)?.[1] ?? ''
    const normalizedEditPlaceholderRule = editPlaceholderRule.replace(/\s+/g, '')

    expect(workspaceSource).toContain("const editInstruction = ref(''); const editSubmitting = ref(false)")
    expect(workspaceSource).toContain("const suiteEditPlaceholder = '写下这次想调整的画面；不填则按当前版本重新生成。比如：让背景更清爽、主体位置微调、保留商品外观。'")
    expect(workspaceSource).toContain("const instruction = editInstruction.value.trim()")
    expect(workspaceSource).not.toContain('suiteDefaultEditInstruction')
    expect(workspaceSource).toContain('if (editSubmitting.value || !activeItem.value')
    expect(workspaceSource).toContain('editInstruction.value = \'\'')
    expect(workspaceSource).toContain('title="二次编辑" ok-text="重新生成"')
    expect(workspaceSource).toContain(':confirm-loading="editSubmitting" @ok="submitEdit"')
    expect(workspaceSource).toContain(':placeholder="suiteEditPlaceholder"')
    expect(workspaceSource).toContain("message.success('已重新生成新版本')")
    expect(workspaceSource).not.toContain('二次编辑 · 创建子版本')
    expect(workspaceSource).not.toContain('已创建新的子版本')

    expect(aplusPanelSource).toContain("const editInstruction = ref('')")
    expect(aplusPanelSource).toContain('const editSubmitting = ref(false)')
    expect(aplusPanelSource).toContain("const aplusEditPlaceholder = '写下这次想调整的 A+ 画面；不填则按当前版本重新生成。比如：提升背景亮度、强化材质表现、保持商品和文案不变。'")
    expect(aplusPanelSource).toContain("const aplusDefaultEditInstruction = '按当前 A+ 图片重新生成，保持商品主体、版式卖点和文字信息不变。'")
    expect(aplusPanelSource).toContain("const instruction = editInstruction.value.trim() || aplusDefaultEditInstruction")
    expect(aplusPanelSource).toContain('if (editSubmitting.value || !editItemState.value')
    expect(aplusPanelSource).toContain('title="A+ 二次编辑" ok-text="重新生成"')
    expect(aplusPanelSource).toContain(':confirm-loading="editSubmitting" @ok="submitEdit"')
    expect(aplusPanelSource).toContain(':placeholder="aplusEditPlaceholder"')
    expect(aplusPanelSource).toContain("message.success('A+ 已重新生成新版本')")
    expect(aplusPanelSource).not.toContain('已创建新的 A+ 子版本')

    expect(normalizedEditPlaceholderRule).toContain('color:#a7acb5')
    expect(normalizedEditPlaceholderRule).toContain('font-size:13px')
    expect(normalizedEditPlaceholderRule).toContain('line-height:1.5')
  })

  it('renders suite result images inside a contain preview frame', () => {
    expect(resultGridSource).toContain('class="result-image-frame"')
    expect(resultGridSource).toContain(':data-text-edit-anchor="item.id"')
    expect(aplusPanelSource).toContain(':data-text-edit-anchor="item.id"')
    expect(resultGridSource).toContain('class="image-watermark-box"')
    expect(resultGridSource).toContain('aspectRatio?: string')
    expect(resultGridSource).toContain('naturalAspectRatios')
    expect(resultGridSource).toContain('itemPreviewAspectRatio(item)')
    expect(resultGridSource).toContain(':style="previewAspectStyle(itemPreviewAspectRatio(item))"')
    expect(resultGridSource).toContain('@load="updateNaturalAspect(currentUrl(item), $event)"')
    expect(workspaceSource).toContain(':aspect-ratio="String(job.params.aspect_ratio || \'\')"')
    expect(aplusPanelSource).toContain('naturalAspectRatios')
    expect(aplusPanelSource).toContain('itemPreviewAspectRatio(item)')
    expect(aplusPanelSource).toContain(':style="previewAspectStyle(itemPreviewAspectRatio(item))"')
    expect(aplusPanelSource).toContain('@load="updateNaturalAspect(currentUrl(item), $event)"')
    expect(resultGridSource).toContain('<img :src="currentUrl(item)"')
    expect(resultGridSource).toContain('textEdit: [item: JobItem]')
    expect(workspaceSource).toContain('@text-edit="openTextEdit"')
    expect(workspaceSource).toContain('<ImageTextEditPanel')
    expect(aplusPanelSource).toContain('<ImageTextEditPanel')
    expect(workspaceSource).toContain(':dirty="textEditDirty"')
    expect(aplusPanelSource).toContain(':dirty="textEditDirty"')
    expect(workspaceSource).toMatch(
      /watch\(\(\) => job\.value\?\.id, \(\) => \{\s*closeTextEdit\(\)\s*\}\)/,
    )
    expect(aplusPanelSource).toMatch(
      /watch\(\(\) => generationJob\.value\?\.id, \(\) => \{\s*closeTextEdit\(\)\s*\}\)/,
    )
    expect(workspaceSource).toContain("async function openHistoryJob(entry: HistoryEntry) {\n  closeTextEdit()")
    expect(aplusPanelSource).toContain("async function openHistoryJob(entry: AplusJob, options: { continuePlan?: boolean } = {}) {\n  closeTextEdit()")
    expect(workspaceSource).toContain("if (!anchor) {\n    closeTextEdit()\n    return\n  }")
    expect(aplusPanelSource).toContain("if (!anchor) {\n    closeTextEdit()\n    return\n  }")
    expect(imageTextEditPanelSource).toContain("{{ submitting ? '改字中...' : '确认改字' }}")
    expect(imageTextEditPanelSource).toContain(':disabled="!dirty || loading || submitting"')
    expect(imageTextEditPanelSource).toContain("ready: dirty && !loading && !submitting")
    expect(imageTextEditPanelSource).not.toContain('确认改字 · 15')
    expect(apiClientSource).toContain('api.post(`/generation-items/${id}/text-ocr`')
    expect(apiClientSource).toContain('api.post(`/generation-items/${id}/text-versions`')
    expect(apiClientSource).toContain('const IMAGE_EDIT_REQUEST_TIMEOUT_MS = 900_000')
    expect(apiClientSource).toContain('api.post(`/generation-items/${id}/versions`, { instruction }, { timeout: IMAGE_EDIT_REQUEST_TIMEOUT_MS })')
    expect(apiClientSource).toContain('api.post(`/aplus-items/${id}/versions`, { instruction }, { timeout: IMAGE_EDIT_REQUEST_TIMEOUT_MS })')
    expect(apiClientSource).toContain('api.post(`/generation-items/${id}/text-versions`, { lines }, { timeout: IMAGE_EDIT_REQUEST_TIMEOUT_MS })')
    expect(apiClientSource).toContain('api.post(`/aplus-items/${id}/text-versions`, { lines }, { timeout: IMAGE_EDIT_REQUEST_TIMEOUT_MS })')
    expect(frontendNginxConf).toContain('proxy_read_timeout 900s;')
    expect(frontendNginxConf).toContain('proxy_send_timeout 900s;')
    expect(workspaceSource).not.toContain('label>原文字')
    expect(aplusPanelSource).not.toContain('label>原文字')
    const resultWatermarkBoxRule = workspaceSuiteCss.match(/\.result-card \.result-image-frame \.image-watermark-box,\s*\.aplus-result-image-frame \.image-watermark-box\s*\{([^}]*)\}/)?.[1]?.replace(/\s+/g, '') ?? ''
    expect(workspaceSuiteCss).toContain('.result-card .result-image-frame')
    expect(workspaceSuiteCss).toContain('.result-card .result-image-frame .image-watermark-box')
    expect(workspaceSuiteCss).toContain('.aplus-result-image-frame .image-watermark-box')
    expect(resultWatermarkBoxRule).toContain('width:100%')
    expect(resultWatermarkBoxRule).toContain('height:100%')
    expect(resultWatermarkBoxRule).toContain('width:min(100cqw,calc(100cqh*var(--preview-aspect-number,1)))')
    expect(resultWatermarkBoxRule).toContain('height:min(100cqh,calc(100cqw/var(--preview-aspect-number,1)))')
    expect(resultWatermarkBoxRule).toContain('aspect-ratio:var(--preview-aspect-ratio,1/1)')
    expect(workspaceSuiteCss).toContain('container-type: size;')
    expect(workspaceSuiteCss).toContain('.result-card .image-watermark-box > img:first-child')
    expect(workspaceSuiteCss).toContain('object-fit: contain;')
    expect(workspaceSuiteCss).not.toContain('.result-card .result-image-frame img {\n  width: 100%;\n  height: 100%;\n  object-fit: cover;')
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
    expect(apiClientSource).toContain("api.post('/video-jobs', payload, { timeout: GENERATION_REQUEST_TIMEOUT_MS })")
    expect(apiClientSource).toContain('api.post(`/video-jobs/${jobId}/retry-failed`, undefined, { timeout: GENERATION_REQUEST_TIMEOUT_MS })')
    expect(apiClientSource).toContain("api.post('/video-copywriting-assist'")
    expect(apiClientSource).toContain('/api/v1/video-jobs/')
    expect(apiClientSource).toContain('api.post(`/video-items/${id}/versions`')
  })

  it('keeps video publish ratio valid when platform changes', () => {
    expect(videoPanelSource).toContain("import { computed, nextTick, onActivated, onBeforeUnmount, onMounted, ref, watch } from 'vue'")
    expect(videoPanelSource).toContain('watch(() => form.value.platform')
    expect(videoPanelSource).toContain('!options.some((item) => item.value === form.value.ratio)')
    expect(videoPanelSource).toContain('form.value.ratio = options[0].value')
  })

  it('renders video result actions for edit, script, download and retry', () => {
    expect(videoPanelSource).toContain('下载选中')
    expect(videoPanelSource).toContain('重试失败')
    expect(videoPanelSource).toContain('视频导演脚本')
    expect(videoPanelSource).toContain('视频二次编辑')
    expect(videoPanelSource).toContain('title="二次编辑" aria-label="二次编辑"')
    expect(videoPanelSource).toContain('title="脚本" aria-label="脚本"')
    expect(videoPanelSource).toContain('<EditOutlined /></button>')
    expect(videoPanelSource).toContain('<PlayCircleOutlined /></button>')
    expect(videoPanelSource).not.toContain('<EditOutlined />编辑')
    expect(videoPanelSource).not.toContain('<PlayCircleOutlined />脚本')
    expect(videoPanelSource).not.toContain('远程任务号 {{ item.provider_task_id }}')
    expect(videoPanelSource).not.toContain('<FileTextOutlined />文字')
    expect(workspaceVideoCss).toContain('.video-card footer .video-card-actions { flex: 0 0 auto; min-width: auto; display: flex; flex-direction: row;')
    expect(workspaceVideoCss).toContain('justify-content: flex-end; gap: 0;')
    expect(workspaceVideoCss).toContain('.video-card footer .video-card-actions button { width: 28px; height: 28px; color: #6d7480;')
    expect(videoPanelSource).toContain('AI 转写')
    expect(videoPanelSource).toContain('安全演示模式')
  })

  it('keeps failed-video retry single-shot and suppresses accidental cancellation', () => {
    expect(videoPanelSource).toContain('const retryCooldownUntil = ref(0)')
    expect(videoPanelSource).toContain('retryCooldownUntil.value = Date.now() + 2000')
    expect(videoPanelSource).toContain("if (!job.value || job.value.id.startsWith('optimistic-video-') || generating.value || retryCooldownActive.value) return")
    expect(videoPanelSource).toContain("const failedItems = job.value.items.filter((item) => item.status === 'failed')")
    expect(videoPanelSource).toContain('startRetryCooldown()')
    expect(videoPanelSource).toContain("item.status === 'failed' ? { ...item, status: 'running', error: null } : item")
    expect(videoPanelSource).toContain('v-if="videoJobActive && job?.status === \'queued\'"')
    expect(videoPanelSource).toContain('v-if="retryCooldownActive || job.items.some((item) => item.status === \'failed\')"')
    expect(videoPanelSource).toContain(':disabled="generating || retryCooldownActive" @click="retryFailed"')
    expect(videoPanelSource).toContain('onBeforeUnmount(clearRetryCooldown)')
    expect(videoPanelSource).toContain('function openHistoryJob(entry: VideoJob) {\n  clearRetryCooldown()')
    expect(videoPanelSource).toContain('function startNewTask() {\n  clearRetryCooldown()')
  })

  it('keeps video fullscreen playback contained instead of cropped', () => {
    const videoRule = workspaceVideoCss.match(/\.video-frame video\s*\{([^}]*)\}/)?.[1] ?? ''
    const fullscreenRule = workspaceVideoCss.match(/\.video-frame video:fullscreen,[^{]+\{([^}]*)\}/)?.[1] ?? ''
    const normalizedVideo = videoRule.replace(/\s+/g, '')
    const normalizedFullscreen = fullscreenRule.replace(/\s+/g, '')

    expect(normalizedVideo).toContain('object-fit:contain')
    expect(normalizedVideo).toContain('background:#000')
    expect(workspaceVideoCss).toContain('.video-frame video:-webkit-full-screen')
    expect(workspaceVideoCss).toContain('.video-frame video:-moz-full-screen')
    expect(workspaceVideoCss).toContain('.video-frame video:-ms-fullscreen')
    expect(normalizedFullscreen).toContain('object-fit:contain')
  })
})
