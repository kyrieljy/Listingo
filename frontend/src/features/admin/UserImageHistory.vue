<script setup lang="ts">
import { ref, watch } from 'vue'
import { api } from '../../api/client'

type Kind = 'suite' | 'aplus' | 'batch'
type Entry = { id: string; kind: Kind; status: string; count: number; created_at: string }
type Version = { id: string; version_no: number; instruction: string; url: string | null }
type Item = { id: string; label: string; status: string; error: string | null; planned_prompt: string | null; versions: Version[] }
type Step = { node: string; status: string; error: string | null; prompt: string | null; instruction: string | null; item_id: string | null }
type Child = { id: string; name: string; status: string; error: string | null; job_kind: Kind | null; job_id: string | null }
type Detail = {
  id: string; status: string; error: string | null; input?: string; submitted_input?: string
  dry_run?: boolean; rewrite?: string; rewrite_recorded?: boolean; source_plan_id?: string
  steps?: Step[]; items?: Item[]; children?: Child[]
}

const props = defineProps<{ user: { id: string; display_name: string } }>()
const emit = defineEmits<{ close: [] }>()
const labels = { suite: '普通生图', aplus: 'A+ 生图', batch: '批量生图' }
const statuses: Record<string, string> = {
  queued: '排队中', running: '生成中', succeeded: '已完成', failed: '失败',
  cancelled: '已取消', partial_failed: '部分失败', prepared: '已准备',
}
const pageSize = 20
const entries = ref<Entry[]>([])
const page = ref(0)
const hasMore = ref(false)
const loading = ref(false)
const listError = ref(false)
const selected = ref<Entry | null>(null)
const detail = ref<Detail | null>(null)
const childDetail = ref<Detail | null>(null)
const child = ref<Child | null>(null)
const detailLoading = ref(false)
const detailError = ref(false)
const brokenImages = ref(new Set<string>())
let detailRequest = 0

function clearDetail() {
  detailRequest += 1
  selected.value = null
  detail.value = null
  child.value = null
  childDetail.value = null
  detailLoading.value = false
  detailError.value = false
}

async function loadPage(nextPage: number) {
  loading.value = true
  listError.value = false
  clearDetail()
  try {
    const { data } = await api.get(`/admin/users/${props.user.id}/image-history`, {
      params: { offset: nextPage * pageSize, limit: pageSize },
    })
    entries.value = data.items
    hasMore.value = data.has_more
    page.value = nextPage
  } catch {
    listError.value = true
  } finally {
    loading.value = false
  }
}

async function loadDetail(kind: Kind, id: string, isChild = false) {
  const request = ++detailRequest
  detailLoading.value = true
  detailError.value = false
  try {
    const { data } = await api.get(`/admin/users/${props.user.id}/image-history/${kind}/${id}`)
    if (request === detailRequest) {
      if (isChild) childDetail.value = data
      else detail.value = data
    }
  } catch {
    if (request === detailRequest) detailError.value = true
  } finally {
    if (request === detailRequest) detailLoading.value = false
  }
}

function openEntry(entry: Entry) {
  clearDetail()
  selected.value = entry
  void loadDetail(entry.kind, entry.id)
}

function openChild(entry: Child) {
  if (!entry.job_kind || !entry.job_id) return
  child.value = entry
  childDetail.value = null
  void loadDetail(entry.job_kind, entry.job_id, true)
}

function retryDetail() {
  if (child.value) openChild(child.value)
  else if (selected.value) openEntry(selected.value)
}

watch(() => props.user.id, () => void loadPage(0), { immediate: true })
</script>

