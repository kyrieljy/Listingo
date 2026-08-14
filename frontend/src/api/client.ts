import axios, { type AxiosError } from 'axios'

export const api = axios.create({ baseURL: '/api/v1', timeout: 20_000, withCredentials: true })
const GENERATION_REQUEST_TIMEOUT_MS = 900_000
const OCR_REQUEST_TIMEOUT_MS = 120_000
const IMAGE_EDIT_REQUEST_TIMEOUT_MS = 900_000

type ApiErrorPayload = {
  detail?: unknown
  message?: unknown
  error?: unknown
}

type ApiErrorLike = Partial<AxiosError<ApiErrorPayload>> & {
  response?: {
    status?: number
    data?: ApiErrorPayload | unknown
  }
}

const HTTP_STATUS_MESSAGES: Record<number, string> = {
  400: '请求参数有误，请检查后重试',
  401: '登录状态已过期，请重新登录',
  403: '没有权限执行该操作',
  404: '请求的内容不存在',
  409: '信息已存在或状态冲突，请检查后重试',
  422: '提交的信息有误，请检查后重试',
  429: '操作过于频繁，请稍后再试',
}

function readableDetail(value: unknown): string {
  if (typeof value === 'string') return value.trim()
  if (Array.isArray(value)) {
    return value
      .map((item) => {
        if (typeof item === 'string') return item.trim()
        if (item && typeof item === 'object') {
          const record = item as Record<string, unknown>
          const message = readableDetail(record.msg ?? record.message ?? record.detail)
          if (message) return message
        }
        return ''
      })
      .filter(Boolean)
      .join('；')
  }
  if (value && typeof value === 'object') {
    const record = value as Record<string, unknown>
    return readableDetail(record.detail ?? record.message ?? record.error)
  }
  return ''
}

function fallbackStatusMessage(status?: number, url?: string): string {
  if (status === 401 && url?.includes('/auth/password/login')) return '账号或密码不正确'
  if (typeof status === 'number' && status >= 500) return '服务暂时不可用，请稍后再试'
  if (typeof status === 'number' && HTTP_STATUS_MESSAGES[status]) return HTTP_STATUS_MESSAGES[status]
  return '操作失败，请稍后重试'
}

export function userFacingApiErrorMessage(error: unknown): string {
  const apiError = error as ApiErrorLike
  const status = apiError.response?.status
  const url = apiError.config?.url
  const detail = readableDetail(apiError.response?.data)
  if (detail) return detail
  if (apiError.code === 'ECONNABORTED') return '请求超时，请稍后重试'
  if (apiError.response) return fallbackStatusMessage(status, url)
  if (axios.isAxiosError(error)) return '网络连接异常，请检查网络后重试'

  const rawMessage = error instanceof Error ? error.message.trim() : ''
  if (rawMessage && !rawMessage.startsWith('Request failed with status code')) return rawMessage
  return fallbackStatusMessage(status, url)
}

api.interceptors.response.use(
  (response) => response,
  (error: AxiosError<ApiErrorPayload>) => {
    const normalized = new Error(userFacingApiErrorMessage(error)) as Error & {
      cause?: unknown
      code?: string
      response?: unknown
      status?: number
    }
    normalized.cause = error
    normalized.code = error.code
    normalized.response = error.response
    normalized.status = error.response?.status
    return Promise.reject(normalized)
  },
)

