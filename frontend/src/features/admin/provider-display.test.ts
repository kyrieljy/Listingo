import { readFileSync } from 'node:fs'

import { describe, expect, it } from 'vitest'

import {
  groupProviderCategoriesByBusinessRoute,
  groupProvidersByBusinessRoute,
  providerRouteChainConfigValue,
  providerRuntimeState,
  type ProviderDisplayRecord,
} from './provider-display'
import adminSource from './AdminView.vue?raw'
import comparisonMatrixSource from './ComparisonMatrix.vue?raw'
import monitoringDashboardSource from './MonitoringDashboard.vue?raw'
import monitoringLineChartSource from './MonitoringLineChart.vue?raw'
import metricHelpSource from './MetricHelpPopover.vue?raw'
import sharePieChartSource from './SharePieChart.vue?raw'
import userDrilldownSource from './UserDrilldownPanel.vue?raw'

const adminPromptUploadCss = readFileSync(new URL('./admin-prompt-upload.css', import.meta.url), 'utf-8')
const monitoringCss = readFileSync(new URL('./monitoring.css', import.meta.url), 'utf-8')

const providerGroupLabels: Record<string, string> = {
  fal: 'fal.ai',
  runware: 'Runware',
  openrouter: 'OpenRouter',
  atlas: 'Atlas Cloud',
  replicate: 'Replicate',
  wavespeed: 'WaveSpeedAI',
  kie: 'Kie.ai',
  cometapi: 'CometAPI',
  apimodels: 'API Models',
}

function providerGroupKey(code: string): string | null {
  return Object.keys(providerGroupLabels).find((prefix) => code.startsWith(`${prefix}-`)) ?? null
}

function providerOperation(code: string): string | null {
  if (code.includes('seedance')) return 'video'
  if (code.endsWith('-edit') || code.includes('gpt-image-2-edit')) return 'edit'
  if (code.includes('gpt-image-2') || code.includes('nano-')) return 'generate'
  return null
}

function providerModelFamily(code: string): string | null {
  if (code.includes('seedance')) return 'seedance-2.0'
  if (code.includes('gpt-image-2')) return 'gpt-image-2'
  if (code.includes('nano-pro')) return 'nano-banana-pro'
  if (code.includes('nano-2')) return 'nano-banana-2'
  return null
}

function provider(
  code: string,
  enabled = true,
  hasApiKey = true,
): ProviderDisplayRecord {
  const capability = code.startsWith('doubao-') || code.startsWith('gpt-') || code.startsWith('qwen-')
    ? 'llm'
    : code.includes('seedance')
      ? 'video'
      : 'image'
  const group = providerGroupKey(code)
  const operation = providerOperation(code)
  const modelFamily = providerModelFamily(code)
  const ratioOnlyImage2 = ['apimodels-', 'kie-', 'wavespeed-', 'replicate-'].some((prefix) => code.startsWith(prefix)) && modelFamily === 'gpt-image-2'
  return {
    id: code,
    code,
    label: code,
    capability,
    adapter: 'adapter',
    base_url: 'https://example.test',
    model_name: code,
    enabled,
    is_default: code === 'doubao-seed-2-0-mini' || code === 'apimodels-nano-pro-generate' || code === 'cometapi-seedance-2-0-video',
    is_fallback: code === 'qwen-3-6' || code === 'kie-nano-2-generate',
    route_roles: {
      ...(code === 'doubao-seed-2-0-mini' ? { llm: 'primary' as const } : {}),
      ...(code === 'qwen-3-6' ? { llm: 'backup1' as const } : {}),
      ...(code === 'apimodels-nano-pro-generate' ? { suite_fidelity: 'primary' as const } : {}),
      ...(code === 'kie-nano-2-generate' ? { suite_fidelity: 'backup1' as const } : {}),
      ...(code === 'atlas-gpt-image-2-generate' ? { suite_layout: 'primary' as const, aplus_detail: 'primary' as const } : {}),
      ...(code === 'atlas-gpt-image-2-edit' ? { aplus_mobile: 'primary' as const, image_edit: 'primary' as const } : {}),
      ...(code === 'cometapi-seedance-2-0-video' ? { video: 'primary' as const } : {}),
    },
    provider_group: group,
    provider_group_label: group ? providerGroupLabels[group] : null,
    operation,
    supports_custom_size: capability !== 'llm',
    supports_exact_custom_size: modelFamily === 'gpt-image-2' ? !ratioOnlyImage2 : false,
    supports_edit: operation === 'edit' || Boolean(modelFamily?.includes('nano-banana')),
    has_api_key: hasApiKey,
    api_key_masked: hasApiKey ? 'sk-****' : null,
    config: {
      provider_group: group,
      provider_group_label: group ? providerGroupLabels[group] : null,
      operation,
      model_family: modelFamily,
      size: 'follow_frontend',
      parameter_schema: capability === 'llm' ? [] : [
        {
          key: operation === 'video' ? 'aspect_ratio' : modelFamily === 'gpt-image-2' ? 'size' : 'aspect_ratio',
          label: 'size',
          type: 'select',
          options: [{ value: 'follow_frontend', label: 'follow frontend input' }],
        },
      ],
    },
  }
}

