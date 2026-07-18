import { describe, expect, it } from 'vitest'

import {
  groupProvidersByBusinessRoute,
  providerRuntimeState,
  type ProviderDisplayRecord,
} from './provider-display'
import adminSource from './AdminView.vue?raw'

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
    is_default: code === 'doubao-seed-2-0-mini' || code === 'yunwu-nano-pro' || code === 'shengsuanyun-seedance-1-5-pro',
    is_fallback: code === 'qwen-3-6' || code === 'yunwu-nano',
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
      provider('qwen-3-6'),
      provider('yunwu-nano'),
      provider('doubao-seed-2-0-mini'),
      provider('yunwu-nano-pro'),
      provider('shengsuanyun-seedance-1-5-pro'),
    ])

    expect(groups.map((group) => group.key)).toEqual(['prompt', 'fidelity', 'layout', 'video'])
    expect(groups.map((group) => group.title)).toEqual([
      '提示词理解与任务规划',
      '商品保持优先',
      '视觉排版优先',
      '15 秒爆款视频生成',
    ])
    expect(groups[0].providers.map((item) => item.role)).toEqual(['主模型', '失败备用'])
    expect(groups[1].providers.map((item) => item.role)).toEqual(['主模型', '失败备用'])
    expect(groups[2].providers.map((item) => item.role)).toEqual(['排版模式模型'])
    expect(groups[3].providers.map((item) => item.role)).toEqual(['视频生成模型'])
    expect(groups.every((group) => group.ready)).toBe(true)
  })

  it('marks a route incomplete when any required provider is unavailable', () => {
    const groups = groupProvidersByBusinessRoute([
      provider('doubao-seed-2-0-mini'),
      provider('qwen-3-6', false, true),
      provider('yunwu-nano-pro'),
      provider('yunwu-nano'),
      provider('yunwu-image-2', true, false),
      provider('shengsuanyun-seedance-1-5-pro'),
    ])

    expect(groups[0].ready).toBe(false)
    expect(groups[0].statusLabel).toBe('链路未完整启用')
    expect(groups[1].ready).toBe(true)
    expect(groups[2].ready).toBe(false)
    expect(groups[3].ready).toBe(true)
  })

  it('renders business groups and explains that enablement alone is insufficient', () => {
    expect(adminSource).toContain('v-for="group in providerGroups"')
    expect(adminSource).toContain('providerRuntimeState(provider).label')
    expect(adminSource).toContain('启用开关只是允许调用')
    expect(adminSource).toContain('未启用')
    expect(adminSource).toContain('缺少密钥')
    expect(adminSource).toContain('当前生效')
    expect(adminSource).toContain('视频模型')
  })

  it('keeps mobile admin navigation icon-only instead of wrapping labels vertically', () => {
    expect(adminSource).toContain('.admin-nav>button { font-size: 0 !important; justify-content: center; }')
    expect(adminSource).toContain('.admin-nav>button>.anticon { font-size: 18px; }')
  })

  it('separates Nano resolution from Image 2 ratio-following size settings', () => {
    expect(adminSource).toContain('providerResolutions(selectedProvider)')
    expect(adminSource).toContain('selectedProvider.adapter===\'gemini_generate_content\'')
    expect(adminSource).not.toContain('v-model="selectedProvider.config.aspect_ratio"')
    expect(adminSource).toContain('class="image2-size-warning"')
    expect(adminSource).toContain('value="follow_ratio"')
    expect(adminSource).toContain('高级固定尺寸')
  })

  it('shows runtime public asset base URL settings for video generation', () => {
    expect(adminSource).toContain('/admin/runtime-settings')
    expect(adminSource).toContain('PUBLIC_ASSET_BASE_URL')
    expect(adminSource).toContain('LISTINGO_PUBLIC_ASSET_BASE_URL')
  })
})