export type Asset = {
  id: string
  original_name: string
  url: string
  width: number
  height: number
}
export type Version = { id: string; parent_version_id: string | null; version_no: number; instruction: string; url: string; created_at: string }
export type JobItem = { id: string; index: number; image_type: string; prompt_text: string; status: string; provider_id?: string | null; provider_task_id?: string | null; error: string | null; current_version_id: string | null; versions: Version[] }
export type Job = { id: string; status: string; dry_run: boolean; progress: number; count: number; params: Record<string, unknown>; error: string | null; created_at: string; items: JobItem[] }
export type DownloadFormat = 'zip' | 'long_image'
export type ImageTextBox = { x: number; y: number; width: number; height: number }
export type ImageTextLine = { id: string; index: number; text: string; confidence: number; bbox: ImageTextBox }
export type ImageTextEditLine = { id?: string | null; index: number; original_text: string; text: string; bbox?: ImageTextBox | null }
export type ImageTextOcrResult = { lines: ImageTextLine[]; warning?: string | null }
export type VideoVersion = Version & { remote_url: string }
export type VideoItem = {
  id: string
  index: number
  video_type: string
  status: string
  provider_id: string | null
  provider_task_id: string | null
  error: string | null
  prompt_text: string
  script_markdown: string
  current_version_id: string | null
  versions: VideoVersion[]
}
export type VideoJob = { id: string; status: string; dry_run: boolean; progress: number; count: number; params: Record<string, unknown>; error: string | null; created_at: string; items: VideoItem[] }
export type AplusOutputMode = 'detail' | 'amazon_aplus_standard' | 'amazon_aplus_advanced_web' | 'amazon_aplus_advanced_mobile'
export type AplusOutputTarget = { mode: AplusOutputMode; aspect_ratio: string }
export type AplusItem = {
  id: string
  index: number
  module_index: number
  module_name: string
  output_mode: string
  aspect_ratio: string
  image_prompt: string
  copy_requirements: string
  prompt_text: string
  status: string
  provider_id: string | null
  provider_task_id: string | null
  source_web_item_id: string | null
  error: string | null
  current_version_id: string | null
  versions: Version[]
}
export type AplusJob = {
  id: string
  job_type: string
  status: string
  dry_run: boolean
  progress: number
  count: number
  params: Record<string, unknown>
  source_plan_job_id: string | null
  error: string | null
  created_at: string
  completed_at?: string | null
  items: AplusItem[]
}
export type PromptTestRun = {
  id: string
  prompt_id: string
  prompt_code: string
  test_type: 'llm_output' | 'full_chain'
  status: string
  progress: number
  prompt_content_sha256: string
  input_params: Record<string, unknown>
  raw_output: string
  parsed_output: Record<string, unknown>
  validation_errors: string[]
  related_job_type: string | null
  related_job_id: string | null
  artifact_urls: string[]
  provider_code: string | null
  error: string | null
  created_at: string
  updated_at: string
}

export type WorkspaceConfig = {
  max_upload_bytes: number
  max_batch_tasks: number
  max_batch_item_assets: number
  max_active_batch_items: number
  max_provider_concurrency: number
}

export type BatchBusinessType = 'suite' | 'aplus'
export type BatchItem = {
  id: string
  index: number
  name: string
  status: string
  thumbnail_url?: string | null
  completed_image_count: number
  failed_image_count: number
  total_image_count: number
  params: Record<string, unknown>
  asset_ids: string[]
  generation_job_id: string | null
  aplus_plan_job_id: string | null
  aplus_generation_job_id: string | null
  error: string | null
  started_at: string | null
  completed_at: string | null
  generation_job?: Job | null
  aplus_plan_job?: AplusJob | null
  aplus_generation_job?: AplusJob | null
}
export type BatchJob = {
  id: string
  business_type: BatchBusinessType
  status: string
  global_params: Record<string, unknown>
  total_count: number
  completed_count: number
  failed_count: number
  progress: number
  notification_config: Record<string, unknown>
  error: string | null
  started_at: string | null
  completed_at: string | null
  created_at: string
  updated_at: string
  items: BatchItem[]
}

export type UserRole = 'user' | 'admin'
export type UserStatus = 'active' | 'disabled'
export type PlanCode = 'free' | 'standard' | 'advanced' | 'enterprise' | 'internal'

export type AuthUserDto = {
  id: string
  phone: string
  phone_masked: string
  username: string
  display_name: string
  email: string
  avatar_initials: string
  uid: string
  role: UserRole
  status: UserStatus
  plan: PlanCode
  gender: string
  bio: string
  password_set: boolean
  first_password_pending: boolean
  last_login_at: string | null
  created_at: string
}