const baseProviders = () => [
  provider('atlas-gpt-image-2-generate'),
  provider('atlas-gpt-image-2-edit'),
  provider('qwen-3-6'),
  provider('kie-nano-2-generate'),
  provider('doubao-seed-2-0-mini'),
  provider('apimodels-nano-pro-generate'),
  provider('cometapi-seedance-2-0-video'),
]

describe('provider business display', () => {
  it('requires both enablement and an API key before a provider is effective', () => {
    expect(providerRuntimeState(provider('yunwu-nano-pro', false, true)).tone).toBe('off')
    expect(providerRuntimeState(provider('yunwu-nano-pro', true, false)).tone).toBe('warning')
    expect(providerRuntimeState(provider('yunwu-nano-pro', true, true)).tone).toBe('ready')
  })

  it('groups providers by business route and defaults to the primary provider group', () => {
    const groups = groupProvidersByBusinessRoute(baseProviders())

    expect(groups.map((group) => group.key)).toEqual(['suite_fidelity', 'suite_layout', 'aplus_detail', 'aplus_mobile', 'image_edit', 'video', 'llm'])
    expect(groups[0].defaultProviderGroup).toBe('apimodels')
    expect(groups[0].selectedProviderGroup).toBe('apimodels')
    expect(groups[0].providerGroups.map((item) => item.key)).toEqual(['apimodels', 'kie'])
    expect(groups[0].providers.map((item) => item.code)).toEqual(['apimodels-nano-pro-generate'])
    expect(groups[0].route).toContain('kie-nano-2-generate')
    expect(groups[1].providers.map((item) => item.code)).toEqual(['atlas-gpt-image-2-generate'])
    expect(groups[3].providers.map((item) => item.code)).toEqual(['atlas-gpt-image-2-edit'])
    expect(groups[5].providers.map((item) => item.code)).toEqual(['cometapi-seedance-2-0-video'])
    expect(groups[6].providers.map((item) => item.routeRole)).toEqual(['primary', 'backup1'])
    expect(groups.every((group) => group.ready)).toBe(true)
  })

  it('lets an admin switch a route to another transit provider group', () => {
    const groups = groupProvidersByBusinessRoute(baseProviders(), { suite_fidelity: 'kie' })
    const fidelity = groups.find((group) => group.key === 'suite_fidelity')

    expect(fidelity?.selectionMode).toBe('provider_group')
    expect(fidelity?.selectedProviderGroup).toBe('kie')
    expect(fidelity?.providers.map((item) => item.code)).toEqual(['kie-nano-2-generate'])
  })

  it('exposes a chain configuration mode with all compatible model candidates', () => {
    const groups = groupProvidersByBusinessRoute([
      provider('apimodels-nano-pro-generate'),
      provider('kie-nano-2-generate'),
      provider('atlas-nano-2-generate'),
      provider('runware-nano-2-generate'),
      provider('atlas-gpt-image-2-generate'),
    ], { suite_fidelity: providerRouteChainConfigValue })

    const fidelity = groups.find((group) => group.key === 'suite_fidelity')
    expect(fidelity?.selectionMode).toBe('chain_config')
    expect(fidelity?.providers.map((item) => item.code)).toEqual([
      'apimodels-nano-pro-generate',
      'kie-nano-2-generate',
    ])
    expect(fidelity?.chainCandidates.map((item) => item.code)).toEqual([
      'apimodels-nano-pro-generate',
      'kie-nano-2-generate',
      'atlas-nano-2-generate',
      'runware-nano-2-generate',
    ])
  })

  it('groups routes into the requested major model categories', () => {
    const categories = groupProviderCategoriesByBusinessRoute(baseProviders())

    expect(categories.map((category) => category.key)).toEqual(['suite', 'aplus', 'image_edit', 'video', 'llm'])
    expect(categories[0].groups.map((group) => group.key)).toEqual(['suite_fidelity', 'suite_layout'])
    expect(categories[1].groups.map((group) => group.key)).toEqual(['aplus_detail', 'aplus_mobile'])
    expect(categories[2].groups.map((group) => group.key)).toEqual(['image_edit'])
    expect(categories[3].groups.map((group) => group.key)).toEqual(['video'])
    expect(categories[4].groups.map((group) => group.key)).toEqual(['llm'])
  })

  it('marks a route incomplete when any required provider is unavailable', () => {
    const groups = groupProvidersByBusinessRoute([
      provider('doubao-seed-2-0-mini'),
      provider('qwen-3-6', false, true),
      provider('apimodels-nano-pro-generate'),
      provider('kie-nano-2-generate'),
      provider('atlas-gpt-image-2-generate', true, false),
      provider('atlas-gpt-image-2-edit'),
      provider('cometapi-seedance-2-0-video'),
    ])

    expect(groups.find((group) => group.key === 'llm')?.ready).toBe(false)
    expect(groups.find((group) => group.key === 'suite_fidelity')?.ready).toBe(true)
    expect(groups.find((group) => group.key === 'suite_layout')?.ready).toBe(false)
    expect(groups.find((group) => group.key === 'aplus_mobile')?.ready).toBe(true)
    expect(groups.find((group) => group.key === 'image_edit')?.ready).toBe(true)
    expect(groups.find((group) => group.key === 'video')?.ready).toBe(true)
  })

  it('renders business groups, transit filters, and editable five-slot chains', () => {
    const filterBlock = adminSource.slice(
      adminSource.indexOf('provider-group-filter'),
      adminSource.indexOf('provider-chain-editor'),
    )

    expect(adminSource).toContain('v-for="category in providerCategories"')
    expect(adminSource).toContain('v-for="group in category.groups"')
    expect(adminSource).toContain('providerRuntimeState(provider).label')
    expect(filterBlock).toContain('activeProviderGroupValue(group)')
    expect(filterBlock).toContain('providerGroup in group.providerGroups')
    expect(filterBlock).toContain('providerRouteChainConfigValue')
    expect(filterBlock).not.toContain('<option value="">')
    expect(adminSource).toContain('/admin/provider-routes/${group.key}/chain')
    expect(adminSource).toContain('providerRouteRoleOrder')
    expect(adminSource).toContain('group.chainCandidates')
    expect(adminSource).toContain('routeChainDraft(group)[index]')
  })

  it('renders provider parameter schema instead of hard-coded image controls', () => {
    expect(adminSource).toContain('providerParameterSchema(selectedProvider)')
    expect(adminSource).toContain('provider-parameter-editor')
    expect(adminSource).toContain('providerParameterGroups(selectedProvider)')
    expect(adminSource).toContain("title:'常用参数'")
    expect(adminSource).toContain('不传，使用中转站默认')
    expect(adminSource).toContain('parameterHelpText(parameter)')
    expect(adminSource).toContain('providerParameterOptions(parameter)')
    expect(adminSource).toContain('parameter_values:providerParameterValues(p)')
    expect(adminSource).toContain('savingProvider')
    expect(adminSource).toContain('模型配置保存失败，请检查参数')
    expect(adminSource).toContain("savingProvider ? '保存中...' : '保存配置'")
    expect(adminSource).toContain("['follow_frontend','follow_ratio','auto']")
    expect(adminSource).toContain('class="image2-size-warning"')
    expect(adminSource).not.toContain('providerResolutions(selectedProvider)')
    expect(adminSource).not.toContain("selectedProvider.capability==='image' && Array.isArray(selectedProvider.config.allowed_resolutions)")
    expect(adminSource).not.toContain('Array.isArray(selectedProvider.config.allowed_sizes)')
  })

  it('keeps mobile admin navigation icon-only instead of wrapping labels vertically', () => {
    expect(adminSource).toContain('.admin-nav>button { font-size: 0 !important; justify-content: center; }')
    expect(adminSource).toContain('.admin-nav>button>.anticon { font-size: 18px; }')
  })

  it('shows runtime public asset base URL settings for video generation', () => {
    expect(adminSource).toContain('/admin/runtime-settings')
    expect(adminSource).toContain('PUBLIC_ASSET_BASE_URL')
    expect(adminSource).toContain('LISTINGO_PUBLIC_ASSET_BASE_URL')
  })

  it('shows provider health checks, OCR settings, and model prewarm controls', () => {
    expect(adminSource).toContain('/admin/provider-groups/${groupKey}/health-check')
    expect(adminSource).toContain('healthResults[group.key]')
    expect(adminSource).toContain('/admin/ocr-settings')
    expect(adminSource).toContain('/admin/ocr-settings/prewarm')
    expect(adminSource).toContain('ocr_use_enhanced_variants')
  })

  it('keeps the runtime settings save action visibly primary', () => {
    const primaryRule = [...adminSource.matchAll(/\.admin-primary\s*\{([^}]*)\}/g)]
      .map((match) => match[1])
      .find((rule) => rule.includes('#5b46e8')) ?? ''
    const disabledRule = adminSource.match(/\.admin-primary:disabled\s*\{([^}]*)\}/)?.[1] ?? ''
    const normalizedPrimary = primaryRule.replace(/\s+/g, '')
    const normalizedDisabled = disabledRule.replace(/\s+/g, '')

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
    expect(adminSource).toContain('if(logFilters.value.node)params.node=logFilters.value.node')
    expect(adminSource).toContain('v-model="logFilters.node"')
    expect(adminSource).toContain('v-model="logFilters.status"')
    expect(adminSource).toContain('@click="loadLogs"')
  })

  it('renders premium monitoring dashboards for ops and business metrics', () => {
    expect(adminSource).toContain("key:'ops-monitoring',label:'运维监控'")
    expect(adminSource).toContain("key:'business-metrics',label:'运营指标监控'")
    expect(adminSource).toContain('MonitoringDashboard')
    expect(monitoringDashboardSource).toContain("route.query.mode === 'prototype'")
    expect(monitoringDashboardSource).toContain("router.push({ path: `/admin/${section}`")
    expect(monitoringDashboardSource).toContain('ChartTableToggle')
    expect(monitoringDashboardSource).toContain('MonitoringLineChart')
    expect(monitoringDashboardSource).toContain('ComparisonMatrix')
    expect(monitoringDashboardSource).toContain('UserDrilldownPanel')
    expect(monitoringDashboardSource).toContain('providerMode ===')
    expect(monitoringDashboardSource).toContain('businessChainMode ===')
    expect(monitoringDashboardSource).toContain('onErrorCaptured')
    expect(monitoringDashboardSource).toContain('monitoringError')
    expect(monitoringDashboardSource).toContain('class="monitoring-error-state"')
    expect(monitoringDashboardSource).toContain('function finiteNumber(value: unknown): number')
    expect(userDrilldownSource).toContain('props.prototypeMode ? (businessUserPrototypeData.user_rows || []) : []')
    expect(userDrilldownSource).toContain('catch (error: unknown)')
    expect(userDrilldownSource).toContain('detailError.value = userFacingApiErrorMessage(error)')
    expect(userDrilldownSource).toContain(':rows="detail.platform_rows || []"')
    expect(userDrilldownSource).not.toContain('detail.value.platform_rows')
    expect(monitoringLineChartSource).toContain('finiteNumber(row[metric.key])')
    expect(comparisonMatrixSource).toContain('const numeric = finiteNumber(value)')
    expect(sharePieChartSource).toContain('value: finiteNumber(row[valueKey])')
    expect(metricHelpSource).toContain('a-popover')
    expect(metricHelpSource).toContain('公式')
    expect(metricHelpSource).toContain('数据源')
    expect(monitoringCss).toContain('grid-template-columns: repeat(12')
    expect(monitoringCss).toContain('grid-auto-flow: row dense')
    expect(monitoringCss).toContain('.monitoring-error-state')
    expect(monitoringCss).toContain('.monitoring-inline-error')
    expect(monitoringCss).toContain('.preference-stack')
  })

  it('renders a prompt test workbench wired to current editor content', () => {
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
    expect(adminSource).toContain('assistCopywriting')
    expect(adminSource).toContain('assistVideoCopywriting')
    expect(adminSource).toContain("'content-safety-review'")
    expect(adminSource).toContain("promptDetail.value?.code==='content-safety-review'")
    expect(adminSource).toContain('dry_run:false')
    expect(adminSource).not.toContain('ai_dry_run')
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
