<script setup lang="ts">
import { computed, reactive, ref, watch } from 'vue'
import { message } from 'ant-design-vue'
import {
  BellOutlined,
  CheckCircleOutlined,
  CloseOutlined,
  CloudUploadOutlined,
  CreditCardOutlined,
  ExclamationCircleOutlined,
  BarChartOutlined,
  HistoryOutlined,
  LeftOutlined,
  MailOutlined,
  PictureOutlined,
  RightOutlined,
  SafetyCertificateOutlined,
  SettingOutlined,
  UserOutlined,
  VideoCameraOutlined,
} from '@ant-design/icons-vue'
import {
  listAplusGenerationJobs,
  listJobs,
  listVideoJobs,
  type AplusJob,
  type Job,
  type LoginEventDto,
} from '../../api/client'
import { maskPhone, type AccountMessage, type QuotaUsage } from './auth-model'
import { useAuthStore } from './auth-store'

type AccountTab = 'profile' | 'quota' | 'settings' | 'history' | 'messages' | 'privacy'
type TaskStatus = 'completed' | 'running' | 'failed'

type TaskRow = {
  id: string
  taskName: string
  status: TaskStatus
  createdAt: string
  rawId?: string
}

type UsageStats = {
  totalImages: number
  totalVideos: number
  monthImages: number
  monthVideos: number
}

const props = withDefaults(defineProps<{
  open: boolean
  initialTab?: AccountTab
}>(), {
  initialTab: 'profile',
})

const emit = defineEmits<{
  'update:open': [value: boolean]
  'open-pricing': []
}>()

const authStore = useAuthStore()
const activeTab = ref<AccountTab>(props.initialTab)
const avatarInput = ref<HTMLInputElement | null>(null)
const saving = ref(false)
const uploadingAvatar = ref(false)
const loadingTasks = ref(false)
const tasksLoaded = ref(false)
const taskRows = ref<TaskRow[]>([])
const taskPage = ref(1)
const taskPageSize = ref(5)
const loadingQuotaStats = ref(false)
const quotaStatsLoaded = ref(false)
const quotaStats = ref<UsageStats | null>(null)
const messageTab = ref<'unread' | 'read' | 'all'>('unread')
const messagePage = ref(1)
const messagePageSize = ref(5)

const profileForm = reactive({
  displayName: '',
  email: '',
  gender: '男',
  bio: '',
})

const privacy = reactive({
  personalized: true,
  analytics: true,
  historyRetention: true,
})

const dialogOpen = computed({
  get: () => props.open,
  set: (value: boolean) => emit('update:open', value),
})

const navItems = [
  { key: 'profile' as const, label: '账户信息', icon: UserOutlined },
  { key: 'quota' as const, label: '套餐额度', icon: CreditCardOutlined },
  { key: 'settings' as const, label: '账号设置', icon: SettingOutlined },
  { key: 'history' as const, label: '任务历史', icon: HistoryOutlined },
  { key: 'messages' as const, label: '消息中心', icon: BellOutlined },
  { key: 'privacy' as const, label: '隐私设置', icon: SettingOutlined },
]

const genderOptions = ['男', '女']

const sampleTasks: TaskRow[] = [
  { id: 'TASK-20240813-001', taskName: '户外水杯主图', status: 'completed', createdAt: '2024-08-13T09:32:00+08:00' },
  { id: 'TASK-20240813-002', taskName: '旅行背包场景图', status: 'completed', createdAt: '2024-08-13T08:41:00+08:00' },
  { id: 'TASK-20240812-015', taskName: '蓝牙耳机主图', status: 'failed', createdAt: '2024-08-12T16:22:00+08:00' },
  { id: 'LOGIN-20240812-014', taskName: '密码登录成功', status: 'completed', createdAt: '2024-08-12T15:10:00+08:00' },
  { id: 'LOGIN-20240812-013', taskName: '密码登录失败', status: 'failed', createdAt: '2024-08-12T11:03:00+08:00' },
  { id: 'TASK-20240811-009', taskName: '收纳盒主图', status: 'completed', createdAt: '2024-08-11T18:44:00+08:00' },
]

