<script setup lang="ts">
import { computed, onErrorCaptured, onMounted, ref, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { message } from 'ant-design-vue'
import { ReloadOutlined } from '@ant-design/icons-vue'
import {
  adminGetBusinessMetricsApi,
  adminGetOpsMonitoringApi,
  userFacingApiErrorMessage,
  type MonitoringQuery,
} from '../../api/client'
import ChartTableToggle from './ChartTableToggle.vue'
import ComparisonMatrix from './ComparisonMatrix.vue'
import MetricHelpPopover from './MetricHelpPopover.vue'
import MetricKpiStrip from './MetricKpiStrip.vue'
import MonitoringLineChart from './MonitoringLineChart.vue'
import MonitoringPager from './MonitoringPager.vue'
import SharePieChart from './SharePieChart.vue'
import UserDrilldownPanel from './UserDrilldownPanel.vue'
import {
  businessPrototypeData,
  defaultMonitoringFilters,
  opsPrototypeData,
  prototypeDefinitions,
  type MetricDefinition,
  type MetricRow,
  type MonitoringPayload,
} from './monitoring-data'
import './monitoring.css'

const props = defineProps<{
  kind: 'ops' | 'business'
}>()

const route = useRoute()
const router = useRouter()
const filters = ref(defaultMonitoringFilters())
const data = ref<MonitoringPayload>(props.kind === 'ops' ? opsPrototypeData : businessPrototypeData)
const loading = ref(false)
const loadError = ref('')
const renderError = ref('')
const providerMode = ref<'chart' | 'table'>('chart')
const businessChainMode = ref<'chart' | 'table'>('chart')
const platformMode = ref<'pie' | 'table'>('table')
const queuePage = ref(1)
const incidentPage = ref(1)
const queuePageSize = 4
const incidentPageSize = 6

const prototypeMode = computed(() => route.query.mode === 'prototype')
const safeData = computed<MonitoringPayload>(() => data.value && typeof data.value === 'object'
  ? data.value
  : props.kind === 'ops' ? opsPrototypeData : businessPrototypeData)
const monitoringError = computed(() => renderError.value || loadError.value)
const definitions = computed<Record<string, MetricDefinition>>(() => ({
  ...prototypeDefinitions,
  ...(safeData.value.metric_definitions || {}),
}))
const cards = computed(() => safeData.value.summary_cards || [])
const title = computed(() => props.kind === 'ops' ? '运维监控中心' : '运营指标监控中心')
const subtitle = computed(() => props.kind === 'ops'
  ? '按中转站、节点、业务链路和队列状态监控成功率、失败率与耗时'
  : '按事件链路、偏好维度、用户画像和套餐行为分析运营表现')
const primaryTrendRows = computed(() => rows(props.kind === 'ops' ? 'timeseries' : 'trend_rows'))
const providerRows = computed(() => rows('provider_rows').map((row) => ({
  ...row,
  label: String(row.provider_group_label || row.provider_label || row.label || row.key || '中转站'),
})))
const nodeRows = computed(() => rows('node_rows'))
const businessRows = computed(() => rows('business_rows'))
const queueRows = computed(() => rows('queue_rows'))
const incidentRows = computed(() => rows('incident_rows'))
const featureRows = computed(() => rows('feature_rows'))
const platformRows = computed(() => rows('platform_rows'))
const ratioRows = computed(() => rows('ratio_rows'))
const moduleRows = computed(() => rows('module_rows'))
const videoTypeRows = computed(() => rows('video_type_rows'))
const eventRelationRows = computed(() => rows('event_relation_rows'))
const subscriptionRows = computed(() => rows('subscription_rows'))
const userRows = computed(() => rows('user_rows'))
const pagedQueueRows = computed(() => slicePage(queueRows.value, queuePage.value, queuePageSize))
const pagedIncidentRows = computed(() => slicePage(incidentRows.value, incidentPage.value, incidentPageSize))

onErrorCaptured((error) => {
  renderError.value = error instanceof Error ? error.message : String(error)
  message.error('监控模块渲染异常，已停止本次渲染')
  return false
})

onMounted(load)
watch(() => props.kind, load)
watch(prototypeMode, load)
watch([queueRows, incidentRows], () => {
  queuePage.value = 1
  incidentPage.value = 1
})

function slicePage<T>(items: T[], page: number, pageSize: number): T[] {
  const start = (Math.max(1, page) - 1) * pageSize
  return items.slice(start, start + pageSize)
}

function rows(key: string): MetricRow[] {
  const value = safeData.value[key]
  return Array.isArray(value) ? value as MetricRow[] : []
}

function profileRows(key: string): MetricRow[] {
  const value = safeData.value.profile_rows?.[key]
  return Array.isArray(value) ? value : []
}

function profileGroupLabel(key: string): string {
  const labels: Record<string, string> = { plans: '套餐', roles: '角色', statuses: '状态', genders: '性别', activity_levels: '活跃层级' }
  return labels[key] || key
}

function apiParams(): MonitoringQuery {
  const params: MonitoringQuery = { granularity: filters.value.granularity }
  const start = new Date(filters.value.start_at)
  const end = new Date(filters.value.end_at)
  if (!Number.isNaN(start.getTime())) params.start_at = start.toISOString()
  if (!Number.isNaN(end.getTime())) params.end_at = end.toISOString()
  return params
}

async function load(): Promise<void> {
  loadError.value = ''
  renderError.value = ''
  if (prototypeMode.value) {
    data.value = props.kind === 'ops' ? opsPrototypeData : businessPrototypeData
    return
  }
  loading.value = true
  try {
    data.value = props.kind === 'ops'
      ? await adminGetOpsMonitoringApi(apiParams()) as MonitoringPayload
      : await adminGetBusinessMetricsApi(apiParams()) as MonitoringPayload
  } catch (error: unknown) {
    loadError.value = requestDetail(error) || '监控数据加载失败'
    message.error(loadError.value)
  } finally {
    loading.value = false
  }
}

async function refresh(): Promise<void> {
  await load()
  if (!prototypeMode.value && !monitoringError.value) message.success('监控数据已刷新')
}

function requestDetail(error: unknown): string {
  return userFacingApiErrorMessage(error)
}

function go(kind: 'ops' | 'business'): void {
  const section = kind === 'ops' ? 'ops-monitoring' : 'business-metrics'
  router.push({ path: `/admin/${section}`, query: prototypeMode.value ? { mode: 'prototype' } : {} })
}

function durationText(value: unknown): string {
  const ms = finiteNumber(value)
  if (ms <= 0) return '0ms'
  if (ms >= 1000) return `${(ms / 1000).toFixed(1)}s`
  return `${Math.round(ms)}ms`
}

function percentText(value: unknown): string {
  return `${finiteNumber(value).toFixed(1)}%`
}

function countText(value: unknown): string {
  return Intl.NumberFormat('zh-CN').format(finiteNumber(value))
}

function waitText(value: unknown): string {
  const seconds = finiteNumber(value)
  if (seconds >= 3600) return `${(seconds / 3600).toFixed(1)}h`
  if (seconds >= 60) return `${Math.round(seconds / 60)}m`
  return `${Math.round(seconds)}s`
}

function finiteNumber(value: unknown): number {
  const numeric = Number(value)
  return Number.isFinite(numeric) ? numeric : 0
}

function boundedPercent(value: unknown): string {
  return `${Math.max(4, Math.min(100, finiteNumber(value)))}%`
}

function timeText(value: unknown): string {
  if (!value) return '-'
  const date = new Date(String(value))
  if (Number.isNaN(date.getTime())) return String(value)
  return date.toLocaleString('zh-CN', { month: '2-digit', day: '2-digit', hour: '2-digit', minute: '2-digit', hour12: false })
}
</script>

<template>
  <section class="admin-module-shell monitoring-dashboard-v2">
    <div class="monitoring-tabs">
      <button type="button" :class="{ active: kind === 'ops' }" @click="go('ops')">运维监控</button>
      <button type="button" :class="{ active: kind === 'business' }" @click="go('business')">运营指标监控</button>
      <span v-if="prototypeMode">可点原型</span>
    </div>

    <header class="monitoring-header">
      <div>
        <h2>{{ title }}</h2>
        <p>{{ subtitle }}</p>
      </div>
      <div class="monitoring-filterbar">
        <label>开始<input v-model="filters.start_at" type="datetime-local" /></label>
        <label>结束<input v-model="filters.end_at" type="datetime-local" /></label>
        <label>粒度<select v-model="filters.granularity"><option value="hour">小时</option><option value="day">天</option><option value="week">周</option></select></label>
        <button type="button" :disabled="loading" @click="refresh"><ReloadOutlined />{{ loading ? '刷新中' : '刷新' }}</button>
      </div>
    </header>

    <div v-if="monitoringError" class="monitoring-error-state" role="alert">
      <b>监控模块暂不可用</b>
      <span>{{ monitoringError }}</span>
      <button type="button" :disabled="loading" @click="refresh"><ReloadOutlined />重试</button>
    </div>

    <MetricKpiStrip v-if="!monitoringError" :cards="cards" :definitions="definitions" />

    <template v-if="!monitoringError && kind === 'ops'">
      <div class="monitoring-layout">
        <MonitoringLineChart
          class="wide"
          title="链路趋势"
          subtitle="成功率、失败率、超时率与 P95 耗时"
          :rows="primaryTrendRows"
          :definitions="definitions"
          definition-key="success_rate"
          :metrics="[
            { key: 'success_rate', label: '成功率', unit: '%', color: '#16a34a' },
            { key: 'failure_rate', label: '失败率', unit: '%', color: '#dc2626' },
            { key: 'timeout_rate', label: '超时率', unit: '%', color: '#d97706' },
            { key: 'p95_duration_ms', label: 'P95耗时', unit: 'ms', color: '#2563eb', yAxisIndex: 1 },
          ]"
        />

        <section class="monitoring-panel wide">
          <header>
            <div><span>中转站健康</span><b>模型、能力、成功率、耗时和超时对比</b></div>
            <ChartTableToggle v-model="providerMode" />
          </header>
          <MonitoringLineChart
            v-if="providerMode === 'chart'"
            embedded
            title="中转站模型情况"
            subtitle="调用量、成功率与 P95"
            :rows="providerRows"
            x-key="label"
            :definitions="definitions"
            definition-key="provider_health"
            :metrics="[
              { key: 'total', label: '调用量', type: 'bar', color: '#9db7f5' },
              { key: 'success_rate', label: '成功率', unit: '%', color: '#16a34a' },
              { key: 'p95_duration_ms', label: 'P95耗时', unit: 'ms', color: '#2563eb', yAxisIndex: 1 },
            ]"
          />
          <ComparisonMatrix
            v-else
            :rows="providerRows"
            :definitions="definitions"
            :page-size="12"
            :columns="[
              { key: 'total', label: '调用' },
              { key: 'success_rate', label: '成功率', kind: 'percent', definitionKey: 'success_rate' },
              { key: 'failure_rate', label: '失败率', kind: 'percent', definitionKey: 'failure_rate' },
              { key: 'timeout_rate', label: '超时率', kind: 'percent', definitionKey: 'timeout_rate' },
              { key: 'p95_duration_ms', label: 'P95', kind: 'duration', definitionKey: 'p95_latency' },
            ]"
          />
        </section>

        <section class="monitoring-panel span-6">
          <header>
            <div><span>业务链路</span><b>任务成功率、耗时和产出</b></div>
            <ChartTableToggle v-model="businessChainMode" />
          </header>
          <MonitoringLineChart
            v-if="businessChainMode === 'chart'"
            embedded
            title="业务链路对比"
            subtitle="任务量、成功率与端到端 P95"
            :rows="businessRows"
            x-key="label"
            :definitions="definitions"
            definition-key="success_rate"
            :metrics="[
              { key: 'total', label: '任务数', type: 'bar', color: '#9db7f5' },
              { key: 'success_rate', label: '成功率', unit: '%', color: '#16a34a' },
              { key: 'p95_duration_ms', label: 'P95耗时', unit: 'ms', color: '#2563eb', yAxisIndex: 1 },
            ]"
          />
          <ComparisonMatrix
            v-else
            :rows="businessRows"
            :definitions="definitions"
            :page-size="8"
            :columns="[
              { key: 'total', label: '任务' },
              { key: 'success_rate', label: '成功率', kind: 'percent', definitionKey: 'success_rate' },
              { key: 'failure_rate', label: '失败率', kind: 'percent', definitionKey: 'failure_rate' },
              { key: 'p95_duration_ms', label: 'P95', kind: 'duration', definitionKey: 'p95_latency' },
              { key: 'output_count', label: '产出' },
            ]"
          />
        </section>

        <section class="monitoring-panel span-6">
          <header><div><span>队列状态</span><b>积压、运行中和等待时间</b></div><MetricHelpPopover :definition="definitions.queue" label="队列状态" /></header>
          <div class="queue-grid">
            <article v-for="row in pagedQueueRows" :key="String(row.key)">
              <b>{{ row.label }}</b>
              <strong>{{ countText(row.count) }}</strong>
              <span>queued {{ row.queued }} / running {{ row.running }}</span>
              <small>最久等待 {{ waitText(row.oldest_wait_seconds) }}</small>
            </article>
          </div>
          <MonitoringPager v-model="queuePage" :total="queueRows.length" :page-size="queuePageSize" />
        </section>

        <section class="monitoring-panel span-6">
          <header><div><span>节点监控</span><b>中文节点解释与耗时</b></div><MetricHelpPopover :definition="definitions.p95_latency" label="节点监控" /></header>
          <ComparisonMatrix
            :rows="nodeRows"
            :definitions="definitions"
            :page-size="8"
            :columns="[
              { key: 'total', label: '调用' },
              { key: 'success_rate', label: '成功率', kind: 'percent', definitionKey: 'success_rate' },
              { key: 'failure_rate', label: '失败率', kind: 'percent', definitionKey: 'failure_rate' },
              { key: 'p95_duration_ms', label: 'P95', kind: 'duration', definitionKey: 'p95_latency' },
            ]"
          />
        </section>

        <section class="monitoring-panel span-6">
          <header><div><span>事故明细</span><b>最近失败与错误分类</b></div><MetricHelpPopover :definition="definitions.failure_rate" label="事故明细" /></header>
          <div class="incident-list-v2">
            <article v-for="row in pagedIncidentRows" :key="String(row.id)">
              <span>{{ row.error_category || '其他' }}</span>
              <div>
                <b>{{ row.node_label || row.node || row.provider_label || 'unknown' }}</b>
                <p>{{ row.error || row.status }}</p>
              </div>
              <small><em>{{ durationText(row.duration_ms) }}</em><time>{{ timeText(row.created_at) }}</time></small>
            </article>
            <p v-if="!incidentRows.length" class="monitoring-empty">暂无失败记录</p>
          </div>
          <MonitoringPager v-model="incidentPage" :total="incidentRows.length" :page-size="incidentPageSize" />
        </section>
      </div>
    </template>

    <template v-else-if="!monitoringError">
      <div class="monitoring-layout">
        <MonitoringLineChart
          class="span-8"
          title="运营趋势"
          subtitle="曝光、点击、提交、成功、下载和活跃用户"
          :rows="primaryTrendRows"
          :definitions="definitions"
          definition-key="feature_ctr"
          :metrics="[
            { key: 'views', label: '曝光', type: 'bar', color: '#b7c8f8' },
            { key: 'clicks', label: '点击', color: '#2563eb' },
            { key: 'submits', label: '提交', color: '#7c3aed' },
            { key: 'successes', label: '成功', color: '#16a34a' },
            { key: 'downloads', label: '下载', color: '#d97706' },
          ]"
        />

        <section class="monitoring-panel wide">
          <header><div><span>功能漏斗</span><b>每个核心功能的曝光、点击、提交、成功和下载</b></div><MetricHelpPopover :definition="definitions.feature_ctr" label="功能漏斗" /></header>
          <ComparisonMatrix
            :rows="featureRows"
            :definitions="definitions"
            :page-size="10"
            :columns="[
              { key: 'views', label: '曝光' },
              { key: 'clicks', label: '点击' },
              { key: 'ctr', label: '点击率', kind: 'percent', definitionKey: 'feature_ctr' },
              { key: 'submits', label: '提交' },
              { key: 'submit_rate', label: '提交率', kind: 'percent', definitionKey: 'submit_rate' },
              { key: 'success_rate', label: '成功率', kind: 'percent' },
              { key: 'download_rate', label: '下载率', kind: 'percent', definitionKey: 'download_rate' },
            ]"
          />
        </section>

        <section class="monitoring-panel span-4">
          <header><div><span>事件关系</span><b>view 到 download 的转化路径</b></div><MetricHelpPopover :definition="definitions.submit_rate" label="事件关系" /></header>
          <div class="event-flow">
            <article v-for="row in eventRelationRows" :key="String(row.key)">
              <b>{{ row.label }}</b>
              <strong>{{ countText(row.count) }}</strong>
              <i><em :style="{ width: boundedPercent(row.conversion_rate) }" /></i>
              <small>转化 {{ percentText(row.conversion_rate) }} / 流失 {{ countText(row.dropoff) }}</small>
            </article>
          </div>
        </section>

        <section class="monitoring-panel span-6">
          <header>
            <div><span>平台偏好</span><b>多指标对比</b></div>
            <ChartTableToggle v-model="platformMode" hide-chart pie-label="占比" table-label="表格" />
          </header>
          <ComparisonMatrix v-if="platformMode === 'table'" :rows="platformRows" :definitions="definitions" compact :page-size="8" :columns="[
            { key: 'views', label: '曝光' },
            { key: 'clicks', label: '点击' },
            { key: 'submits', label: '提交' },
            { key: 'success_rate', label: '成功率', kind: 'percent' },
            { key: 'downloads', label: '下载' },
          ]" />
          <SharePieChart v-else :rows="platformRows" />
        </section>

        <section class="monitoring-panel span-6">
          <header><div><span>用户总体画像</span><b>套餐、身份、状态和活跃层级</b></div><MetricHelpPopover :definition="definitions.active_users" label="用户总体画像" /></header>
          <div class="profile-grid-v2">
            <section v-for="group in ['plans','roles','statuses','genders','activity_levels']" :key="group">
              <b>{{ profileGroupLabel(group) }}</b>
              <span v-for="row in profileRows(group)" :key="String(row.key)">
                <em>{{ row.label }}</em><strong>{{ percentText(row.share) }}</strong>
              </span>
            </section>
          </div>
        </section>

        <section class="monitoring-panel wide">
          <header><div><span>偏好维度</span><b>尺寸、A+ 模块和视频类型</b></div><MetricHelpPopover :definition="definitions.submit_rate" label="偏好维度" /></header>
          <div class="preference-stack">
            <ComparisonMatrix :rows="ratioRows" :definitions="definitions" compact :page-size="6" :columns="[{ key: 'submits', label: '提交' }, { key: 'success_rate', label: '成功率', kind: 'percent' }, { key: 'share', label: '占比', kind: 'percent' }]" />
            <ComparisonMatrix :rows="moduleRows" :definitions="definitions" compact :page-size="6" :columns="[{ key: 'clicks', label: '点击' }, { key: 'submits', label: '提交' }, { key: 'downloads', label: '下载' }]" />
            <ComparisonMatrix :rows="videoTypeRows" :definitions="definitions" compact :page-size="6" :columns="[{ key: 'clicks', label: '点击' }, { key: 'submits', label: '提交' }, { key: 'success_rate', label: '成功率', kind: 'percent' }]" />
          </div>
        </section>

        <section class="monitoring-panel wide">
          <header><div><span>套餐行为</span><b>分布、支付转化和额度消耗</b></div><MetricHelpPopover :definition="definitions.paid_conversion_rate" label="套餐行为" /></header>
          <ComparisonMatrix
            :rows="subscriptionRows"
            :definitions="definitions"
            :page-size="8"
            :columns="[
              { key: 'users', label: '用户' },
              { key: 'share', label: '占比', kind: 'percent' },
              { key: 'orders', label: '订单' },
              { key: 'paid_conversion_rate', label: '支付转化', kind: 'percent', definitionKey: 'paid_conversion_rate' },
              { key: 'quota_used', label: '额度消耗', definitionKey: 'quota_usage_rate' },
            ]"
          />
        </section>

        <UserDrilldownPanel
          :users="userRows"
          :filters="filters"
          :definitions="definitions"
          :prototype-mode="prototypeMode"
        />
      </div>
    </template>
  </section>
</template>