<template>
  <a-drawer :open="true" :width="'min(780px, 100vw)'" :title="`生图历史 · ${user.display_name}`" @close="emit('close')">
    <a-spin :spinning="loading">
      <a-alert v-if="listError" type="error" message="生图历史加载失败" show-icon>
        <template #action><a-button size="small" @click="loadPage(page)">重试</a-button></template>
      </a-alert>
      <a-empty v-else-if="!entries.length && !loading" description="暂无生图记录" />
      <ul v-else class="history-list">
        <li v-for="entry in entries" :key="`${entry.kind}-${entry.id}`">
          <button type="button" :aria-pressed="selected?.id === entry.id" @click="openEntry(entry)">
            <strong>{{ labels[entry.kind] }}</strong>
            <time :datetime="entry.created_at">{{ new Date(entry.created_at).toLocaleString() }}</time>
            <span>{{ statuses[entry.status] || entry.status }}</span>
            <span>{{ entry.count }} {{ entry.kind === 'batch' ? '个子任务' : '张 / 模块' }}</span>
          </button>
        </li>
      </ul>
      <div v-if="page || hasMore" class="history-pagination">
        <a-button :disabled="!page || loading" @click="loadPage(page - 1)">上一页</a-button>
        <span>第 {{ page + 1 }} 页</span>
        <a-button :disabled="!hasMore || loading" @click="loadPage(page + 1)">下一页</a-button>
      </div>
    </a-spin>

    <section v-if="selected" class="history-detail">
      <h3>{{ labels[selected.kind] }}详情</h3>
      <p v-if="detail?.error" class="history-error">{{ detail.error }}</p>
      <ul v-if="detail?.children" class="history-list">
        <li v-for="entry in detail.children" :key="entry.id">
          <button :disabled="!entry.job_id" :aria-pressed="child?.id === entry.id" @click="openChild(entry)">
            <strong>{{ entry.name }}</strong><span>{{ statuses[entry.status] || entry.status }}</span>
          </button>
          <p v-if="entry.error" class="history-error">{{ entry.error }}</p>
        </li>
      </ul>
      <p v-if="detailLoading" role="status">正在加载任务详情…</p>
      <a-alert v-if="detailError" type="error" message="任务详情加载失败" show-icon>
        <template #action><a-button size="small" @click="retryDetail">重试</a-button></template>
      </a-alert>

      <template v-for="job in [childDetail || (detail?.children ? null : detail)]" :key="job?.id">
        <div v-if="job">
          <p v-if="childDetail?.error" class="history-error">{{ childDetail.error }}</p>
          <h4>用户原始输入</h4>
          <pre>{{ job.input ?? '未记录' }}</pre>
          <h4>AI 帮写 / 转写</h4>
          <pre>{{ job.rewrite ?? (job.rewrite_recorded ? '未执行' : '未记录') }}</pre>
          <h4>实际提交内容</h4>
          <pre>{{ job.submitted_input ?? '未记录' }}</pre>
          <p v-if="job.source_plan_id">关联 A+ 策划 <code>{{ job.source_plan_id }}</code></p>

          <h4>生成 Prompt</h4>
          <template v-if="job.steps?.some(step => step.prompt)">
            <details v-for="(step, index) in job.steps.filter(step => step.prompt)" :key="index" :open="index === 0">
              <summary>{{ job.items?.find(item => item.id === step.item_id)?.label || '图片' }} · {{ step.instruction ? '编辑 / 重生成' : '生图' }}</summary>
              <pre v-if="step.instruction">{{ step.instruction }}</pre>
              <pre>{{ step.prompt }}</pre>
            </details>
          </template>
          <p v-else>{{ job.dry_run || !job.items?.length ? '未执行' : '未记录' }}</p>

          <h4>输出与版本</h4>
          <p v-if="!job.items?.length">暂无输出</p>
          <article v-for="item in job.items" :key="item.id" class="history-output">
            <strong>{{ item.label }} · {{ statuses[item.status] || item.status }}</strong>
            <p v-if="item.error" class="history-error">{{ item.error }}</p>
            <details v-if="item.planned_prompt">
              <summary>策划内容</summary>
              <pre>{{ item.planned_prompt }}</pre>
            </details>
            <div v-if="item.versions.length" class="history-images">
              <figure v-for="version in item.versions" :key="version.id">
                <a-image v-if="version.url && !brokenImages.has(version.id)" :src="version.url" :alt="item.label" @error="brokenImages.add(version.id)" />
                <span v-else>图片不可用</span>
                <figcaption>版本 {{ version.version_no }} {{ version.instruction }}</figcaption>
              </figure>
            </div>
            <p v-else>暂无输出</p>
          </article>

          <details v-if="job.steps?.length" class="history-steps">
            <summary>执行日志</summary>
            <ul>
              <li v-for="(step, index) in job.steps" :key="index">
                {{ step.node }} · {{ statuses[step.status] || step.status }}
                <span v-if="step.error" class="history-error">{{ step.error }}</span>
              </li>
            </ul>
          </details>
        </div>
      </template>
    </section>
  </a-drawer>
</template>

<style scoped>
.history-list { list-style: none; padding: 0; margin: 0; }
.history-list button { display: flex; flex-wrap: wrap; gap: .75rem; width: 100%; text-align: left; margin-bottom: .5rem; padding: .65rem .8rem; border: 1px solid #e2e8f0; border-radius: 8px; background: #fff; }
.history-list button[aria-pressed="true"] { border-color: #2563eb; background: #eff6ff; }
.history-list button:disabled { opacity: .65; }
.history-pagination { display: flex; align-items: center; justify-content: flex-end; gap: .75rem; }
.history-detail { border-top: 1px solid #e2e8f0; margin-top: 1rem; padding-top: 1rem; }
.history-detail h4 { margin-top: 1rem; }
.history-detail pre { white-space: pre-wrap; overflow-wrap: anywhere; background: #f8fafc; border-radius: 8px; padding: .65rem .8rem; }
.history-output { border: 1px solid #e2e8f0; border-radius: 8px; padding: .75rem; margin-bottom: .6rem; }
.history-images { display: flex; flex-wrap: wrap; gap: .75rem; margin-top: .5rem; }
.history-images figure { width: 140px; margin: 0; overflow-wrap: anywhere; }
.history-error { color: #b42318; overflow-wrap: anywhere; }
.history-steps { margin-top: 1rem; }
</style>
