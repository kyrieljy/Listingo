<script setup lang="ts">
import { computed, onUnmounted, ref, watch } from 'vue'
import { CheckOutlined, ClockCircleOutlined, ExperimentOutlined, EyeOutlined, LoadingOutlined } from '@ant-design/icons-vue'
import { message } from 'ant-design-vue'
import {
  createBatchValidationFixtures,
  getBatchJob,
  listBatchJobs,
  userFacingApiErrorMessage,
  type BatchBusinessType,
  type BatchItem,
  type BatchJob,
} from '../../api/client'
import { batchItemResultJob, type BatchSelectionPayload, type BatchSelectionTask } from './batch-model'

const props = defineProps<{
  open: boolean
  businessType: BatchBusinessType
}>()

const emit = defineEmits<{
  'update:open': [boolean]
  selectTasks: [BatchSelectionPayload]
}>()

const jobs = ref<BatchJob[]>([])
const selected = ref<BatchJob | null>(null)
const checkedItemIds = ref<Set<string>>(new Set())
const loading = ref(false)
const fixtureLoading = ref(false)
let pollTimer: ReturnType<typeof window.setInterval> | null = null

const visibleJobs = computed(() => jobs.value.filter((job) => job.business_type === props.businessType))
const businessLabel = computed(() => props.businessType === 'aplus' ? 'A+详情' : '商品套图')
const selectedCount = computed(() => checkedItemIds.value.size)

watch(() => props.open, (open) => {
  if (open) {
    void refresh()
    startPolling()
  } else {
    stopPolling()
  }
}, { immediate: true })

watch(() => props.businessType, () => {
  selected.value = null
  checkedItemIds.value = new Set()
  if (props.open) void refresh()
})

onUnmounted(stopPolling)

function statusLabel(status: string): string {
  const labels: Record<string, string> = {
    queued: '排队中',
    running: '生成中',
    succeeded: '已完成',
    partial_failed: '部分失败',
    failed: '失败',
    cancelling: '取消中',
    cancelled: '已取消',
    partial_cancelled: '部分取消',
  }
  return labels[status] ?? status
}

function statusClass(status: string): string {
  if (status === 'succeeded') return 'succeeded'
  if (status === 'partial_failed' || status === 'partial_cancelled') return 'warning'
  if (status === 'failed' || status === 'cancelled') return 'failed'
  return 'running'
}

function startPolling() {
  stopPolling()
  pollTimer = window.setInterval(() => { void refresh(false) }, 1600)
}

function stopPolling() {
  if (pollTimer) window.clearInterval(pollTimer)
  pollTimer = null
}

async function refresh(showLoading = true) {
  if (showLoading) loading.value = true
  try {
    jobs.value = await listBatchJobs()
    const current = selected.value
    const visible = visibleJobs.value
    if (current && visible.some((job) => job.id === current.id)) {
      selected.value = await getBatchJob(current.id)
    } else if (visible.length) {
      selected.value = await getBatchJob(visible[0].id)
    } else {
      selected.value = null
    }
  } catch {
    if (showLoading) message.error('批量记录加载失败')
  } finally {
    loading.value = false
  }
}

async function openDetail(id: string) {
  selected.value = await getBatchJob(id)
}

function taskSelectable(item: BatchItem): boolean {
  if (props.businessType === 'suite') return Boolean(item.generation_job_id)
  return Boolean(item.aplus_generation_job_id)
}

function taskChecked(itemId: string): boolean {
  return checkedItemIds.value.has(itemId)
}

function setTaskChecked(itemId: string, checked: boolean) {
  const next = new Set(checkedItemIds.value)
  if (checked) next.add(itemId)
  else next.delete(itemId)
  checkedItemIds.value = next
}

function toggleTask(item: BatchItem) {
  if (!taskSelectable(item)) return
  setTaskChecked(item.id, !taskChecked(item.id))
}

function selectableItems(job: BatchJob): BatchItem[] {
  return job.items.filter(taskSelectable)
}

function batchChecked(job: BatchJob): boolean {
  const items = selectableItems(job)
  return items.length > 0 && items.every((item) => checkedItemIds.value.has(item.id))
}

function toggleBatch(job: BatchJob) {
  const next = new Set(checkedItemIds.value)
  const items = selectableItems(job)
  const checked = items.length > 0 && items.every((item) => next.has(item.id))
  for (const item of items) {
    if (checked) next.delete(item.id)
    else next.add(item.id)
  }
  checkedItemIds.value = next
}

function taskPayload(batch: BatchJob, item: BatchItem): BatchSelectionTask {
  return {
    batchId: batch.id,
    batchCreatedAt: batch.created_at,
    batchStatus: batch.status,
    batchProgress: batch.progress,
    item,
  }
}

async function resolveCheckedTasks(): Promise<BatchSelectionTask[]> {
  const ids = checkedItemIds.value
  const batches = await Promise.all(
    visibleJobs.value
      .filter((job) => job.items.some((item) => ids.has(item.id)))
      .map((job) => getBatchJob(job.id)),
  )
  return batches.flatMap((batch) => batch.items.filter((item) => ids.has(item.id)).map((item) => taskPayload(batch, item)))
}

