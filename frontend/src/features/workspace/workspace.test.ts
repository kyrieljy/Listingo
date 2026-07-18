import { readFileSync } from 'node:fs'
import { describe, expect, it } from 'vitest'
import {
  buildCustomTypes,
  buildGenerationPayload,
  buildVideoPayload,
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
import videoPanelSource from './VideoPhasePanel.vue?raw'
import workspaceSource from './WorkspaceView.vue?raw'
import apiClientSource from '../../api/client.ts?raw'

const workspaceSuiteCss = readFileSync(new URL('./workspace-suite.css', import.meta.url), 'utf8')

describe('workspace model', () => {
  it('keeps the four planned phase entries in order', () => {
    expect(phaseDefinitions.map((item) => item.label)).toEqual([
      '商品套图',
      'A+详情',
      '视频与爆款复刻',
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
    expect(workspaceSource).toContain("status: 'running'")
    expect(workspaceSource).toContain('job.value = createOptimisticJob(payload)')
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

  it('renders markdown copywriting as formatted preview while preserving editable textareas', () => {
    expect(renderMarkdown('### 1. 商品定位\n- 品名：<保温杯>')).toBe('<h3>1. 商品定位</h3><ul><li>品名：&lt;保温杯&gt;</li></ul>')
    expect(workspaceSource).toContain('class="markdown-input-frame selling-points-markdown-frame"')
    expect(workspaceSource).toContain('v-html="renderMarkdown(form.sellingPoints)"')
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
    expect(workspaceSource).toContain('<VideoPhasePanel v-else />')
    expect(workspaceSource).toContain("v-if=\"phase!=='video'\" class=\"preview-canvas\"")
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
    expect(payload.generate_audio).toBe(true)
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
    expect(videoPanelSource).toContain('AI 转写')
    expect(videoPanelSource).toContain('安全演示模式')
  })
})
