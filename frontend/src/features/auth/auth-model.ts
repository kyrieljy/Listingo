import type { AuthUserDto, NotificationDto, PlanCode, QuotaRowDto, SubscriptionPlanDto, UserRole, UserStatus } from '../../api/client'

export type { PlanCode as PlanKey, UserRole, UserStatus }

export type QuotaKey =
  | 'image_generation'
  | 'aplus_generation'
  | 'video_generation'
  | 'edit_generation'
  | 'batch_suite'
  | 'batch_aplus'

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
  contactText?: string
  contactPhone?: string
  quota: Record<string, number | 'unlimited'>
  features: string[]
  source?: SubscriptionPlanDto
}

export type QuotaUsage = {
  key: string
  label: string
  used: number
  total: number | 'unlimited'
  remaining: number | null
  unit: string
  period: string
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

export const fallbackPlans: MembershipPlan[] = [
  {
    key: 'free',
    name: '免费版',
    price: '¥0',
    period: '/月',
    description: '适合先体验 Listingo 的基础内容生成流程。',
    cta: '当前可用',
    quota: { image_generation: 20, aplus_generation: 4, video_generation: 2, edit_generation: 10, batch_suite: 2, batch_aplus: 1 },
    features: ['免费体验商品套图', '少量 A+ 详情生成', '基础二次编辑', '历史任务保留 7 天'],
  },
  {
    key: 'standard',
    name: '标准会员',
    price: '¥30.0',
    period: '/月',
    badge: 'VIP',
    description: '适合稳定上新的个人卖家和小型电商团队。',
    cta: '立即订阅',
    quota: { image_generation: 330, aplus_generation: 60, video_generation: 12, edit_generation: 160, batch_suite: 20, batch_aplus: 8 },
    features: ['包含免费版所有权益', '个人商业授权', '付费模板/素材', '智能抠图与二次编辑', '每月赠送生成额度'],
  },
  {
    key: 'advanced',
    name: '高级会员',
    price: '¥88.0',
    period: '/月',
    badge: 'PRO',
    featured: true,
    description: '适合高频 SKU、批量上新和多平台内容生产。',
    cta: '立即订阅',
    quota: { image_generation: 1000, aplus_generation: 240, video_generation: 60, edit_generation: 520, batch_suite: 80, batch_aplus: 30 },
    features: ['包含标准会员所有权益', '更高月度额度', '批量任务优先', '大图与视频生产支持', '额度告急提醒'],
  },
  {
    key: 'enterprise',
    name: '企业定制版',
    price: '联系我们',
    period: '',
    badge: 'TEAM',
    enterprise: true,
    description: '面向团队协作、私有化部署和定制化开发需求。',
    cta: '联系我们',
    contactPhone: '18928268686',
    contactText: '联系商务获取企业定制方案，可支持团队账号、品牌模板、私有化部署、定制化开发和专属额度配置。',
    quota: { image_generation: 20000, aplus_generation: 3000, video_generation: 800, edit_generation: 10000, batch_suite: 1000, batch_aplus: 500 },
    features: ['企业商业授权', '团队账号与额度共享', '品牌导航与工作流定制', 'SSO / 私有化部署方案', '专属支持与定制化开发'],
  },
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

export function planFromDto(plan: SubscriptionPlanDto, billing: 'monthly' | 'yearly' = 'monthly'): MembershipPlan {
  const price = plan.prices.find((item) => item.billing_cycle === billing) || plan.prices[0]
  const quota: Record<string, number | 'unlimited'> = {}
  for (const rule of plan.quota_rules) quota[rule.action_key] = rule.monthly_limit ?? 'unlimited'
  return {
    key: plan.code,
    name: plan.name,
    price: plan.is_enterprise ? '联系我们' : price?.price_label || '',
    period: plan.is_enterprise ? '' : price?.period_label || '',
    badge: plan.badge || undefined,
    description: plan.description,
    cta: plan.cta || (plan.is_enterprise ? '联系我们' : '立即订阅'),
    featured: plan.code === 'advanced',
    adminOnly: plan.is_internal,
    enterprise: plan.is_enterprise,
    contactText: plan.contact_text,
    contactPhone: plan.contact_phone,
    quota,
    features: plan.features,
    source: plan,
  }
}

export function quotaFromDto(row: QuotaRowDto): QuotaUsage {
  return {
    key: row.action_key,
    label: row.action_label,
    used: row.used,
    total: row.monthly_limit ?? 'unlimited',
    remaining: row.remaining,
    unit: row.unit,
    period: row.period,
  }
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

export function planByKey(plans: MembershipPlan[], plan: PlanCode): MembershipPlan {
  return plans.find((item) => item.key === plan) || fallbackPlans[0]
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
