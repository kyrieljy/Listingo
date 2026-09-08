import type {
  AuthUserDto,
  BillingCycle,
  NotificationDto,
  PlanCode,
  PlanEntitlements,
  SubscriptionPlanDto,
  UserRole,
  UserStatus,
} from '../../api/client'

export type { PlanCode as PlanKey, UserRole, UserStatus }

export type AuthUser = {
  id: string
  phone: string
  username: string
  displayName: string
  email: string
  avatarInitials: string
  uid: string
  role: UserRole
  status: UserStatus
  plan: PlanCode
  gender: string
  bio: string
  passwordSet: boolean
  firstPasswordPending: boolean
  lastLoginAt: string
  createdAt: string
  feishuWebhook: string
  feishuWebhookConfigured: boolean
}

export type MembershipPlan = {
  key: PlanCode
  name: string
  price: string
  period: string
  badge?: string
  description: string
  cta: string
  featured?: boolean
  adminOnly?: boolean
  enterprise?: boolean
  billingCycle: BillingCycle | 'none' | 'custom' | 'internal' | 'legacy'
  beans: number | null
  contactSales: boolean
  contactText?: string
  contactPhone?: string
  entitlements: PlanEntitlements
  features: string[]
  source?: SubscriptionPlanDto
}

export type AccountHistoryItem = {
  id: string
  type: 'suite' | 'aplus' | 'video'
  title: string
  status: 'succeeded' | 'running' | 'failed'
  createdAt: string
}

export type AccountMessage = {
  id: string
  title: string
  body: string
  createdAt: string
  unread: boolean
  category: string
}

const emptyEntitlements: PlanEntitlements = { image_generation: true, image_edit: true, batch_generation: false }

function plan(options: Pick<MembershipPlan, 'key' | 'name' | 'price' | 'period' | 'description'> & Partial<MembershipPlan>): MembershipPlan {
  return {
    cta: options.enterprise ? '联系我们' : '立即订阅',
    billingCycle: 'monthly',
    beans: 0,
    contactSales: Boolean(options.enterprise),
    entitlements: emptyEntitlements,
    features: [],
    ...options,
  }
}

export const fallbackPlans: MembershipPlan[] = [
  plan({
    key: 'free',
    name: '免费版',
    price: '¥0',
    period: '',
    description: '未开通会员时可使用已购买的豆子生成图片。',
    cta: '购买豆子',
    billingCycle: 'none',
  }),
  plan({ key: 'monthly_basic', name: '轻量版', price: '¥49', period: '/月', description: '适合刚开始尝试 AI 商品图的个人卖家，满足少量商品上新需求。', beans: 480 }),
  plan({ key: 'monthly_standard', name: '标准版', price: '¥129', period: '/月', badge: '推荐', description: '适合稳定上新的电商卖家，支持商品图、详情图和图片编辑。', featured: true, beans: 1560, entitlements: { ...emptyEntitlements, batch_generation: true, priority_queue: 'basic' } }),
  plan({ key: 'monthly_pro', name: '高级版', price: '¥699', period: '/月', description: '适合多 SKU 上新、批量商品图生产和小团队协作。', beans: 9600, entitlements: { ...emptyEntitlements, batch_generation: true, priority_queue: true, team_collaboration: 'basic' } }),
  plan({ key: 'yearly_basic', name: '轻量年付', price: '¥499', period: '/年', badge: '年付更省', description: '适合少量商品上新，全年豆子可用于商品图、详情图和图片编辑。', billingCycle: 'yearly', beans: 5760, entitlements: { ...emptyEntitlements, batch_generation: true, priority_queue: true } }),
  plan({ key: 'yearly_standard', name: '标准年付', price: '¥1299', period: '/年', badge: '推荐', description: '适合持续上新的卖家，全年更划算，支持批量上传和批量生成。', billingCycle: 'yearly', featured: true, beans: 18000, entitlements: { ...emptyEntitlements, batch_generation: true, priority_queue: true } }),
  plan({ key: 'yearly_flagship', name: '旗舰年付', price: '¥19999', period: '/年', badge: '团队首选', description: '适合团队批量生产电商内容，支持大额豆子、批量任务和团队协作。', billingCycle: 'yearly', beans: 288000, entitlements: { ...emptyEntitlements, batch_generation: 'advanced', priority_queue: true, team_collaboration: true, exclusive_support: true } }),
  plan({
    key: 'enterprise_custom',
    name: '企业定制版',
    price: '联系我们',
    period: '',
    badge: '企业定制',
    description: '面向品牌方、代运营团队和批量内容生产团队，根据用量与需求定制方案。',
    billingCycle: 'custom',
    beans: null,
    enterprise: true,
    contactText: '企业版不展示固定价格，请联系商务获取专属报价。',
    contactPhone: '18928268686',
    features: ['团队协作', 'API 接入可沟通', '定制工作流', '专属客服'],
    entitlements: { ...emptyEntitlements, batch_generation: 'custom', priority_queue: true, team_collaboration: true, api_access: 'negotiable', custom_workflow: true, exclusive_support: true },
  }),
]