export type AuthMeResponse = { user: AuthUserDto | null; unread_count: number }
export type SmsPurpose = 'login' | 'register' | 'reset_password' | 'change_phone' | 'admin'
export type SmsSendResponse = { ok: boolean; expires_in: number; message: string; debug_code?: string | null }
export type PlanPriceDto = { id: string; billing_cycle: 'monthly' | 'yearly'; amount_cents: number | null; currency: string; price_label: string; period_label: string }
export type PlanQuotaRuleDto = { id: string; action_key: string; action_label: string; unit: string; monthly_limit: number | null; cost_multiplier: number; warning_threshold: number; enabled: boolean }
export type SubscriptionPlanDto = {
  id: string
  code: PlanCode
  name: string
  description: string
  badge: string
  cta: string
  enabled: boolean
  visible: boolean
  is_internal: boolean
  is_enterprise: boolean
  features: string[]
  contact_text: string
  contact_phone: string
  prices: PlanPriceDto[]
  quota_rules: PlanQuotaRuleDto[]
  sort_order: number
}
export type QuotaRowDto = PlanQuotaRuleDto & { used: number; remaining: number | null; period: string }
export type QuotaSummaryDto = { plan: SubscriptionPlanDto; period: string; rows: QuotaRowDto[] }
export type PaymentOrderDto = {
  id: string
  order_no: string
  plan_code: PlanCode
  plan_name: string
  billing_cycle: 'monthly' | 'yearly'
  amount_cents: number | null
  currency: string
  status: string
  paid_at: string | null
  expires_at: string | null
  created_at: string
}
export type NotificationDto = { id: string; category: string; title: string; body: string; unread: boolean; metadata: Record<string, unknown>; created_at: string; read_at: string | null }
export type LoginEventDto = { id: string; method: string; status: string; ip_address: string; user_agent: string; message: string; created_at: string }
export type MonitoringGranularity = 'hour' | 'day' | 'week'
export type MonitoringQuery = { start_at?: string; end_at?: string; granularity?: MonitoringGranularity }
export type AnalyticsEventPayload = {
  session_id?: string
  event_name: string
  event_type?: 'view' | 'click' | 'submit' | 'download' | string
  surface?: string
  business_type?: string
  feature_key?: string
  platform?: string
  market?: string
  language?: string
  metadata?: Record<string, unknown>
}

export async function uploadAsset(file: File): Promise<Asset> {
  const form = new FormData()
  form.append('file', file)
  return (await api.post('/assets', form)).data
}

export async function getWorkspaceConfig(): Promise<WorkspaceConfig> {
  return (await api.get('/workspace-config')).data
}

export async function trackAnalyticsEvent(payload: AnalyticsEventPayload): Promise<void> {
  await api.post('/analytics/events', payload, { timeout: 5_000 })
}

export async function createJob(payload: Record<string, unknown>): Promise<Job> {
  return (await api.post('/generation-jobs', payload, { timeout: GENERATION_REQUEST_TIMEOUT_MS })).data
}

export async function getJob(id: string): Promise<Job> {
  return (await api.get(`/generation-jobs/${id}`)).data
}

export async function cancelJob(id: string): Promise<Job> {
  return (await api.post(`/generation-jobs/${id}/cancel`)).data
}

export async function listJobs(): Promise<Job[]> {
  return (await api.get('/generation-jobs')).data
}

export async function assistCopywriting(payload: {
  asset_ids: string[]
  platform: string
  market: string
  language: string
  selling_points: string
  dry_run: boolean
}): Promise<{ selling_points: string; dry_run: boolean; provider_code: string | null }> {
  return (await api.post('/copywriting-assist', payload)).data
}

export async function assistVideoCopywriting(payload: Record<string, unknown>): Promise<{ selling_points: string; dry_run: boolean; provider_code: string | null }> {
  return (await api.post('/video-copywriting-assist', payload)).data
}

export async function createVideoJob(payload: Record<string, unknown>): Promise<VideoJob> {
  return (await api.post('/video-jobs', payload, { timeout: GENERATION_REQUEST_TIMEOUT_MS })).data
}

export async function getVideoJob(id: string): Promise<VideoJob> {
  return (await api.get(`/video-jobs/${id}`)).data
}

export async function cancelVideoJob(id: string): Promise<VideoJob> {
  return (await api.post(`/video-jobs/${id}/cancel`)).data
}

export async function listVideoJobs(): Promise<VideoJob[]> {
  return (await api.get('/video-jobs')).data
}

export async function createAplusPlanJob(payload: Record<string, unknown>): Promise<AplusJob> {
  return (await api.post('/aplus-plan-jobs', payload, { timeout: GENERATION_REQUEST_TIMEOUT_MS })).data
}

export async function getAplusPlanJob(id: string): Promise<AplusJob> {
  return (await api.get(`/aplus-plan-jobs/${id}`)).data
}

