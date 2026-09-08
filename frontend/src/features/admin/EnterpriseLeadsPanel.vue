<script setup lang="ts">
import { onMounted, reactive, ref } from 'vue'
import { message } from 'ant-design-vue'
import {
  adminExportEnterpriseLeadsApi,
  adminListEnterpriseLeadsApi,
  adminUpdateEnterpriseLeadNoteApi,
  adminUpdateEnterpriseLeadStatusApi,
  userFacingApiErrorMessage,
  type EnterpriseLeadDto,
} from '../../api/client'

const loading = ref(false)
const exporting = ref(false)
const savingId = ref('')
const leads = ref<EnterpriseLeadDto[]>([])
const filters = reactive({ status: '', q: '', created_from: '', created_to: '' })

const statusOptions = [
  { value: 'pending', label: '待跟进' },
  { value: 'following', label: '跟进中' },
  { value: 'converted', label: '已成交' },
  { value: 'invalid', label: '无效线索' },
]

const usageLabels: Record<EnterpriseLeadDto['monthly_usage'], string> = {
  under_1000: '1000 张以内 / 月',
  '1000_5000': '1000 - 5000 张 / 月',
  '5000_20000': '5000 - 20000 张 / 月',
  over_20000: '20000 张以上 / 月',
  unsure: '暂不确定',
}

onMounted(load)

async function load(): Promise<void> {
  loading.value = true
  try {
    leads.value = await adminListEnterpriseLeadsApi({
      status: filters.status || undefined,
      q: filters.q.trim() || undefined,
      created_from: filters.created_from || undefined,
      created_to: filters.created_to || undefined,
    })
  } catch (error) {
    message.error(userFacingApiErrorMessage(error) || '企业线索加载失败')
  } finally {
    loading.value = false
  }
}

function statusLabel(status: EnterpriseLeadDto['status']): string {
  return statusOptions.find((item) => item.value === status)?.label ?? status
}

async function updateStatus(lead: EnterpriseLeadDto): Promise<void> {
  savingId.value = lead.id
  try {
    const updated = await adminUpdateEnterpriseLeadStatusApi(lead.id, lead.status)
    replaceLead(updated)
    message.success('线索状态已更新')
  } catch (error) {
    message.error(userFacingApiErrorMessage(error) || '线索状态更新失败')
  } finally {
    savingId.value = ''
  }
}

async function saveNote(lead: EnterpriseLeadDto): Promise<void> {
  savingId.value = lead.id
  try {
    const updated = await adminUpdateEnterpriseLeadNoteApi(lead.id, lead.note)
    replaceLead(updated)
    message.success('线索备注已保存')
  } catch (error) {
    message.error(userFacingApiErrorMessage(error) || '线索备注保存失败')
  } finally {
    savingId.value = ''
  }
}

function replaceLead(updated: EnterpriseLeadDto): void {
  leads.value = leads.value.map((item) => item.id === updated.id ? updated : item)
}

async function exportCsv(): Promise<void> {
  exporting.value = true
  try {
    const blob = await adminExportEnterpriseLeadsApi()
    const url = URL.createObjectURL(blob)
    const anchor = document.createElement('a')
    anchor.href = url
    anchor.download = `listingo-enterprise-leads-${new Date().toISOString().slice(0, 10)}.csv`
    anchor.click()
    URL.revokeObjectURL(url)
    message.success('CSV 已导出')
  } catch (error) {
    message.error(userFacingApiErrorMessage(error) || 'CSV 导出失败')
  } finally {
    exporting.value = false
  }
}
</script>