export function toAuthUser(dto: AuthUserDto): AuthUser {
  return {
    id: dto.id,
    phone: dto.phone,
    username: dto.username,
    displayName: dto.display_name,
    email: dto.email,
    avatarInitials: dto.avatar_initials,
    uid: dto.uid,
    role: dto.role,
    status: dto.status,
    plan: dto.plan,
    gender: dto.gender,
    bio: dto.bio,
    passwordSet: dto.password_set,
    firstPasswordPending: dto.first_password_pending,
    lastLoginAt: dto.last_login_at || dto.created_at,
    createdAt: dto.created_at,
    feishuWebhook: dto.feishu_webhook,
    feishuWebhookConfigured: dto.feishu_webhook_configured,
  }
}

export function planFromDto(source: SubscriptionPlanDto, billing: BillingCycle = 'monthly'): MembershipPlan {
  const price = source.prices.find((item) => item.billing_cycle === billing) || source.prices[0]
  const enterprise = source.contact_sales || source.is_enterprise
  return {
    key: source.code,
    name: source.name,
    price: enterprise ? '联系我们' : price?.price_label || '',
    period: enterprise ? '' : price?.period_label || '',
    badge: source.badge || undefined,
    description: source.description,
    cta: source.cta || (enterprise ? '联系我们' : '立即订阅'),
    featured: source.recommended,
    adminOnly: source.is_internal,
    enterprise,
    billingCycle: source.billing_cycle,
    beans: source.beans,
    contactSales: source.contact_sales,
    contactText: source.contact_text,
    contactPhone: source.contact_phone,
    entitlements: source.entitlements,
    features: source.features,
    source,
  }
}

export function hasEntitlement(plan: MembershipPlan | null | undefined, key: string): boolean {
  if (!plan) return false
  if (plan.key === 'internal') return true
  return Boolean(plan.entitlements[key])
}

export function messageFromDto(row: NotificationDto): AccountMessage {
  return {
    id: row.id,
    title: row.title,
    body: row.body,
    createdAt: row.created_at,
    unread: row.unread,
    category: row.category,
  }
}

export function planByKey(plans: MembershipPlan[], planCode: PlanCode): MembershipPlan {
  return plans.find((item) => item.key === planCode) || fallbackPlans[0]
}

export function maskPhone(phone: string): string {
  const phoneCountryCodes = ['852', '853', '886', '86', '65', '60', '81', '82', '44', '61', '1']
  const trimmed = phone.trim()
  const rawDigits = phone.replace(/\D/g, '')
  if (trimmed.startsWith('+')) {
    for (const countryCode of phoneCountryCodes) {
      if (!rawDigits.startsWith(countryCode)) continue
      const localDigits = rawDigits.slice(countryCode.length)
      if (countryCode === '86') {
        if (localDigits.length < 7) return phone
        return `${localDigits.slice(0, 3)}****${localDigits.slice(-4)}`
      }
      if (localDigits.length < 7) return phone
      return `+${countryCode} ${localDigits.slice(0, 2)}****${localDigits.slice(-4)}`
    }
  }
  const digits = rawDigits.length === 13 && rawDigits.startsWith('86') ? rawDigits.slice(2) : rawDigits
  if (digits.length < 7) return phone
  return `${digits.slice(0, 3)}****${digits.slice(-4)}`
}

export function resolvePasswordRole(identifier: string): UserRole {
  return identifier.trim().toLowerCase().includes('admin') ? 'admin' : 'user'
}