export async function listAplusPlanJobs(): Promise<AplusJob[]> {
  return (await api.get('/aplus-plan-jobs')).data
}

export async function cancelAplusPlanJob(id: string): Promise<AplusJob> {
  return (await api.post(`/aplus-plan-jobs/${id}/cancel`)).data
}

export async function createAplusGenerationJob(payload: Record<string, unknown>): Promise<AplusJob> {
  return (await api.post('/aplus-generation-jobs', payload, { timeout: GENERATION_REQUEST_TIMEOUT_MS })).data
}

export async function getAplusGenerationJob(id: string): Promise<AplusJob> {
  return (await api.get(`/aplus-generation-jobs/${id}`)).data
}

export async function cancelAplusGenerationJob(id: string): Promise<AplusJob> {
  return (await api.post(`/aplus-generation-jobs/${id}/cancel`)).data
}

export async function retryFailedAplusItems(jobId: string): Promise<AplusJob> {
  return (await api.post(`/aplus-generation-jobs/${jobId}/retry-failed`, undefined, { timeout: GENERATION_REQUEST_TIMEOUT_MS })).data
}

export async function listAplusGenerationJobs(): Promise<AplusJob[]> {
  return (await api.get('/aplus-generation-jobs')).data
}

export async function createBatchJob(payload: Record<string, unknown>): Promise<BatchJob> {
  return (await api.post('/batch-jobs', payload, { timeout: GENERATION_REQUEST_TIMEOUT_MS })).data
}

export async function listBatchJobs(): Promise<BatchJob[]> {
  return (await api.get('/batch-jobs')).data
}

export async function getBatchJob(id: string): Promise<BatchJob> {
  return (await api.get(`/batch-jobs/${id}`)).data
}

export async function cancelBatchJob(id: string): Promise<BatchJob> {
  return (await api.post(`/batch-jobs/${id}/cancel`)).data
}

export async function retryFailedBatchJob(id: string): Promise<BatchJob> {
  return (await api.post(`/batch-jobs/${id}/retry-failed`, undefined, { timeout: GENERATION_REQUEST_TIMEOUT_MS })).data
}

export async function createBatchValidationFixtures(businessType: BatchBusinessType): Promise<BatchJob[]> {
  return (await api.post('/batch-jobs/validation-fixtures', { business_type: businessType }, { timeout: GENERATION_REQUEST_TIMEOUT_MS })).data
}

export async function createPromptTestRun(promptId: string, payload: Record<string, unknown>): Promise<PromptTestRun> {
  return (await api.post(`/admin/prompts/${promptId}/test-runs`, payload)).data
}

export async function getPromptTestRun(id: string): Promise<PromptTestRun> {
  return (await api.get(`/admin/prompt-test-runs/${id}`)).data
}

export async function listPromptTestRuns(promptId: string): Promise<PromptTestRun[]> {
  return (await api.get(`/admin/prompts/${promptId}/test-runs`)).data
}

export async function retryFailedVideoItems(jobId: string): Promise<VideoJob> {
  return (await api.post(`/video-jobs/${jobId}/retry-failed`, undefined, { timeout: GENERATION_REQUEST_TIMEOUT_MS })).data
}

export async function editVideoItem(id: string, instruction: string): Promise<VideoVersion> {
  return (await api.post(`/video-items/${id}/versions`, { instruction }, { timeout: GENERATION_REQUEST_TIMEOUT_MS })).data
}

export async function editItem(id: string, instruction: string): Promise<Version> {
  return (await api.post(`/generation-items/${id}/versions`, { instruction }, { timeout: IMAGE_EDIT_REQUEST_TIMEOUT_MS })).data
}

export async function ocrItemText(id: string): Promise<ImageTextOcrResult> {
  return (await api.post(`/generation-items/${id}/text-ocr`, undefined, { timeout: OCR_REQUEST_TIMEOUT_MS })).data
}

export async function editItemText(id: string, lines: ImageTextEditLine[]): Promise<Version> {
  return (await api.post(`/generation-items/${id}/text-versions`, { lines }, { timeout: IMAGE_EDIT_REQUEST_TIMEOUT_MS })).data
}

export async function editAplusItem(id: string, instruction: string): Promise<Version> {
  return (await api.post(`/aplus-items/${id}/versions`, { instruction }, { timeout: IMAGE_EDIT_REQUEST_TIMEOUT_MS })).data
}