const sampleMessages: AccountMessage[] = [
  { id: 'sample-1', category: '任务完成通知', title: '任务完成通知', body: '任务 TASK-20240813-001 已完成', createdAt: '2024-08-13T09:32:00+08:00', unread: true },
  { id: 'sample-2', category: '系统通知', title: '系统通知', body: '套餐额度已更新', createdAt: '2024-08-13T08:41:00+08:00', unread: true },
  { id: 'sample-3', category: '账户安全提醒', title: '账户安全提醒', body: '检测到新设备登录', createdAt: '2024-08-13T07:15:00+08:00', unread: true },
  { id: 'sample-4', category: '系统通知', title: '系统通知', body: '欢迎使用 Listingo', createdAt: '2024-08-12T16:22:00+08:00', unread: false },
  { id: 'sample-5', category: '任务失败通知', title: '任务失败通知', body: '任务 TASK-20240812-015 处理失败', createdAt: '2024-08-12T15:10:00+08:00', unread: false },
]

const userPhone = computed(() => maskPhone(authStore.user?.phone || ''))
const pageTitle = computed(() => navItems.find((item) => item.key === activeTab.value)?.label || '账户信息')
const messages = computed(() => authStore.user ? authStore.accountMessages : sampleMessages)
const unreadMessages = computed(() => messages.value.filter((item) => item.unread))
const readMessages = computed(() => messages.value.filter((item) => !item.unread))
const visibleMessages = computed(() => {
  if (messageTab.value === 'unread') return unreadMessages.value
  if (messageTab.value === 'read') return readMessages.value
  return messages.value
})
const messageTotalPages = computed(() => Math.max(1, Math.ceil(visibleMessages.value.length / messagePageSize.value)))
const messagePageRows = computed(() => {
  const start = (messagePage.value - 1) * messagePageSize.value
  return visibleMessages.value.slice(start, start + messagePageSize.value)
})
const messagePageNumbers = computed(() => pageWindow(messagePage.value, messageTotalPages.value))
const visibleTasks = computed(() => taskRows.value.length ? taskRows.value : sampleTasks)
const taskTotalPages = computed(() => Math.max(1, Math.ceil(visibleTasks.value.length / taskPageSize.value)))
const taskPageRows = computed(() => {
  const start = (taskPage.value - 1) * taskPageSize.value
  return visibleTasks.value.slice(start, start + taskPageSize.value)
})
const taskPageNumbers = computed(() => pageWindow(taskPage.value, taskTotalPages.value))

const quotaRows = computed<QuotaUsage[]>(() => authStore.quotaUsage.length ? authStore.quotaUsage : [{
  key: 'image_generation',
  label: '图片生成积分',
  used: 420,
  total: 1000,
  remaining: 580,
  unit: '积分',
  period: '',
}])

const mainQuota = computed(() => quotaRows.value.find((item) => typeof item.total === 'number') || quotaRows.value[0])
const quotaPercent = computed(() => {
  const row = mainQuota.value
  if (!row || typeof row.total !== 'number' || row.total <= 0) return 0
  return Math.min(100, Math.round((row.used / row.total) * 100))
})
const quotaUsageMetrics = computed(() => {
  const stats = quotaStats.value
  return [
    { label: '历史生成图片', value: formatMetric(stats?.totalImages), unit: '张', icon: PictureOutlined },
    { label: '历史生成视频', value: formatMetric(stats?.totalVideos), unit: '个', icon: VideoCameraOutlined },
    { label: '本月生成', monthImages: formatMetric(stats?.monthImages), monthVideos: formatMetric(stats?.monthVideos), icon: BarChartOutlined },
  ]
})

const settingsRows = computed(() => [
  { label: '登录手机号', value: userPhone.value || '未绑定', action: '更换' },
  { label: '登录密码', value: authStore.user?.passwordSet ? '********' : '未设置', action: authStore.user?.passwordSet ? '修改' : '设置' },
  { label: '绑定邮箱', value: authStore.user?.email || '未绑定', action: authStore.user?.email ? '更换' : '绑定' },
  { label: '两步验证', value: '未开启', action: '开启' },
  { label: '登录设备管理', value: '3 台设备', action: '管理' },
])

watch(() => props.initialTab, (tab) => {
  if (!props.open) return
  selectTab(tab)
})

watch(() => props.open, (open) => {
  if (!open) return
  activeTab.value = props.initialTab
  syncProfile()
  void ensureTabData(activeTab.value)
})

watch(() => authStore.user?.id, syncProfile, { immediate: true })

watch(taskTotalPages, (total) => {
  if (taskPage.value > total) taskPage.value = total
})

watch(messageTotalPages, (total) => {
  if (messagePage.value > total) messagePage.value = total
})

