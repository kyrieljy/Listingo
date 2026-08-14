<script setup lang="ts">
import { computed, ref, watch } from 'vue'
import { SearchOutlined } from '@ant-design/icons-vue'
import { adminGetBusinessUserMetricsApi, userFacingApiErrorMessage } from '../../api/client'
import ComparisonMatrix from './ComparisonMatrix.vue'
import MetricKpiStrip from './MetricKpiStrip.vue'
import MonitoringPager from './MonitoringPager.vue'
import { businessUserPrototypeData, type MetricDefinition, type MetricRow, type MonitoringPayload, type MonitoringQueryState } from './monitoring-data'

const props = defineProps<{
  users: MetricRow[]
  filters: MonitoringQueryState
  definitions: Record<string, MetricDefinition>
  prototypeMode: boolean
}>()

const search = ref('')
const selectedUserId = ref('')
const detail = ref<MonitoringPayload>(businessUserPrototypeData)
const detailError = ref('')
const loading = ref(false)
const userPage = ref(1)
const timelinePage = ref(1)
const userPageSize = 8
const timelinePageSize = 8
const emptyUserDetail: MonitoringPayload = {
  metric_definitions: businessUserPrototypeData.metric_definitions,
  summary_cards: [],
  feature_rows: [],
  platform_rows: [],
  ratio_rows: [],
  module_rows: [],
  video_type_rows: [],
  trend_rows: [],
  timeline_rows: [],
  subscription_rows: [],
}

const sourceUsers = computed(() => {
  if (props.users.length) return props.users
  return props.prototypeMode ? (businessUserPrototypeData.user_rows || []) : []
})
const filteredUsers = computed(() => {
  const keyword = search.value.trim().toLowerCase()
  const rows = sourceUsers.value
  if (!keyword) return rows
  return rows.filter((row) => JSON.stringify(row).toLowerCase().includes(keyword))
})

const activeUser = computed(() => filteredUsers.value.find((row) => String(row.user_id) === selectedUserId.value) || filteredUsers.value[0] || null)
const summaryCards = computed(() => detail.value.summary_cards || [])
const timelineRows = computed(() => Array.isArray(detail.value.timeline_rows) ? detail.value.timeline_rows as MetricRow[] : [])
const detailFeatureRows = computed(() => detail.value.feature_rows || [])
const pagedUsers = computed(() => slicePage(filteredUsers.value, userPage.value, userPageSize))
const pagedTimelineRows = computed(() => slicePage(timelineRows.value, timelinePage.value, timelinePageSize))

function slicePage<T>(items: T[], page: number, pageSize: number): T[] {
  const start = (Math.max(1, page) - 1) * pageSize
  return items.slice(start, start + pageSize)
}

watch(filteredUsers, () => {
  userPage.value = 1
  if (!activeUser.value) {
    selectedUserId.value = ''
    return
  }
  if (!selectedUserId.value || !filteredUsers.value.some((row) => String(row.user_id) === selectedUserId.value)) {
    selectedUserId.value = String(activeUser.value.user_id || '')
  }
}, { immediate: true })

watch([pagedUsers, userPage], () => {
  const firstVisible = pagedUsers.value[0]
  if (!firstVisible) return
  if (!pagedUsers.value.some((row) => String(row.user_id) === selectedUserId.value)) {
    selectedUserId.value = String(firstVisible.user_id || '')
  }
}, { immediate: true })

watch(timelineRows, () => {
  timelinePage.value = 1
})

watch([selectedUserId, () => props.filters.start_at, () => props.filters.end_at, () => props.filters.granularity, () => props.prototypeMode], async () => {
  if (!selectedUserId.value) {
    detail.value = props.prototypeMode ? businessUserPrototypeData : emptyUserDetail
    detailError.value = ''
    return
  }
  if (props.prototypeMode) {
    detail.value = { ...businessUserPrototypeData, user: activeUser.value || businessUserPrototypeData.user }
    detailError.value = ''
    return
  }
  loading.value = true
  try {
    detail.value = await adminGetBusinessUserMetricsApi(selectedUserId.value, {
      start_at: new Date(props.filters.start_at).toISOString(),
      end_at: new Date(props.filters.end_at).toISOString(),
      granularity: props.filters.granularity,
    }) as MonitoringPayload
    detailError.value = ''
  } catch (error: unknown) {
    detail.value = emptyUserDetail
    detailError.value = userFacingApiErrorMessage(error)
  } finally {
    loading.value = false
  }
}, { immediate: true })
</script>

<template>
  <section class="monitoring-panel wide user-drilldown-panel">
    <header>
      <div>
        <span>单用户画像</span>
        <b>选择用户查看偏好、行为、上传商品和套餐行为</b>
      </div>
      <div class="user-search">
        <SearchOutlined />
        <input v-model="search" placeholder="搜索用户ID / 手机 / 偏好" />
      </div>
    </header>

    <div class="user-drilldown-layout">
      <aside class="user-list">
        <button
          v-for="user in pagedUsers"
          :key="String(user.user_id)"
          type="button"
          :class="{ active: String(user.user_id) === selectedUserId }"
          @click="selectedUserId = String(user.user_id)"
        >
          <b>{{ user.display_name || user.uid || user.user_id }}</b>
          <span>{{ user.plan || 'free' }} · {{ user.top_feature || '未标注' }}</span>
          <small>{{ user.top_platform || '未知平台' }} / {{ user.top_feature || '未标注功能' }}</small>
        </button>
        <MonitoringPager v-model="userPage" :total="filteredUsers.length" :page-size="userPageSize" />
      </aside>

      <main class="user-detail">
        <div class="user-detail-head">
          <div>
            <b>{{ activeUser?.display_name || activeUser?.uid || '未选择用户' }}</b>
            <span>{{ activeUser?.uid || activeUser?.phone_masked || '' }}</span>
          </div>
          <em v-if="loading">加载中...</em>
          <em v-else>{{ activeUser?.plan || 'free' }}</em>
        </div>

        <MetricKpiStrip :cards="summaryCards" :definitions="definitions" />
        <p v-if="detailError" class="monitoring-inline-error">用户详情暂不可用：{{ detailError }}</p>

        <div class="user-detail-grid">
          <ComparisonMatrix
            :rows="detailFeatureRows"
            :definitions="definitions"
            compact
            :page-size="6"
            :columns="[
              { key: 'clicks', label: '点击' },
              { key: 'submits', label: '提交', definitionKey: 'submit_rate' },
              { key: 'success_rate', label: '成功率', kind: 'percent' },
              { key: 'downloads', label: '下载', definitionKey: 'download_rate' },
            ]"
          />
          <ComparisonMatrix
            :rows="detail.platform_rows || []"
            :definitions="definitions"
            compact
            :page-size="6"
            :columns="[
              { key: 'clicks', label: '点击' },
              { key: 'submits', label: '提交' },
              { key: 'downloads', label: '下载' },
            ]"
          />
        </div>

        <section class="timeline-list">
          <header><span>行为时间线</span><b>{{ timelineRows.length }} 条</b></header>
          <div v-for="row in pagedTimelineRows" :key="String(row.id)" class="timeline-row">
            <i />
            <div>
              <b>{{ row.title }}</b>
              <small>{{ row.detail }} · {{ row.status }}</small>
            </div>
            <time>{{ new Date(String(row.created_at)).toLocaleString() }}</time>
          </div>
          <p v-if="!timelineRows.length" class="monitoring-empty">暂无该用户行为</p>
          <MonitoringPager v-model="timelinePage" :total="timelineRows.length" :page-size="timelinePageSize" />
        </section>
      </main>
    </div>
  </section>
</template>