export async function retryAplusItem(id: string): Promise<AplusJob> {
  return (await api.post(`/aplus-items/${id}/retry`, undefined, { timeout: GENERATION_REQUEST_TIMEOUT_MS })).data
}

export async function ocrAplusItemText(id: string): Promise<ImageTextOcrResult> {
  return (await api.post(`/aplus-items/${id}/text-ocr`, undefined, { timeout: OCR_REQUEST_TIMEOUT_MS })).data
}

export async function editAplusItemText(id: string, lines: ImageTextEditLine[]): Promise<Version> {
  return (await api.post(`/aplus-items/${id}/text-versions`, { lines }, { timeout: IMAGE_EDIT_REQUEST_TIMEOUT_MS })).data
}

export async function retryFailedItems(jobId: string): Promise<Job> {
  return (await api.post(`/generation-jobs/${jobId}/retry-failed`, undefined, { timeout: GENERATION_REQUEST_TIMEOUT_MS })).data
}

export async function retryItem(id: string): Promise<Job> {
  return (await api.post(`/generation-items/${id}/retry`, undefined, { timeout: GENERATION_REQUEST_TIMEOUT_MS })).data
}

export function generationDownloadUrl(jobId: string, itemIds: string[], format: DownloadFormat = 'zip', includeWatermark = true): string {
  const params = new URLSearchParams({ item_ids: itemIds.join(','), format, include_watermark: String(includeWatermark) })
  return `/api/v1/generation-jobs/${jobId}/download?${params.toString()}`
}

export function videoDownloadUrl(jobId: string, itemIds: string[]): string {
  const params = new URLSearchParams({ item_ids: itemIds.join(',') })
  return `/api/v1/video-jobs/${jobId}/download?${params.toString()}`
}

export function aplusDownloadUrl(jobId: string, itemIds: string[], format: DownloadFormat = 'zip', includeWatermark = true): string {
  const params = new URLSearchParams({ item_ids: itemIds.join(','), format, include_watermark: String(includeWatermark) })
  return `/api/v1/aplus-generation-jobs/${jobId}/download?${params.toString()}`
}

export function batchDownloadUrl(batchId: string, includeWatermark = true): string {
  const params = new URLSearchParams({ include_watermark: String(includeWatermark) })
  return `/api/v1/batch-jobs/${batchId}/download?${params.toString()}`
}

export function batchSelectionDownloadUrl(
  businessType: BatchBusinessType,
  batchItemIds: string[],
  itemIds: string[],
  format: DownloadFormat = 'zip',
  includeWatermark = true,
): string {
  const params = new URLSearchParams({
    business_type: businessType,
    batch_item_ids: batchItemIds.join(','),
    item_ids: itemIds.join(','),
    format,
    include_watermark: String(includeWatermark),
  })
  return `/api/v1/batch-jobs/selection-download?${params.toString()}`
}

export async function sendSmsCodeApi(phone: string, purpose: SmsPurpose): Promise<SmsSendResponse> {
  return (await api.post('/auth/sms/send', { phone, purpose })).data
}

export async function loginWithSmsApi(payload: { phone: string; code: string; mode: 'login' | 'register' }): Promise<AuthMeResponse> {
  return (await api.post('/auth/sms/login', payload)).data
}

export async function registerApi(payload: { username: string; password: string; phone: string; code: string }): Promise<AuthMeResponse> {
  return (await api.post('/auth/register', payload)).data
}

export async function loginWithPasswordApi(payload: { identifier: string; password: string; admin_code?: string }): Promise<AuthMeResponse> {
  return (await api.post('/auth/password/login', payload)).data
}

export async function setFirstPasswordApi(password: string): Promise<AuthMeResponse> {
  return (await api.post('/auth/first-password', { password })).data
}

export async function logoutApi(): Promise<void> {
  await api.post('/auth/logout')
}

export async function getAuthMeApi(): Promise<AuthMeResponse> {
  return (await api.get('/auth/me')).data
}

export async function updateProfileApi(payload: { display_name?: string; email?: string; gender?: string; bio?: string }): Promise<AuthMeResponse> {
  return (await api.patch('/account/profile', payload)).data
}