watch(messageTab, () => {
  messagePage.value = 1
})

watch(() => unreadMessages.value.length, (count) => {
  if (activeTab.value !== 'messages') return
  if (count === 0 && messageTab.value === 'unread') messageTab.value = 'all'
})

function pageWindow(current: number, total: number): number[] {
  const windowSize = Math.min(5, total)
  const start = Math.min(Math.max(1, current - 2), Math.max(1, total - windowSize + 1))
  return Array.from({ length: windowSize }, (_, index) => start + index)
}

function syncProfile(): void {
  profileForm.displayName = authStore.user?.displayName || ''
  profileForm.email = authStore.user?.email || ''
  profileForm.gender = normalizeGender(authStore.user?.gender || '')
  profileForm.bio = authStore.user?.bio || ''
}

function normalizeGender(value: string): string {
  const next = value.trim().toLowerCase()
  if (next.includes('女') || next === 'female' || next === 'woman') return '女'
  return '男'
}

function selectTab(tab: AccountTab): void {
  activeTab.value = tab
  void ensureTabData(tab)
}

async function ensureTabData(tab: AccountTab): Promise<void> {
  try {
    if (tab === 'quota') await Promise.all([authStore.loadQuota(), loadQuotaStats()])
    if (tab === 'messages') {
      await authStore.loadNotifications()
      syncMessageDefaultTab()
    }
    if (tab === 'history') await loadTasks()
  } catch {
    message.warning('当前页面数据加载失败，请稍后重试')
  }
}

function close(): void {
  emit('update:open', false)
}

async function saveProfile(): Promise<void> {
  saving.value = true
  try {
    await authStore.updateProfile({
      displayName: profileForm.displayName.trim(),
      email: profileForm.email.trim(),
      gender: profileForm.gender,
      bio: profileForm.bio.trim(),
    })
  } finally {
    saving.value = false
  }
}

function chooseAvatar(): void {
  avatarInput.value?.click()
}

async function handleAvatarFile(event: Event): Promise<void> {
  const input = event.target as HTMLInputElement
  const file = input.files?.[0]
  input.value = ''
  if (!file) return
  if (file.size > 2 * 1024 * 1024) {
    message.warning('头像图片不能超过 2MB')
    return
  }
  uploadingAvatar.value = true
  try {
    await authStore.updateAvatarFromFile(file)
  } finally {
    uploadingAvatar.value = false
  }
}

function planExpiry(): string {
  const date = new Date()
  date.setMonth(date.getMonth() + 1)
  return formatDateOnly(date.toISOString())
}

function formatDateOnly(value: string): string {
  const date = new Date(value)
  if (Number.isNaN(date.getTime())) return '--'
  return `${date.getFullYear()}/${pad(date.getMonth() + 1)}/${pad(date.getDate())}`
}

function formatDateTime(value: string): string {
  const date = new Date(value)
  if (Number.isNaN(date.getTime())) return '--'
  return `${date.getFullYear()}/${pad(date.getMonth() + 1)}/${pad(date.getDate())} ${pad(date.getHours())}:${pad(date.getMinutes())}`
}

function formatShortTime(value: string): string {
  const date = new Date(value)
  if (Number.isNaN(date.getTime())) return '--'
  return `${pad(date.getMonth() + 1)}/${pad(date.getDate())} ${pad(date.getHours())}:${pad(date.getMinutes())}`
}

function pad(value: number): string {
  return String(value).padStart(2, '0')
}

function quotaTotal(row: QuotaUsage): string {
  return row.total === 'unlimited' ? '不限' : `${row.total.toLocaleString()}`
}

function quotaRemaining(row: QuotaUsage): string {
  if (row.remaining === null) return '不限'
  return `${row.remaining.toLocaleString()}`
}

function formatMetric(value: number | undefined): string {
  return typeof value === 'number' ? value.toLocaleString() : '--'
}

