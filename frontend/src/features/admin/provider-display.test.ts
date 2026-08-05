import { readFileSync } from 'node:fs'

import { describe, expect, it } from 'vitest'

import {
  groupProviderCategoriesByBusinessRoute,
  groupProvidersByBusinessRoute,
  providerRuntimeState,
  type ProviderDisplayRecord,
} from './provider-display'
import adminSource from './AdminView.vue?raw'

const adminPromptUploadCss = readFileSync(new URL('./admin-prompt-upload.css', import.meta.url), 'utf-8')

function provider(
  code: string,
  enabled = true,
  hasApiKey = true,
): ProviderDisplayRecord {
  const capability = code.startsWith('doubao-') || code.startsWith('gpt-') || code.startsWith('qwen-')
    ? 'llm'
    : code.startsWith('shengsuanyun-')
      ? 'video'
      : 'image'
  return {
    id: code,
    code,
    label: code,
    capability,
    adapter: 'adapter',
    base_url: 'https://example.test',
    model_name: code,
    enabled,
    is_default: code === 'doubao-seed-2-0-mini' || code === 'yunwu-nano-pro' || code === 'shengsuanyun-doubao-seedance-2-0',
    is_fallback: code === 'qwen-3-6' || code === 'yunwu-nano',
    route_roles: {
      ...(code === 'doubao-seed-2-0-mini' ? { llm: 'primary' as const } : {}),
      ...(code === 'qwen-3-6' ? { llm: 'fallback' as const } : {}),
      ...(code === 'yunwu-nano-pro' ? { suite_fidelity: 'primary' as const } : {}),
      ...(code === 'yunwu-nano' ? { suite_fidelity: 'fallback' as const } : {}),
      ...(code === 'yunwu-image-2' ? { suite_layout: 'primary' as const, aplus_detail: 'primary' as const } : {}),
      ...(code === 'aplus-mobile-edit-low-cost' ? { aplus_mobile: 'primary' as const } : {}),
      ...(code === 'shengsuanyun-doubao-seedance-2-0' ? { video: 'primary' as const } : {}),
    },
    has_api_key: hasApiKey,
    api_key_masked: hasApiKey ? 'sk-****' : null,
    config: {},
  }
}