function resultReady(task: BatchSelectionTask): boolean {
  return Boolean(batchItemResultJob(task.item, props.businessType))
}

function emitTasks(tasks: BatchSelectionTask[]) {
  const readyTasks = tasks.filter(resultReady)
  if (!readyTasks.length) {
    message.warning('请选择已经生成出结果的商品任务')
    return
  }
  emit('selectTasks', { businessType: props.businessType, tasks: readyTasks })
  emit('update:open', false)
}

async function openTask(item: BatchItem) {
  if (selectedCount.value > 0) {
    toggleTask(item)
    return
  }
  if (!selected.value) return
  const latest = await getBatchJob(selected.value.id)
  selected.value = latest
  const latestItem = latest.items.find((entry) => entry.id === item.id)
  if (!latestItem) return
  emitTasks([taskPayload(latest, latestItem)])
}

async function viewChecked() {
  emitTasks(await resolveCheckedTasks())
}

async function createFixtures() {
  fixtureLoading.value = true
  try {
    const created = await createBatchValidationFixtures(props.businessType)
    await refresh(false)
    if (created[0]) selected.value = await getBatchJob(created[0].id)
    message.success('已生成 Dryrun 验证批次')
  } catch (error: any) {
    message.error(userFacingApiErrorMessage(error) || '验证批次创建失败')
  } finally {
    fixtureLoading.value = false
  }
}

function thumbFor(item: BatchItem): string {
  if (item.thumbnail_url) return item.thumbnail_url
  return props.businessType === 'aplus' ? '/demo/aplus-outdoor-source.png' : '/demo/tumbler-source.png'
}
</script>

<template>
  <a-drawer :open="open" width="600" class="batch-history-drawer" @update:open="emit('update:open', $event)">
    <template #title>
      <span class="batch-history-title"><ClockCircleOutlined />批量托管记录 · {{ businessLabel }}</span>
    </template>

    <div class="batch-history-actions">
      <button type="button" class="ghost-action" :disabled="fixtureLoading" @click="createFixtures">
        <LoadingOutlined v-if="fixtureLoading" spin />
        <ExperimentOutlined v-else />
        生成验证用例
      </button>
      <button type="button" class="primary-action" :disabled="selectedCount === 0" @click="viewChecked">
        <EyeOutlined />查看选中 {{ selectedCount ? `(${selectedCount})` : '' }}
      </button>
    </div>

    <div class="batch-history-layout">
      <aside class="batch-history-list">
        <article
          v-for="job in visibleJobs"
          :key="job.id"
          class="batch-history-batch"
          :class="{ active: selected?.id === job.id }"
        >
          <button type="button" class="batch-list-check" :class="{ checked: batchChecked(job) }" @click.stop="toggleBatch(job)">
            <CheckOutlined v-if="batchChecked(job)" />
          </button>
          <button type="button" class="batch-history-batch-main" @click="openDetail(job.id)">
            <b>{{ businessLabel }}批次</b>
            <small>{{ new Date(job.created_at).toLocaleString() }}</small>
            <span class="batch-history-batch-status"><em :class="statusClass(job.status)">{{ statusLabel(job.status) }}</em><i>{{ job.progress }}%</i></span>
          </button>
        </article>
        <p v-if="!visibleJobs.length && !loading">暂无批次记录</p>
      </aside>

      <main class="batch-history-detail" v-if="selected">
        <header>
          <div>
            <b>{{ businessLabel }}批次</b>
            <span>{{ new Date(selected.created_at).toLocaleString() }} · {{ statusLabel(selected.status) }} · {{ selected.completed_count }}/{{ selected.total_count }} 完成 · {{ selected.failed_count }} 失败</span>
          </div>
          <button type="button" class="ghost-action" @click="toggleBatch(selected)">
            <CheckOutlined v-if="batchChecked(selected)" />{{ batchChecked(selected) ? '清空整批' : '勾选整批' }}
          </button>
        </header>
        <section class="batch-history-items">
          <article
            v-for="item in selected.items"
            :key="item.id"
            :class="{ selected: taskChecked(item.id), disabled: !taskSelectable(item) }"
            @click="openTask(item)"
          >
            <button type="button" class="batch-task-check" :class="{ checked: taskChecked(item.id) }" :disabled="!taskSelectable(item)" @click.stop="toggleTask(item)">
              <CheckOutlined v-if="taskChecked(item.id)" />
            </button>
            <img :src="thumbFor(item)" :alt="item.name || `商品任务${item.index}`" />
            <div>
              <b>商品任务{{ item.index }} · {{ item.name || '未命名商品' }}</b>
              <span :class="statusClass(item.status)">{{ statusLabel(item.status) }}</span>
              <small>{{ item.completed_image_count }}/{{ item.total_image_count }} 图完成 · {{ item.failed_image_count }} 图失败</small>
              <small v-if="item.error" class="batch-task-error-text">{{ item.error }}</small>
            </div>
          </article>
        </section>
      </main>

      <main class="batch-history-empty" v-else>
        <ClockCircleOutlined />
        <span>选择左侧批次查看商品任务</span>
      </main>
    </div>
  </a-drawer>
</template>
