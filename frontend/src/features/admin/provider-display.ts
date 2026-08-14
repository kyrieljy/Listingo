export type ProviderRouteRole = 'primary' | 'backup1' | 'backup2' | 'backup3' | 'backup4'

export const providerRouteRoleOrder: ProviderRouteRole[] = ['primary', 'backup1', 'backup2', 'backup3', 'backup4']
export const providerRouteChainConfigValue = '__chain_config__'

export type ProviderDisplayRecord = {
  id: string
  code: string
  label: string
  capability: string
  adapter: string
  base_url: string
  model_name: string
  enabled: boolean
  is_default: boolean
  is_fallback: boolean
  route_roles: Record<string, ProviderRouteRole>
  provider_group?: string | null
  provider_group_label?: string | null
  operation?: string | null
  supports_custom_size?: boolean
  supports_exact_custom_size?: boolean
  supports_edit?: boolean
  pricing?: any | null
  health?: any | null
  has_api_key: boolean
  api_key_masked: string | null
  config: Record<string, any>
}

export type ProviderRuntimeState = {
  label: '当前生效' | '未启用' | '缺少密钥'
  tone: 'ready' | 'off' | 'warning'
  detail: string
}

export type ProviderRouteDefinition = {
  key: string
  categoryKey: string
  categoryTitle: string
  title: string
  description: string
  capability: 'llm' | 'image' | 'video'
}

export type ProviderBusinessItem = ProviderDisplayRecord & { role: string; routeRole: ProviderRouteRole | null }

export type ProviderBusinessGroup = {
  key: string
  categoryKey: string
  categoryTitle: string
  title: string
  description: string
  route: string
  routeModels: string
  providers: ProviderBusinessItem[]
  providerGroups: { key: string; label: string; count: number }[]
  selectedProviderGroup: string
  defaultProviderGroup: string
  selectionMode: 'provider_group' | 'chain_config'
  assignedProviderCodes: string[]
  chainCandidates: ProviderDisplayRecord[]
  ready: boolean
  statusLabel: '链路已生效' | '链路未完整启用'
}

export type ProviderBusinessCategory = {
  key: string
  title: string
  groups: ProviderBusinessGroup[]
}

export const providerRouteDefinitions: ProviderRouteDefinition[] = [
  {
    key: 'suite_fidelity',
    categoryKey: 'suite',
    categoryTitle: '套图',
    title: '保真',
    description: 'Nano Pro 主线 + Nano 2 备线，强调商品外观、颜色、结构与标签一致。',
    capability: 'image',
  },
  {
    key: 'suite_layout',
    categoryKey: 'suite',
    categoryTitle: '套图',
    title: '排版',
    description: 'GPT Image 2 generations，强化文字层级与海报版式。',
    capability: 'image',
  },
  {
    key: 'aplus_detail',
    categoryKey: 'aplus',
    categoryTitle: 'A+',
    title: '详情页',
    description: 'A+ 详情页、普通 A+ 与高级 A+ Web 生图链路。',
    capability: 'image',
  },
  {
    key: 'aplus_mobile',
    categoryKey: 'aplus',
    categoryTitle: 'A+',
    title: '移动端',
    description: '高级 A+ 移动端 600:450，必须使用 GPT Image 2 edit。',
    capability: 'image',
  },
  {
    key: 'image_edit',
    categoryKey: 'image_edit',
    categoryTitle: '改图',
    title: '图片编辑',
    description: '套图与 A+ 结果图二次编辑、文字替换，只调用图片 edit 能力。',
    capability: 'image',
  },
  {
    key: 'video',
    categoryKey: 'video',
    categoryTitle: '视频',
    title: '视频',
    description: 'Seedance 2.0 异步视频生成链路。',
    capability: 'video',
  },
  {
    key: 'llm',
    categoryKey: 'llm',
    categoryTitle: 'LLM',
    title: 'LLM',
    description: '提示词理解、商品识别、文案帮写与安全审计链路，暂不重构。',
    capability: 'llm',
  },
]

const legacyDefaultRoles: Record<string, Record<string, ProviderRouteRole>> = {
  'doubao-seed-2-0-mini': { llm: 'primary' },
  'qwen-3-6': { llm: 'backup1' },
}

function routeRole(provider: ProviderDisplayRecord, routeKey: string): ProviderRouteRole | undefined {
  return provider.route_roles?.[routeKey] ?? legacyDefaultRoles[provider.code]?.[routeKey]
}

export function roleLabel(role: ProviderRouteRole): string {
  return role === 'primary' ? '主模型' : `备${role.replace('backup', '')}`
}

function roleRank(role: ProviderRouteRole | null): number {
  return role ? providerRouteRoleOrder.indexOf(role) : 99
}

export function providerRuntimeState(provider: ProviderDisplayRecord): ProviderRuntimeState {
  if (!provider.enabled) {
    return { label: '未启用', tone: 'off', detail: '启用开关关闭，Live 任务不会调用此模型' }
  }
  if (!provider.has_api_key) {
    return { label: '缺少密钥', tone: 'warning', detail: 'Provider 已启用，但缺少 API Key，仍不能调用' }
  }
  return { label: '当前生效', tone: 'ready', detail: '已启用且密钥已配置，当前业务路由可以调用' }
}

export function providerRoutesForCapability(capability: string): ProviderRouteDefinition[] {
  return providerRouteDefinitions.filter((route) => route.capability === capability)
}