async function loadQuotaStats(): Promise<void> {
  if (quotaStatsLoaded.value || loadingQuotaStats.value) return
  loadingQuotaStats.value = true
  try {
    const [suite, aplusGeneration, videos] = await Promise.all([
      listJobs(),
      listAplusGenerationJobs(),
      listVideoJobs(),
    ])
    const suiteImageRows = suite.map((item) => ({
      count: successItemCount(item.items, item.count, item.status),
      createdAt: item.created_at,
    }))
    const aplusImageRows = aplusGeneration.map((item) => ({
      count: successItemCount(item.items, item.count, item.status),
      createdAt: item.created_at,
    }))
    const videoRows = videos.map((item) => ({
      count: successItemCount(item.items, item.count, item.status),
      createdAt: item.created_at,
    }))
    const imageRows = [...suiteImageRows, ...aplusImageRows]

    quotaStats.value = {
      totalImages: sumCounts(imageRows),
      totalVideos: sumCounts(videoRows),
      monthImages: sumCounts(imageRows.filter((item) => isCurrentMonth(item.createdAt))),
      monthVideos: sumCounts(videoRows.filter((item) => isCurrentMonth(item.createdAt))),
    }
  } catch {
    quotaStats.value = null
  } finally {
    quotaStatsLoaded.value = true
    loadingQuotaStats.value = false
  }
}

function successItemCount<T extends { status: string }>(items: T[] | null | undefined, fallbackCount: number, jobStatus: string): number {
  if (items?.length) return items.filter((item) => isSuccessfulStatus(item.status)).length
  return isSuccessfulStatus(jobStatus) ? fallbackCount : 0
}

function sumCounts(rows: Array<{ count: number }>): number {
  return rows.reduce((total, item) => total + item.count, 0)
}

function isSuccessfulStatus(status: string): boolean {
  return ['succeeded', 'completed'].includes(status)
}

function isCurrentMonth(value: string): boolean {
  const date = new Date(value)
  if (Number.isNaN(date.getTime())) return false
  const now = new Date()
  return date.getFullYear() === now.getFullYear() && date.getMonth() === now.getMonth()
}

async function loadTasks(): Promise<void> {
  if (tasksLoaded.value || loadingTasks.value) return
  loadingTasks.value = true
  try {
    const [suite, aplusGeneration] = await Promise.all([
      listJobs(),
      listAplusGenerationJobs(),
      authStore.loadLoginEvents(),
    ])
    const rows = [
      ...suite.map((item, index) => taskFromJob(item, '商品套图', index)),
      ...aplusGeneration.map((item, index) => taskFromAplus(item, 'A+ 图片生成', index)),
      ...authStore.loginEvents.map((item, index) => taskFromLogin(item, index)),
    ].filter((row) => row.status !== 'running').sort((a, b) => Date.parse(b.createdAt) - Date.parse(a.createdAt))
    taskRows.value = rows
    tasksLoaded.value = true
  } catch {
    taskRows.value = []
    tasksLoaded.value = true
    message.warning('任务历史接口暂时不可用，已显示原型示例数据')
  } finally {
    loadingTasks.value = false
  }
}

function taskFromJob(row: Job, fallback: string, index: number): TaskRow {
  return {
    id: taskCode(row.created_at, index),
    taskName: taskName(row.params, fallback),
    status: taskStatus(row.status),
    createdAt: row.created_at,
    rawId: row.id,
  }
}

function taskFromAplus(row: AplusJob, fallback: string, index: number): TaskRow {
  return {
    id: taskCode(row.created_at, index),
    taskName: taskName(row.params, fallback),
    status: taskStatus(row.status),
    createdAt: row.created_at,
    rawId: row.id,
  }
}

function taskFromLogin(row: LoginEventDto, index: number): TaskRow {
  return {
    id: loginCode(row.created_at, index),
    taskName: loginTaskName(row),
    status: row.status === 'succeeded' ? 'completed' : 'failed',
    createdAt: row.created_at,
    rawId: row.id,
  }
}

function taskCode(createdAt: string, index: number): string {
  const date = new Date(createdAt)
  const stamp = Number.isNaN(date.getTime())
    ? '20240813'
    : `${date.getFullYear()}${pad(date.getMonth() + 1)}${pad(date.getDate())}`
  return `TASK-${stamp}-${String(index + 1).padStart(3, '0')}`
}

function loginCode(createdAt: string, index: number): string {
  const date = new Date(createdAt)
  const stamp = Number.isNaN(date.getTime())
    ? '20240813'
    : `${date.getFullYear()}${pad(date.getMonth() + 1)}${pad(date.getDate())}`
  return `LOGIN-${stamp}-${String(index + 1).padStart(3, '0')}`
}

function loginTaskName(row: LoginEventDto): string {
  const method = row.method === 'password' ? '密码登录' : row.method === 'sms' ? '短信登录' : row.method === 'register' ? '注册登录' : '登录'
  return `${method}${row.status === 'succeeded' ? '成功' : '失败'}`
}