describe('provider business display', () => {
  it('requires both enablement and an API key before a provider is effective', () => {
    expect(providerRuntimeState(provider('yunwu-nano-pro', false, true)).label).toBe('未启用')
    expect(providerRuntimeState(provider('yunwu-nano-pro', true, false)).label).toBe('缺少密钥')
    expect(providerRuntimeState(provider('yunwu-nano-pro', true, true)).label).toBe('当前生效')
  })

  it('groups providers by the actual business routes instead of capability only', () => {
    const groups = groupProvidersByBusinessRoute([
      provider('yunwu-image-2'),
      provider('aplus-mobile-edit-low-cost'),
      provider('qwen-3-6'),
      provider('yunwu-nano'),
      provider('doubao-seed-2-0-mini'),
      provider('yunwu-nano-pro'),
      provider('shengsuanyun-doubao-seedance-2-0'),
    ])

    expect(groups.map((group) => group.key)).toEqual(['suite_fidelity', 'suite_layout', 'aplus_detail', 'aplus_mobile', 'video', 'llm'])
    expect(groups.map((group) => group.title)).toEqual([
      '保真',
      '排版',
      '详情页',
      '移动端',
      '视频',
      'LLM',
    ])
    expect(groups[0].providers.map((item) => item.role)).toEqual(['主模型', '失败备用'])
    expect(groups[1].providers.map((item) => item.role)).toEqual(['主模型'])
    expect(groups[2].providers.map((item) => item.role)).toEqual(['主模型'])
    expect(groups[3].providers.map((item) => item.role)).toEqual(['主模型'])
    expect(groups[4].providers.map((item) => item.role)).toEqual(['主模型'])
    expect(groups[5].providers.map((item) => item.role)).toEqual(['主模型', '失败备用'])
    expect(groups.every((group) => group.ready)).toBe(true)
  })

  it('groups routes into the requested major model categories', () => {
    const categories = groupProviderCategoriesByBusinessRoute([
      provider('yunwu-image-2'),
      provider('aplus-mobile-edit-low-cost'),
      provider('qwen-3-6'),
      provider('yunwu-nano'),
      provider('doubao-seed-2-0-mini'),
      provider('yunwu-nano-pro'),
      provider('shengsuanyun-doubao-seedance-2-0'),
    ])

    expect(categories.map((category) => category.title)).toEqual(['套图', 'A+', '视频', 'LLM'])
    expect(categories[0].groups.map((group) => group.title)).toEqual(['保真', '排版'])
    expect(categories[1].groups.map((group) => group.title)).toEqual(['详情页', '移动端'])
    expect(categories[2].groups.map((group) => group.title)).toEqual(['视频'])
    expect(categories[3].groups.map((group) => group.title)).toEqual(['LLM'])
  })

  it('marks a route incomplete when any required provider is unavailable', () => {
    const groups = groupProvidersByBusinessRoute([
      provider('doubao-seed-2-0-mini'),
      provider('qwen-3-6', false, true),
      provider('yunwu-nano-pro'),
      provider('yunwu-nano'),
      provider('yunwu-image-2', true, false),
      provider('aplus-mobile-edit-low-cost'),
      provider('shengsuanyun-doubao-seedance-2-0'),
    ])

    expect(groups.find((group) => group.key === 'llm')?.ready).toBe(false)
    expect(groups.find((group) => group.key === 'llm')?.statusLabel).toBe('链路未完整启用')
    expect(groups.find((group) => group.key === 'suite_fidelity')?.ready).toBe(true)
    expect(groups.find((group) => group.key === 'suite_layout')?.ready).toBe(false)
    expect(groups.find((group) => group.key === 'aplus_mobile')?.ready).toBe(true)
    expect(groups.find((group) => group.key === 'video')?.ready).toBe(true)
  })

  it('renders business groups and explains that enablement alone is insufficient', () => {
    expect(adminSource).toContain('v-for="category in providerCategories"')
    expect(adminSource).toContain('v-for="group in category.groups"')
    expect(adminSource).toContain('providerRuntimeState(provider).label')
    expect(adminSource).toContain('启用开关只是允许调用')
    expect(adminSource).toContain('未启用')
    expect(adminSource).toContain('缺少密钥')
    expect(adminSource).toContain('当前生效')
    expect(adminSource).toContain('视频模型')
    expect(adminSource).toContain('套图大板块模型链路')
    expect(adminSource).toContain('A+ 详情页模型链路')
    expect(adminSource).toContain('业务链路角色')
    expect(adminSource).toContain('主模型')
    expect(adminSource).toContain('备用模型')
  })

  it('keeps mobile admin navigation icon-only instead of wrapping labels vertically', () => {
    expect(adminSource).toContain('.admin-nav>button { font-size: 0 !important; justify-content: center; }')
    expect(adminSource).toContain('.admin-nav>button>.anticon { font-size: 18px; }')
  })

  it('separates Nano resolution from Image 2 ratio-following size settings', () => {
    expect(adminSource).toContain('providerResolutions(selectedProvider)')
    expect(adminSource).toContain("selectedProvider.capability==='image' && Array.isArray(selectedProvider.config.allowed_resolutions)")
    expect(adminSource).toContain('Array.isArray(selectedProvider.config.allowed_sizes)')
    expect(adminSource).not.toContain('v-model="selectedProvider.config.aspect_ratio"')
    expect(adminSource).toContain('class="image2-size-warning"')
    expect(adminSource).toContain('value="follow_ratio"')
    expect(adminSource).toContain('高级固定尺寸')
    expect(adminSource).toContain("selectedProvider.config.quality!==undefined")
  })

  it('shows runtime public asset base URL settings for video generation', () => {
    expect(adminSource).toContain('/admin/runtime-settings')
    expect(adminSource).toContain('PUBLIC_ASSET_BASE_URL')
    expect(adminSource).toContain('LISTINGO_PUBLIC_ASSET_BASE_URL')
  })

  it('keeps the runtime settings save action visibly primary', () => {
    const primaryRule = [...adminSource.matchAll(/\.admin-primary\s*\{([^}]*)\}/g)]
      .map((match) => match[1])
      .find((rule) => rule.includes('#5b46e8')) ?? ''
    const disabledRule = adminSource.match(/\.admin-primary:disabled\s*\{([^}]*)\}/)?.[1] ?? ''
    const normalizedPrimary = primaryRule.replace(/\s+/g, '')
    const normalizedDisabled = disabledRule.replace(/\s+/g, '')

    expect(adminSource).toContain('保存基础配置')
    expect(adminSource.match(/@click="saveRuntimeSettings"/g)).toHaveLength(1)
    expect(normalizedPrimary).toContain('background:#5b46e8!important')
    expect(normalizedPrimary).toContain('border-color:#5b46e8!important')
    expect(normalizedPrimary).toContain('color:#fff!important')
    expect(normalizedDisabled).toContain('background:#8f82ef!important')
    expect(normalizedDisabled).toContain('opacity:.92')
  })

  it('wires execution log filters to an explicit filter action', () => {
    expect(adminSource).toContain("const logFilters=ref({ node: '', status: '' })")
    expect(adminSource).toContain('async function loadLogs()')
    expect(adminSource).toContain("if(logFilters.value.node)params.node=logFilters.value.node")
    expect(adminSource).toContain('v-model="logFilters.node"')
    expect(adminSource).toContain('v-model="logFilters.status"')
    expect(adminSource).toContain('@click="loadLogs">筛选')
  })

  it('renders a prompt test workbench wired to current editor content', () => {
    expect(adminSource).toContain('提示词测试台')
    expect(adminSource).toContain('/admin/prompts/${promptDetail.value.id}/test-runs')
    expect(adminSource).toContain('/admin/prompt-test-runs/${id}')
    expect(adminSource).toContain('prompt_content:promptContent.value')
    expect(adminSource).toContain("runPromptTest('llm_output')")
    expect(adminSource).toContain("runPromptTest('full_chain')")
    expect(adminSource).toContain("fullChainPromptCodes=['ecommerce-meta','ecommerce-video-meta-15s','aplus-meta']")
    expect(adminSource).toContain(':disabled="promptTesting||promptFullTesting||!promptSupportsFullChain"')
    expect(adminSource).toContain('prompt-test-workspace')
    expect(adminSource).not.toContain('v-model="promptTestInputs.preset"')
    expect(adminSource).toContain('promptPlatformChoices')
    expect(adminSource).toContain('videoTypeOptions')
    expect(adminSource).toContain('aplusOutputSpecs')
    expect(adminSource).toContain('AI 转写')
    expect(adminSource).toContain('assistCopywriting')
    expect(adminSource).toContain('assistVideoCopywriting')
    expect(adminSource).toContain("'content-safety-review'")
    expect(adminSource).toContain("promptDetail.value?.code==='content-safety-review'")
    expect(adminSource).toContain('dry_run:false')
    expect(adminSource).not.toContain('AI 转写 Dryrun')
    expect(adminSource).not.toContain('ai_dry_run')
    expect(adminSource).toContain('本次输入')
    expect(adminSource).toContain('结构化 JSON')
    expect(adminSource).toContain('模型原始输出')
    expect(adminSource).toContain('生图 / 视频结果')
    expect(adminSource).toContain('promptTestResult?.input_params')
    expect(adminSource).toContain('promptTestResult.artifact_urls')
  })

  it('marks the prompt version currently being viewed', () => {
    expect(adminSource).toContain('promptViewedVersionId')
    expect(adminSource).toContain('function viewPromptVersion')
    expect(adminSource).toContain('selected:version.id===promptViewedVersionId')
    expect(adminSource).toContain('@click="viewPromptVersion(version)"')
    expect(adminSource).toContain(':aria-selected="version.id===promptViewedVersionId"')
    expect(adminPromptUploadCss).toContain('.version-panel article.selected')
    expect(adminPromptUploadCss).toContain('box-shadow: inset 3px 0 0 #6c5ce7')
  })
})