function providerGroupLabel(provider: ProviderDisplayRecord): string {
  return provider.provider_group_label || provider.provider_group || '未分组'
}

function providerModelFamily(provider: ProviderDisplayRecord): string {
  return String(provider.config?.model_family || provider.model_name || provider.code)
}

export function providerMatchesRoute(provider: ProviderDisplayRecord, route: ProviderRouteDefinition): boolean {
  if (provider.capability !== route.capability) return false
  const operation = String(provider.operation || provider.config?.operation || '')
  const family = providerModelFamily(provider)
  const requiresExactSize = route.key === 'suite_layout' || route.key === 'aplus_detail' || route.key === 'aplus_mobile' || route.key === 'image_edit'
  if (requiresExactSize && !provider.supports_exact_custom_size) return false
  if (route.key === 'suite_fidelity') {
    return operation === 'generate' && family.includes('nano-banana')
  }
  if (route.key === 'suite_layout' || route.key === 'aplus_detail') {
    return operation === 'generate' && family === 'gpt-image-2'
  }
  if (route.key === 'aplus_mobile' || route.key === 'image_edit') {
    return operation === 'edit' && family === 'gpt-image-2' && Boolean(provider.supports_edit)
  }
  if (route.key === 'video') {
    return operation === 'video' && family === 'seedance-2.0'
  }
  return true
}

function assignedProviderItems(providers: ProviderDisplayRecord[], route: ProviderRouteDefinition): ProviderBusinessItem[] {
  return providers
    .map((provider): ProviderBusinessItem | null => {
      const assignedRole = routeRole(provider, route.key)
      return assignedRole ? { ...provider, routeRole: assignedRole, role: roleLabel(assignedRole) } : null
    })
    .filter((provider): provider is ProviderBusinessItem => Boolean(provider))
    .sort((left, right) => roleRank(left.routeRole) - roleRank(right.routeRole))
}

export function groupProvidersByBusinessRoute(
  providers: ProviderDisplayRecord[],
  selectedProviderGroups: Record<string, string> = {},
): ProviderBusinessGroup[] {
  return providerRouteDefinitions.map((routeDefinition) => {
    const assignedMembers = assignedProviderItems(providers, routeDefinition)
    const candidates = providers
      .filter((provider) => providerMatchesRoute(provider, routeDefinition))
      .sort((left, right) => {
        const leftRole = routeRole(left, routeDefinition.key) ?? null
        const rightRole = routeRole(right, routeDefinition.key) ?? null
        return roleRank(leftRole) - roleRank(rightRole) || providerGroupLabel(left).localeCompare(providerGroupLabel(right)) || left.label.localeCompare(right.label)
      })
    const providerGroups = Array.from(
      candidates.reduce((map, provider) => {
        const key = provider.provider_group || 'ungrouped'
        const existing = map.get(key)
        map.set(key, { key, label: providerGroupLabel(provider), count: (existing?.count || 0) + 1 })
        return map
      }, new Map<string, { key: string; label: string; count: number }>()),
    ).map(([, value]) => value)
    const primary = assignedMembers.find((provider) => provider.routeRole === 'primary')
    const defaultProviderGroup = primary?.provider_group || providerGroups[0]?.key || ''
    const selectedProviderGroup = selectedProviderGroups[routeDefinition.key] || defaultProviderGroup
    const selectionMode = selectedProviderGroup === providerRouteChainConfigValue ? 'chain_config' : 'provider_group'
    const members = selectionMode === 'chain_config'
      ? assignedMembers
      : candidates
        .filter((provider) => (provider.provider_group || 'ungrouped') === selectedProviderGroup)
        .map((provider) => {
          const assignedRole = routeRole(provider, routeDefinition.key) ?? null
          return { ...provider, routeRole: assignedRole, role: assignedRole ? roleLabel(assignedRole) : '可配置' }
        })

    const ready = Boolean(primary && providerRuntimeState(primary).tone === 'ready')
      && assignedMembers.every((provider) => providerRuntimeState(provider).tone === 'ready')
    const routeModels = assignedMembers.length ? assignedMembers.map((provider) => provider.label).join(' -> ') : '未配置'
    const route = routeModels

    return {
      key: routeDefinition.key,
      categoryKey: routeDefinition.categoryKey,
      categoryTitle: routeDefinition.categoryTitle,
      title: routeDefinition.title,
      description: routeDefinition.description,
      route,
      routeModels,
      providers: members,
      providerGroups,
      selectedProviderGroup,
      defaultProviderGroup,
      selectionMode,
      assignedProviderCodes: assignedMembers.map((provider) => provider.code),
      chainCandidates: candidates,
      ready,
      statusLabel: ready ? '链路已生效' : '链路未完整启用',
    }
  })
}

export function groupProviderCategoriesByBusinessRoute(
  providers: ProviderDisplayRecord[],
  selectedProviderGroups: Record<string, string> = {},
): ProviderBusinessCategory[] {
  const groups = groupProvidersByBusinessRoute(providers, selectedProviderGroups)
  const categoryOrder = ['suite', 'aplus', 'image_edit', 'video', 'llm']
  return categoryOrder
    .map((categoryKey) => {
      const categoryGroups = groups.filter((group) => group.categoryKey === categoryKey)
      return {
        key: categoryKey,
        title: categoryGroups[0]?.categoryTitle ?? categoryKey,
        groups: categoryGroups,
      }
    })
    .filter((category) => category.groups.length > 0)
}
