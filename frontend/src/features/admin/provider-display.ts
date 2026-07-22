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
  has_api_key: boolean
  api_key_masked: string | null
  config: Record<string, unknown>
}

export type ProviderRuntimeState = {
  label: '当前生效' | '未启用' | '缺少密钥'
  tone: 'ready' | 'off' | 'warning'
  detail: string
}

export type ProviderBusinessItem = ProviderDisplayRecord & { role: string }

export type ProviderBusinessGroup = {
  key: string
  title: string
  description: string
  route: string
  providers: ProviderBusinessItem[]
  ready: boolean
  statusLabel: '链路已生效' | '链路未完整启用'
}

const businessRoutes = [
  {
    key: 'prompt',
    title: '提示词理解与任务规划',
    description: '所有 Live 套图、AI 帮写和二次编辑共用的语言模型链路。',
    route: 'Doubao Seed 2.0 Mini 主用 → Qwen‑3.6 失败备用',
    members: [
      { code: 'doubao-seed-2-0-mini', role: '主模型' },
      { code: 'qwen-3-6', role: '失败备用' },
    ],
  },
  {
    key: 'fidelity',
    title: '商品保持优先',
    description: '前台选择“商品保持优先”时使用，强调商品外观、颜色、结构与标签一致。',
    route: 'Nano Banana Pro 主用 → Nano Banana 2 失败备用',
    members: [
      { code: 'yunwu-nano-pro', role: '主模型' },
      { code: 'yunwu-nano', role: '失败备用' },
    ],
  },
  {
    key: 'layout',
    title: '视觉排版优先',
    description: '前台选择“视觉排版优先”时使用，强化文字呈现和海报版式。',
    route: 'Image 2 单模型执行',
    members: [
      { code: 'yunwu-image-2', role: '排版模式模型' },
    ],
  },
  {
    key: 'aplus-mobile-edit',
    title: '高级 A+ 移动端 Edit 模型',
    description: '仅在高级 A+ 同时选择 Web 和移动端时，用 Web 成图派生 600:450 移动端版式；移动端单选走普通生图。',
    route: 'Web+Mobile 时走独立低成本 edit URL',
    members: [
      { code: 'aplus-mobile-edit-low-cost', role: '移动端派生模型' },
    ],
  },
  {
    key: 'video',
    title: '15 秒爆款视频生成',
    description: '前台视频模块使用的 Seedance 异步视频生成链路，接收商品图公网地址与导演脚本。',
    route: '胜算云 Seedance 1.5 Pro',
    members: [
      { code: 'shengsuanyun-seedance-1-5-pro', role: '视频生成模型' },
    ],
  },
] as const

export function providerRuntimeState(provider: ProviderDisplayRecord): ProviderRuntimeState {
  if (!provider.enabled) {
    return { label: '未启用', tone: 'off', detail: '启用开关关闭，Live 任务不会调用此模型' }
  }
  if (!provider.has_api_key) {
    return { label: '缺少密钥', tone: 'warning', detail: 'Provider 已启用，但缺少 API Key，仍不能调用' }
  }
  return { label: '当前生效', tone: 'ready', detail: '已启用且密钥已配置，当前业务路由可以调用' }
}

export function groupProvidersByBusinessRoute(providers: ProviderDisplayRecord[]): ProviderBusinessGroup[] {
  const byCode = new Map(providers.map((provider) => [provider.code, provider]))
  return businessRoutes.map((group) => {
    const members: ProviderBusinessItem[] = []
    for (const member of group.members) {
      const provider = byCode.get(member.code)
      if (provider) members.push({ ...provider, role: member.role })
    }
    const ready = members.length === group.members.length
      && members.every((provider) => providerRuntimeState(provider).tone === 'ready')
    return {
      key: group.key,
      title: group.title,
      description: group.description,
      route: group.route,
      providers: members,
      ready,
      statusLabel: ready ? '链路已生效' : '链路未完整启用',
    }
  })
}