<template>
  <div class="leads-panel">
    <header>
      <div>
        <span>ENTERPRISE LEADS</span>
        <h2>企业线索管理</h2>
        <p>匿名提交的线索会显示访客来源，登录用户会同时记录账号快照。</p>
      </div>
      <button type="button" :disabled="exporting" @click="exportCsv">{{ exporting ? '导出中' : '导出 CSV' }}</button>
    </header>

    <form class="filter-bar" @submit.prevent="load">
      <label>状态
        <select v-model="filters.status">
          <option value="">全部</option>
          <option v-for="option in statusOptions" :key="option.value" :value="option.value">{{ option.label }}</option>
        </select>
      </label>
      <label>搜索<input v-model="filters.q" placeholder="姓名 / 手机号 / 公司" /></label>
      <label>开始日期<input v-model="filters.created_from" type="date" /></label>
      <label>结束日期<input v-model="filters.created_to" type="date" /></label>
      <button type="submit">筛选</button>
    </form>

    <p v-if="loading" class="state-text">线索加载中...</p>
    <p v-else-if="!leads.length" class="state-text">暂无符合条件的线索</p>

    <article v-for="lead in leads" v-else :key="lead.id" class="lead-card">
      <header>
        <div>
          <b>{{ lead.company_or_shop }}</b>
          <small>{{ lead.name }} · {{ lead.phone }}{{ lead.wechat ? ` · ${lead.wechat}` : '' }}</small>
        </div>
        <select v-model="lead.status" @change="updateStatus(lead)">
          <option v-for="option in statusOptions" :key="option.value" :value="option.value">{{ option.label }}</option>
        </select>
      </header>
      <dl>
        <div><dt>月生成量</dt><dd>{{ usageLabels[lead.monthly_usage] }}</dd></div>
        <div><dt>账号</dt><dd>{{ lead.user_id ? lead.account_phone : '匿名访客' }}</dd></div>
        <div><dt>来源</dt><dd>{{ lead.source }}</dd></div>
        <div><dt>创建时间</dt><dd>{{ new Date(lead.created_at).toLocaleString('zh-CN', { hour12: false }) }}</dd></div>
      </dl>
      <p v-if="lead.requirement">{{ lead.requirement }}</p>
      <label>跟进备注<textarea v-model="lead.note" rows="3" /></label>
      <button type="button" :disabled="savingId === lead.id" @click="saveNote(lead)">保存备注</button>
    </article>
  </div>
</template>

<style scoped>
.leads-panel {
  display: grid;
  gap: 16px;
}

.leads-panel > header,
.filter-bar,
.lead-card > header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 14px;
}

.leads-panel > header {
  padding: 20px 22px;
  border: 1px solid #e7e9ef;
  border-radius: 8px;
  background: #fff;
}

.leads-panel span {
  color: #778091;
  font-size: 11px;
  font-weight: 850;
}

h2 {
  margin: 6px 0;
  color: #1a2032;
  font-size: 22px;
}

header p {
  margin: 0;
  color: #687185;
}

button,
input,
select,
textarea {
  border: 1px solid #d9dee8;
  border-radius: 7px;
  color: #29303f;
}

button {
  height: 36px;
  padding: 0 14px;
  background: #182130;
  color: #fff;
  cursor: pointer;
  font-weight: 800;
}

.filter-bar {
  flex-wrap: wrap;
  padding: 13px;
  border: 1px solid #e7e9ef;
  border-radius: 8px;
  background: #fbfcfe;
}

.filter-bar label {
  display: grid;
  gap: 4px;
  color: #747d8e;
  font-size: 11px;
  font-weight: 750;
}

.filter-bar input,
.filter-bar select {
  height: 34px;
  padding: 0 9px;
}

.lead-card {
  display: grid;
  gap: 12px;
  padding: 16px;
  border: 1px solid #e6e9f0;
  border-radius: 8px;
  background: #fff;
}

.lead-card header > div {
  display: grid;
  gap: 4px;
}

.lead-card b {
  color: #1d2434;
  font-size: 15px;
}

.lead-card small {
  color: #737c8c;
}

.lead-card select {
  height: 34px;
  padding: 0 9px;
}

dl {
  display: grid;
  grid-template-columns: repeat(4, minmax(0, 1fr));
  gap: 9px;
  margin: 0;
}

dl div {
  display: grid;
  gap: 3px;
  padding: 9px;
  border-radius: 7px;
  background: #f8f9fc;
}

dt {
  color: #7b8393;
  font-size: 11px;
}

dd {
  margin: 0;
  color: #28303f;
  font-size: 12px;
}

.lead-card > p {
  margin: 0;
  padding: 10px;
  border-radius: 7px;
  background: #f8f9fc;
  color: #414a5a;
  line-height: 1.6;
}

label {
  display: grid;
  gap: 5px;
  color: #747d8e;
  font-size: 11px;
  font-weight: 750;
}

textarea {
  padding: 8px;
  line-height: 1.55;
}

.lead-card > button {
  justify-self: start;
}

.state-text {
  margin: 0;
  padding: 18px;
  border: 1px dashed #d8dee9;
  border-radius: 8px;
  color: #77818f;
  text-align: center;
}

@media (max-width: 900px) {
  .leads-panel > header,
  .lead-card > header,
  .filter-bar,
  dl {
    display: grid;
    grid-template-columns: 1fr;
  }
}
</style>
