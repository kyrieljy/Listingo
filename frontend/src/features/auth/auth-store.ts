import { computed, ref } from 'vue'
import { defineStore } from 'pinia'
import { message } from 'ant-design-vue'
import {
  changePasswordApi,
  confirmChangePhoneApi,
  createSubscriptionOrderApi,
  getAuthMeApi,
  getQuotaMeApi,
  listLoginEventsApi,
  listNotificationsApi,
  listSubscriptionPlansApi,
  loginWithPasswordApi,
  loginWithSmsApi,
  logoutApi,
  mockPayOrderApi,
  readAllNotificationsApi,
  readNotificationApi,
  registerApi,
  sendSmsCodeApi,
  setFirstPasswordApi,
  startChangePhoneApi,
  updateProfileApi,
  type LoginEventDto,
  type PaymentOrderDto,
  type SmsPurpose,
  type SubscriptionPlanDto,
} from '../../api/client'
import {
  fallbackPlans,
  messageFromDto,
  planByKey,
  planFromDto,
  quotaFromDto,
  toAuthUser,
  type AccountHistoryItem,
  type AccountMessage,
  type AuthUser,
  type MembershipPlan,
  type PlanKey,
  type QuotaUsage,
} from './auth-model'

export const useAuthStore = defineStore('auth', () => {
  const user = ref<AuthUser | null>(null)
  const avatarDataUrl = ref('')
  const plansRaw = ref<SubscriptionPlanDto[]>([])
  const quotaUsage = ref<QuotaUsage[]>([])
  const accountMessages = ref<AccountMessage[]>([])
  const loginEvents = ref<LoginEventDto[]>([])
  const unreadCount = ref(0)
  const lastMockCode = ref('')
  const loading = ref(false)

  const plans = computed<MembershipPlan[]>(() => plansRaw.value.length ? plansRaw.value.map((plan) => planFromDto(plan)) : fallbackPlans)
  const isAuthenticated = computed(() => Boolean(user.value))
  const isAdmin = computed(() => user.value?.role === 'admin')
  const currentPlan = computed(() => planByKey(plans.value, user.value?.plan ?? 'free'))
  const userAvatarUrl = computed(() => avatarDataUrl.value)
  const canExportWithoutWatermark = computed(() => Boolean(user.value && ['standard', 'advanced', 'enterprise', 'internal'].includes(user.value.plan)))
  const historyItems = computed<AccountHistoryItem[]>(() => [])

  function avatarStorageKey(id: string): string {
    return `listingo.avatar.${id}`
  }

  function loadStoredAvatar(nextUser = user.value): void {
    if (typeof window === 'undefined' || !nextUser) {
      avatarDataUrl.value = ''
      return
    }
    avatarDataUrl.value = window.localStorage.getItem(avatarStorageKey(nextUser.id)) || ''
  }

  function resizeAvatarFile(file: File): Promise<string> {
    return new Promise((resolve, reject) => {
      const objectUrl = URL.createObjectURL(file)
      const image = new Image()
      image.onload = () => {
        URL.revokeObjectURL(objectUrl)
        const size = 320
        const canvas = document.createElement('canvas')
        const context = canvas.getContext('2d')
        if (!context) {
          reject(new Error('浏览器暂不支持头像处理'))
          return
        }
        const sourceSize = Math.min(image.naturalWidth, image.naturalHeight)
        const sourceX = Math.max(0, (image.naturalWidth - sourceSize) / 2)
        const sourceY = Math.max(0, (image.naturalHeight - sourceSize) / 2)
        canvas.width = size
        canvas.height = size
        context.drawImage(image, sourceX, sourceY, sourceSize, sourceSize, 0, 0, size, size)
        resolve(canvas.toDataURL('image/jpeg', 0.88))
      }
      image.onerror = () => {
        URL.revokeObjectURL(objectUrl)
        reject(new Error('头像图片读取失败'))
      }
      image.src = objectUrl
    })
  }

  function apiErrorMessage(error: unknown, fallback: string): string {
    const detail = (error as { response?: { data?: { detail?: unknown } } })?.response?.data?.detail
    if (typeof detail === 'string' && detail.trim()) return detail
    if (Array.isArray(detail) && detail.length) return detail.map((item) => typeof item === 'string' ? item : JSON.stringify(item)).join('；')
    const message = error instanceof Error ? error.message.trim() : ''
    if (message && !message.startsWith('Request failed with status code')) return message
    return fallback
  }

  function applyAuthResponse(response: { user: Parameters<typeof toAuthUser>[0] | null; unread_count: number }): void {
    user.value = response.user ? toAuthUser(response.user) : null
    unreadCount.value = response.unread_count
    loadStoredAvatar(user.value)
  }

  async function loadPlans(): Promise<void> {
    plansRaw.value = await listSubscriptionPlansApi()
  }

  async function loadQuota(): Promise<void> {
    if (!user.value) {
      quotaUsage.value = []
      return
    }
    const data = await getQuotaMeApi()
    quotaUsage.value = data.rows.map(quotaFromDto)
    const backendPlan = data.plan
    if (!plansRaw.value.some((plan) => plan.code === backendPlan.code)) plansRaw.value = [...plansRaw.value, backendPlan]
  }

  async function loadNotifications(): Promise<void> {
    if (!user.value) {
      accountMessages.value = []
      unreadCount.value = 0
      return
    }
    const rows = await listNotificationsApi()
    accountMessages.value = rows.map(messageFromDto)
    unreadCount.value = accountMessages.value.filter((item) => item.unread).length
  }

  async function loadLoginEvents(): Promise<void> {
    if (!user.value) {
      loginEvents.value = []
      return
    }
    loginEvents.value = await listLoginEventsApi()
  }

  async function hydrate(): Promise<void> {
    loading.value = true
    try {
      await loadPlans()
      const response = await getAuthMeApi()
      applyAuthResponse(response)
      if (user.value) await Promise.all([loadQuota(), loadNotifications(), loadLoginEvents()])
    } finally {
      loading.value = false
    }
  }

  async function sendSmsCode(phone: string, purpose: SmsPurpose): Promise<string> {
    try {
      const result = purpose === 'change_phone' ? await startChangePhoneApi(phone) : await sendSmsCodeApi(phone, purpose)
      lastMockCode.value = result.debug_code || ''
      message.success(result.debug_code ? `${result.message}，调试验证码 ${result.debug_code}` : result.message)
      return result.debug_code || ''
    } catch (error) {
      throw new Error(apiErrorMessage(error, '验证码发送失败，请检查短信服务配置'))
    }
  }

  async function loginWithSms(payload: { phone: string; code: string }): Promise<void> {
    applyAuthResponse(await loginWithSmsApi(payload))
    await Promise.all([loadQuota(), loadNotifications(), loadLoginEvents()])
    message.success('登录成功')
  }

  async function loginWithPassword(payload: { identifier: string; password: string; adminCode?: string }): Promise<void> {
    applyAuthResponse(await loginWithPasswordApi({ identifier: payload.identifier, password: payload.password, admin_code: payload.adminCode }))
    await Promise.all([loadQuota(), loadNotifications(), loadLoginEvents()])
    message.success(user.value?.role === 'admin' ? '管理员已通过二次验证' : '登录成功')
  }

  async function registerWithPassword(payload: { identifier: string; password: string; phone: string; code: string }): Promise<void> {
    applyAuthResponse(await registerApi({ username: payload.identifier, password: payload.password, phone: payload.phone, code: payload.code }))
    await Promise.all([loadQuota(), loadNotifications(), loadLoginEvents()])
    message.success('账号已创建，手机号已绑定')
  }

  async function setFirstPassword(password: string): Promise<void> {
    applyAuthResponse(await setFirstPasswordApi(password))
    message.success('登录密码已设置')
  }

  async function updateProfile(payload: { displayName?: string; email?: string; gender?: string; bio?: string; feishuWebhook?: string }): Promise<void> {
    applyAuthResponse(await updateProfileApi({
      display_name: payload.displayName,
      email: payload.email,
      gender: payload.gender,
      bio: payload.bio,
      feishu_webhook: payload.feishuWebhook,
    }))
    message.success('个人资料已保存')
  }

  async function updateAvatarFromFile(file: File): Promise<void> {
    if (!user.value) throw new Error('请先登录后再上传头像')
    if (!['image/jpeg', 'image/png', 'image/webp'].includes(file.type)) {
      message.warning('头像仅支持 JPG、PNG、WebP')
      return
    }
    if (file.size > 10 * 1024 * 1024) {
      message.warning('头像图片不能超过 10MB')
      return
    }
    const nextAvatar = await resizeAvatarFile(file)
    avatarDataUrl.value = nextAvatar
    try {
      window.localStorage.setItem(avatarStorageKey(user.value.id), nextAvatar)
      message.success('头像已更新')
    } catch {
      message.warning('头像已在当前页面更新，但浏览器本地空间不足，刷新后可能不会保留')
    }
  }

  async function changePassword(payload: { currentPassword: string; nextPassword: string }): Promise<void> {
    applyAuthResponse(await changePasswordApi({ current_password: payload.currentPassword, next_password: payload.nextPassword }))
    message.success('登录密码已更新')
  }

  async function confirmChangePhone(phone: string, code: string): Promise<void> {
    applyAuthResponse(await confirmChangePhoneApi(phone, code))
    message.success('手机号已换绑')
  }

  async function choosePlan(planKey: PlanKey, billingCycle: 'monthly' | 'yearly'): Promise<PaymentOrderDto> {
    if (!user.value) throw new Error('请先登录后再选择套餐')
    const order = await createSubscriptionOrderApi({ plan_code: planKey, billing_cycle: billingCycle })
    if (order.status === 'pending') {
      const paid = await mockPayOrderApi(order.id)
      applyAuthResponse(await getAuthMeApi())
      await loadQuota()
      await loadNotifications()
      message.success('支付成功，订阅已生效')
      return paid
    }
    await loadNotifications()
    message.success('企业定制咨询已提交')
    return order
  }

  async function markNotificationRead(id: string): Promise<void> {
    await readNotificationApi(id)
    await loadNotifications()
  }

  async function markAllNotificationsRead(): Promise<void> {
    await readAllNotificationsApi()
    await loadNotifications()
  }

  async function logout(): Promise<void> {
    await logoutApi()
    user.value = null
    avatarDataUrl.value = ''
    quotaUsage.value = []
    accountMessages.value = []
    loginEvents.value = []
    unreadCount.value = 0
    message.success('已退出登录')
  }

  function logoutOtherDevices(): void {
    message.info('当前版本会在后续接入会话管理的批量撤销接口')
  }

  return {
    user,
    plans,
    plansRaw,
    quotaUsage,
    accountMessages,
    loginEvents,
    unreadCount,
    lastMockCode,
    loading,
    isAuthenticated,
    isAdmin,
    currentPlan,
    userAvatarUrl,
    canExportWithoutWatermark,
    historyItems,
    hydrate,
    loadPlans,
    loadQuota,
    loadNotifications,
    loadLoginEvents,
    sendSmsCode,
    loginWithSms,
    loginWithPassword,
    registerWithPassword,
    setFirstPassword,
    updateProfile,
    updateAvatarFromFile,
    changePassword,
    confirmChangePhone,
    choosePlan,
    markNotificationRead,
    markAllNotificationsRead,
    logout,
    logoutOtherDevices,
  }
})