export async function changePasswordApi(payload: { current_password: string; next_password: string }): Promise<AuthMeResponse> {
  return (await api.post('/account/password', payload)).data
}

export async function startChangePhoneApi(phone: string): Promise<SmsSendResponse> {
  return (await api.post('/account/change-phone/start', { phone })).data
}

export async function confirmChangePhoneApi(phone: string, code: string): Promise<AuthMeResponse> {
  return (await api.post('/account/change-phone/confirm', { phone, code })).data
}

export async function listLoginEventsApi(): Promise<LoginEventDto[]> {
  return (await api.get('/account/login-events')).data
}

export async function listSubscriptionPlansApi(): Promise<SubscriptionPlanDto[]> {
  return (await api.get('/subscription/plans')).data
}

export async function getQuotaMeApi(): Promise<QuotaSummaryDto> {
  return (await api.get('/quota/me')).data
}

export async function createSubscriptionOrderApi(payload: { plan_code: string; billing_cycle: 'monthly' | 'yearly' }): Promise<PaymentOrderDto> {
  return (await api.post('/subscription/orders', payload)).data
}

export async function mockPayOrderApi(orderId: string): Promise<PaymentOrderDto> {
  return (await api.post(`/subscription/orders/${orderId}/mock-pay`)).data
}

export async function listNotificationsApi(): Promise<NotificationDto[]> {
  return (await api.get('/notifications')).data
}

export async function readNotificationApi(id: string): Promise<NotificationDto> {
  return (await api.post(`/notifications/${id}/read`)).data
}

export async function readAllNotificationsApi(): Promise<{ ok: boolean; count: number }> {
  return (await api.post('/notifications/read-all')).data
}

export async function adminListUsersApi(): Promise<AuthUserDto[]> {
  return (await api.get('/admin/users')).data
}

export async function adminUpdateUserApi(id: string, payload: { role?: UserRole; status?: UserStatus; plan_code?: string }): Promise<AuthUserDto> {
  return (await api.patch(`/admin/users/${id}`, payload)).data
}

export async function adminListPlansApi(): Promise<SubscriptionPlanDto[]> {
  return (await api.get('/admin/subscription-plans')).data
}

export async function adminUpdatePlanApi(id: string, payload: Partial<Pick<SubscriptionPlanDto, 'name' | 'description' | 'badge' | 'cta' | 'visible' | 'enabled' | 'features' | 'contact_text' | 'contact_phone'>>): Promise<SubscriptionPlanDto> {
  return (await api.patch(`/admin/subscription-plans/${id}`, payload)).data
}

export async function adminUpdateQuotaRuleApi(id: string, payload: { monthly_limit?: number | null; cost_multiplier?: number; warning_threshold?: number; enabled?: boolean }): Promise<PlanQuotaRuleDto> {
  return (await api.patch(`/admin/quota-rules/${id}`, payload)).data
}

export async function adminListPaymentOrdersApi(): Promise<PaymentOrderDto[]> {
  return (await api.get('/admin/payment-orders')).data
}

export async function adminGetSmsSettingsApi(): Promise<Record<string, unknown>> {
  return (await api.get('/admin/sms-settings')).data
}

export async function adminUpdateSmsSettingsApi(payload: Record<string, unknown>): Promise<Record<string, unknown>> {
  return (await api.patch('/admin/sms-settings', payload)).data
}

export async function adminBroadcastNotificationApi(payload: { title: string; body: string; user_ids?: string[] }): Promise<{ ok: boolean; count: number }> {
  return (await api.post('/admin/notifications/broadcast', payload)).data
}

export async function adminGetOpsMonitoringApi(params?: MonitoringQuery): Promise<Record<string, unknown>> {
  return (await api.get('/admin/ops-monitoring', { params })).data
}

export async function adminGetBusinessMetricsApi(params?: MonitoringQuery): Promise<Record<string, unknown>> {
  return (await api.get('/admin/business-metrics', { params })).data
}

export async function adminListBusinessMetricUsersApi(params?: MonitoringQuery & { limit?: number }): Promise<Record<string, unknown>> {
  return (await api.get('/admin/business-metrics/users', { params })).data
}

export async function adminGetBusinessUserMetricsApi(userId: string, params?: MonitoringQuery): Promise<Record<string, unknown>> {
  return (await api.get(`/admin/business-metrics/users/${userId}`, { params })).data
}