function taskName(params: Record<string, unknown>, fallback: string): string {
  const candidates = ['task_name', 'name', 'title', 'product_name', 'selling_points', 'sellingPoints']
  for (const key of candidates) {
    const value = params[key]
    if (typeof value === 'string' && value.trim()) return value.trim().split(/\r?\n/)[0].slice(0, 20)
  }
  return fallback
}

function taskStatus(status: string): TaskStatus {
  if (['failed', 'cancelled', 'partial_failed'].includes(status)) return 'failed'
  if (['succeeded', 'completed'].includes(status)) return 'completed'
  return 'running'
}

function statusLabel(status: TaskStatus): string {
  if (status === 'failed') return '已失败'
  if (status === 'running') return '进行中'
  return '已完成'
}

function changeTaskPage(page: number): void {
  taskPage.value = Math.min(taskTotalPages.value, Math.max(1, page))
}

function changeMessagePage(page: number): void {
  messagePage.value = Math.min(messageTotalPages.value, Math.max(1, page))
}

function taskPageSizeChanged(): void {
  taskPage.value = 1
}

function viewTask(row: TaskRow): void {
  message.info(`${row.rawId ? '任务详情' : '示例任务'}查看入口待接入`)
}

function settingAction(label: string): void {
  message.info(`${label}功能待接入`)
}

async function openMessage(item: AccountMessage): Promise<void> {
  if (!item.unread || item.id.startsWith('sample-')) return
  await authStore.markNotificationRead(item.id)
}

function viewAllMessages(): void {
  messageTab.value = 'all'
  messagePage.value = 1
}

function syncMessageDefaultTab(): void {
  messageTab.value = unreadMessages.value.length > 0 ? 'unread' : 'all'
  messagePage.value = 1
}

function openPricingFromQuota(): void {
  emit('update:open', false)
  emit('open-pricing')
}

function messageType(item: AccountMessage): string {
  if (item.category === 'security') return '账户安全提醒'
  if (item.category === 'quota') return '额度通知'
  if (item.category === 'payment') return '支付通知'
  if (item.category === 'register') return '系统通知'
  return item.category || item.title || '系统通知'
}

function messageIcon(item: AccountMessage) {
  if (item.category === 'security') return SafetyCertificateOutlined
  if (item.category === 'quota' || item.category === 'payment') return CreditCardOutlined
  if (item.title.includes('失败') || item.body.includes('失败')) return ExclamationCircleOutlined
  if (item.title.includes('完成') || item.body.includes('完成')) return CheckCircleOutlined
  if (item.category === 'admin' || item.category === 'system') return BellOutlined
  return MailOutlined
}

function togglePrivacy(key: keyof typeof privacy): void {
  privacy[key] = !privacy[key]
}

function deleteAccount(): void {
  message.info('删除账户功能待接入')
}
</script>

