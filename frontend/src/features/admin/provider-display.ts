export type ProviderRouteRole = 'primary' | 'fallback'

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
  has_api_key: boolean
  api_key_masked: string | null
  config: Record<string, unknown>
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

export type ProviderBusinessItem = ProviderDisplayRecord & { role: string; routeRole: ProviderRouteRole }

export type ProviderBusinessGroup = {
  key: string
  categoryKey: string
  categoryTitle: string
  title: string
  description: string
  route: string
  providers: ProviderBusinessItem[]
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
    description: '商品保持优先链路，强调商品外观、颜色、结构与标签一致。',
    capability: 'image',
  },
  {
    key: 'suite_layout',
    categoryKey: 'suite',
    categoryTitle: '套图',
    title: '排版',
    description: '视觉排版优先链路，强化文字层级与海报版式。',
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
    description: '高级 A+ 移动端 600:450 生成或 Web 成图派生链路。',
    capability: 'image',
  },
  {
    key: 'video',
    categoryKey: 'video',
    categoryTitle: '视频',
    title: '视频',
    description: '爆款视频异步生成链路，接收商品图公网地址与导演脚本。',
    capability: 'video',
  },
  {
    key: 'llm',
    categoryKey: 'llm',
    categoryTitle: 'LLM',
    title: 'LLM',
    description: '提示词理解、商品识别、AI 帮写与安全审计链路。',
    capability: 'llm',
  },
]

const legacyDefaultRoles: Record<string, Record<string, ProviderRouteRole>> = {
  'doubao-seed-2-0-mini': { llm: 'primary' },
  'qwen-3-6': { llm: 'fallback' },
  'yunwu-nano-pro': { suite_fidelity: 'primary' },
  'yunwu-nano': { suite_fidelity: 'fallback' },
  'yunwu-image-2': { suite_layout: 'primary', aplus_detail: 'primary' },
  'aplus-mobile-edit-low-cost': { aplus_mobile: 'primary' },
  'shengsuanyun-doubao-seedance-2-0': { video: 'primary' },
}

function routeRole(provider: ProviderDisplayRecord, routeKey: string): ProviderRouteRole | undefined {
  return provider.route_roles?.[routeKey] ?? legacyDefaultRoles[provider.code]?.[routeKey]
}

function roleLabel(role: ProviderRouteRole): string {
  return role === 'primary' ? '主模型' : '失败备用'
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

export function groupProvidersByBusinessRoute(providers: ProviderDisplayRecord[]): ProviderBusinessGroup[] {
  return providerRouteDefinitions.map((routeDefinition) => {
    const members = providers
      .map((provider) => {
        const assignedRole = routeRole(provider, routeDefinition.key)
        return assignedRole ? { ...provider, routeRole: assignedRole, role: roleLabel(assignedRole) } : null
      })
      .filter((provider): provider is ProviderBusinessItem => Boolean(provider))
      .sort((left, right) => (left.routeRole === right.routeRole ? 0 : left.routeRole === 'primary' ? -1 : 1))

    const primary = members.find((provider) => provider.routeRole === 'primary')
    const fallback = members.find((provider) => provider.routeRole === 'fallback')
    const ready = Boolean(primary && providerRuntimeState(primary).tone === 'ready')
      && (!fallback || providerRuntimeState(fallback).tone === 'ready')
    const route = members.length ? members.map((provider) => `${provider.label} ${provider.role}`).join(' → ') : '未配置'

    return {
      key: routeDefinition.key,
      categoryKey: routeDefinition.categoryKey,
      categoryTitle: routeDefinition.categoryTitle,
      title: routeDefinition.title,
      description: routeDefinition.description,
      route,
      providers: members,
      ready,
      statusLabel: ready ? '链路已生效' : '链路未完整启用',
    }
  })
}

export function groupProviderCategoriesByBusinessRoute(providers: ProviderDisplayRecord[]): ProviderBusinessCategory[] {
  const groups = groupProvidersByBusinessRoute(providers)
  const categoryOrder = ['suite', 'aplus', 'video', 'llm']
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