<template>
  <a-modal
    v-model:open="dialogOpen"
    wrap-class-name="account-modal-wrap"
    :footer="null"
    :closable="false"
    :centered="true"
    :width="980"
  >
    <div class="account-modal-card account-line-modal">
      <aside class="account-sidebar">
        <p>个人中心</p>
        <nav>
          <button
            v-for="item in navItems"
            :key="item.key"
            type="button"
            :class="{ active: activeTab === item.key }"
            @click="selectTab(item.key)"
          >
            <component :is="item.icon" />
            <span>{{ item.label }}</span>
            <small v-if="item.key === 'messages' && unreadMessages.length">{{ unreadMessages.length }}</small>
          </button>
        </nav>
      </aside>

      <main class="account-content">
        <button class="account-close" type="button" aria-label="关闭个人中心" @click="close">
          <CloseOutlined />
        </button>

        <header class="account-content-head">
          <div>
            <h2>{{ pageTitle }}</h2>
          </div>
        </header>

        <section v-if="activeTab === 'profile'" class="account-section">
          <div class="account-avatar-line">
            <img v-if="authStore.userAvatarUrl" :src="authStore.userAvatarUrl" :alt="authStore.user?.displayName || '用户头像'" />
            <span v-else>{{ authStore.user?.avatarInitials }}</span>
            <div>
              <b>{{ authStore.user?.displayName }}</b>
              <small>上次登录 {{ formatDateTime(authStore.user?.lastLoginAt || authStore.user?.createdAt || '') }}</small>
            </div>
            <div class="account-avatar-actions">
              <button class="avatar-upload-button" type="button" :disabled="uploadingAvatar" @click="chooseAvatar"><CloudUploadOutlined />{{ uploadingAvatar ? '上传中' : '上传头像' }}</button>
              <small>支持 JPG / PNG，建议 1:1，≤ 2MB</small>
              <input ref="avatarInput" type="file" accept="image/jpeg,image/png,image/webp" @change="handleAvatarFile" />
            </div>
          </div>

          <div class="account-linear-form">
            <label>
              <span>昵称</span>
              <input v-model="profileForm.displayName" type="text" placeholder="请输入昵称" />
            </label>
            <label>
              <span>邮箱</span>
              <input v-model="profileForm.email" type="email" placeholder="请输入邮箱" />
            </label>
            <div class="account-linear-field">
              <span>性别</span>
              <div class="account-radio-group">
                <label v-for="option in genderOptions" :key="option" :class="{ active: profileForm.gender === option }">
                  <input v-model="profileForm.gender" type="radio" :value="option" />
                  <i />
                  <b>{{ option }}</b>
                </label>
              </div>
            </div>
            <label>
              <span>个性签名</span>
              <input v-model="profileForm.bio" type="text" placeholder="留下一句话介绍自己" />
            </label>
            <label>
              <span>手机号</span>
              <input :value="userPhone" type="text" disabled />
            </label>
            <label>
              <span>账号状态</span>
              <input value="正常" type="text" disabled />
            </label>
          </div>

          <footer>
            <button class="account-primary" type="button" :disabled="saving" @click="saveProfile">
              {{ saving ? '保存中' : '保存资料' }}
            </button>
          </footer>
        </section>

        <section v-else-if="activeTab === 'quota'" class="account-section account-quota-section">
          <div class="account-plan-line quota-plan-line">
            <div>
              <b>{{ authStore.currentPlan.name }}（有效期至 {{ planExpiry() }}）</b>
            </div>
            <button class="quota-plan-action" type="button" @click="openPricingFromQuota">变更套餐 <RightOutlined /></button>
            <strong>{{ quotaPercent }}%</strong>
            <i><em :style="{ width: `${quotaPercent}%` }" /></i>
            <p>剩余额度 <b>{{ quotaRemaining(mainQuota) }} / {{ quotaTotal(mainQuota) }} {{ mainQuota.unit }}</b></p>
          </div>
          <div class="quota-usage-metrics" :class="{ loading: loadingQuotaStats && !quotaStats }">
            <article v-for="item in quotaUsageMetrics" :key="item.label">
              <i class="quota-metric-mark" />
              <span class="quota-metric-icon"><component :is="item.icon" /></span>
              <span>{{ item.label }}</span>
              <div v-if="'value' in item" class="quota-metric-value">
                <b>{{ item.value }}</b>
                <small>{{ item.unit }}</small>
              </div>
              <div v-else class="quota-metric-month">
                <small>图片 <b>{{ item.monthImages }}</b></small>
                <em />
                <small>视频 <b>{{ item.monthVideos }}</b></small>
              </div>
            </article>
          </div>
        </section>

        <section v-else-if="activeTab === 'settings'" class="account-section">
          <div class="settings-line-list settings-lite-list">
            <article v-for="row in settingsRows" :key="row.label">
              <span>{{ row.label }}</span>
              <strong>{{ row.value }}</strong>
              <button type="button" @click="settingAction(row.action)">{{ row.action }}</button>
            </article>
          </div>
        </section>

        <section v-else-if="activeTab === 'history'" class="account-section account-history-section">
          <div class="history-table">
            <header>
              <span>任务ID</span>
              <span>任务名称</span>
              <span>状态</span>
              <span>创建时间</span>
              <span>操作</span>
            </header>
            <article v-for="row in taskPageRows" :key="row.id">
              <small>{{ row.id }}</small>
              <b>{{ row.taskName }}</b>
              <em :class="row.status">{{ statusLabel(row.status) }}</em>
              <time>{{ formatDateTime(row.createdAt) }}</time>
              <button type="button" @click="viewTask(row)">查看</button>
            </article>
            <p v-if="!taskPageRows.length">{{ loadingTasks ? '任务加载中...' : '暂无任务历史' }}</p>
          </div>
          <div class="account-pagination">
            <span>共 {{ visibleTasks.length }} 条</span>
            <button type="button" :disabled="taskPage === 1" @click="changeTaskPage(taskPage - 1)"><LeftOutlined /></button>
            <button
              v-for="page in taskPageNumbers"
              :key="page"
              type="button"
              :class="{ active: taskPage === page }"
              @click="changeTaskPage(page)"
            >
              {{ page }}
            </button>
            <button type="button" :disabled="taskPage === taskTotalPages" @click="changeTaskPage(taskPage + 1)"><RightOutlined /></button>
            <select v-model.number="taskPageSize" @change="taskPageSizeChanged">
              <option :value="5">5条/页</option>
              <option :value="10">10条/页</option>
              <option :value="20">20条/页</option>
            </select>
          </div>
        </section>

        <section v-else-if="activeTab === 'messages'" class="account-section account-messages-section">
          <div class="message-toolbar">
            <div>
              <button type="button" :class="{ active: messageTab === 'unread' }" @click="messageTab = 'unread'"><span class="message-tab-label">未读</span><em v-if="unreadMessages.length" class="message-tab-count">{{ unreadMessages.length }}</em></button>
              <button type="button" :class="{ active: messageTab === 'read' }" @click="messageTab = 'read'"><span class="message-tab-label">已读</span></button>
              <button type="button" :class="{ active: messageTab === 'all' }" @click="messageTab = 'all'"><span class="message-tab-label">全部</span><em v-if="unreadMessages.length" class="message-tab-count">{{ unreadMessages.length }}</em></button>
            </div>
          </div>
          <div class="message-line-list">
            <header>
              <span>类型</span>
              <span>内容</span>
              <span>时间</span>
            </header>
            <article
              v-for="item in messagePageRows"
              :key="item.id"
              :class="{ unread: item.unread }"
              role="button"
              tabindex="0"
              @click="openMessage(item)"
              @keydown.enter.prevent="openMessage(item)"
            >
              <b class="message-type"><component :is="messageIcon(item)" /><span>{{ messageType(item) }}</span></b>
              <small>{{ item.body }}</small>
              <time>{{ formatShortTime(item.createdAt) }}</time>
            </article>
            <p v-if="!visibleMessages.length">暂无{{ messageTab === 'unread' ? '未读' : messageTab === 'read' ? '已读' : '' }}消息</p>
          </div>
          <div class="account-pagination message-pagination">
            <span>共 {{ visibleMessages.length }} 条</span>
            <button type="button" :disabled="messagePage === 1" @click="changeMessagePage(messagePage - 1)"><LeftOutlined /></button>
            <button
              v-for="page in messagePageNumbers"
              :key="page"
              type="button"
              :class="{ active: messagePage === page }"
              @click="changeMessagePage(page)"
            >
              {{ page }}
            </button>
            <button type="button" :disabled="messagePage === messageTotalPages" @click="changeMessagePage(messagePage + 1)"><RightOutlined /></button>
            <button v-if="messageTab !== 'all'" class="message-view-all" type="button" @click="viewAllMessages">查看全部消息 <RightOutlined /></button>
          </div>
        </section>

        <section v-else class="account-section">
          <div class="privacy-line-list">
            <div class="privacy-line-item">
              <span><b>个性化推荐</b><small>根据使用行为推荐相关功能与内容</small></span>
              <button class="account-switch" type="button" :class="{ checked: privacy.personalized }" :aria-pressed="privacy.personalized" @click="togglePrivacy('personalized')"><i /></button>
            </div>
            <div class="privacy-line-item">
              <span><b>数据统计</b><small>允许收集匿名使用数据以优化产品</small></span>
              <button class="account-switch" type="button" :class="{ checked: privacy.analytics }" :aria-pressed="privacy.analytics" @click="togglePrivacy('analytics')"><i /></button>
            </div>
            <div class="privacy-line-item">
              <span><b>任务内容保留</b><small>保留历史任务记录，便于再次使用</small></span>
              <button class="account-switch" type="button" :class="{ checked: privacy.historyRetention }" :aria-pressed="privacy.historyRetention" @click="togglePrivacy('historyRetention')"><i /></button>
            </div>
            <button type="button" @click="deleteAccount">
              <span><b>删除账户</b><small>永久删除账户及所有数据</small></span>
              <RightOutlined />
            </button>
          </div>
        </section>
      </main>
    </div>
  </a-modal>
</template>
