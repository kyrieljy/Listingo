<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import { message } from 'ant-design-vue'
import {
  adminCreateBeanPackApi,
  adminGetCommercialConfigApi,
  adminUpdateBeanPackApi,
  adminUpdatePlanApi,
  userFacingApiErrorMessage,
  type BeanPackDto,
  type EntitlementValue,
  type SubscriptionPlanDto,
} from '../../api/client'

type PlanDraft = SubscriptionPlanDto & {
  featureText: string
  amountCents: number | null
}

type BeanPackDraft = Omit<BeanPackDto, 'id'> & { id?: string }

const loading = ref(false)
const savingPlanId = ref('')
const savingPackId = ref('')
const creatingPack = ref(false)
const packCreateOpen = ref(false)
const plans = ref<PlanDraft[]>([])
const packs = ref<BeanPackDto[]>([])
const config = ref({ beans_per_image: 12, refund_on_system_failure: true, video_enabled: false })

const emptyPackDraft: BeanPackDraft = {
  code: '',
  name: '',
  description: '',
  amount_cents: 0,
  currency: 'CNY',
  beans: 0,
  recommended: false,
  enabled: true,
  visible: true,
  sort_order: 99,
}
const newPack = ref<BeanPackDraft>({ ...emptyPackDraft })

const monthlyPlans = computed(() => plans.value.filter((plan) => plan.billing_cycle === 'monthly'))
const yearlyPlans = computed(() => plans.value.filter((plan) => plan.billing_cycle === 'yearly'))
const otherPlans = computed(() => plans.value.filter((plan) => plan.billing_cycle !== 'monthly' && plan.billing_cycle !== 'yearly'))
const stats = computed(() => [
  { label: '可展示套餐', value: plans.value.filter((plan) => plan.enabled && plan.visible && !plan.is_internal).length },
  { label: '推荐套餐', value: plans.value.filter((plan) => plan.recommended).length },
  { label: '补豆包', value: packs.value.filter((pack) => pack.enabled && pack.visible).length },
  { label: '企业线索', value: '独立页面' },
])

const batchEntitlementOptions: Array<{ value: EntitlementValue; label: string }> = [
  { value: false, label: '不可用' },
  { value: true, label: '可用' },
  { value: 'basic', label: '基础批量' },
  { value: 'advanced', label: '高级批量' },
  { value: 'custom', label: '企业定制' },
]

const apiAccessOptions: Array<{ value: EntitlementValue; label: string }> = [
  { value: false, label: '未开放' },
  { value: 'negotiable', label: '可沟通' },
  { value: true, label: '已开放' },
]

onMounted(load)

async function load(): Promise<void> {
  loading.value = true
  try {
    const data = await adminGetCommercialConfigApi()
    config.value = {
      beans_per_image: data.beans_per_image,
      refund_on_system_failure: data.refund_on_system_failure,
      video_enabled: data.video_enabled,
    }
    plans.value = data.plans.map(toPlanDraft)
    packs.value = data.bean_packs
  } catch (error) {
    message.error(userFacingApiErrorMessage(error) || '商业化目录加载失败')
  } finally {
    loading.value = false
  }
}

function toPlanDraft(plan: SubscriptionPlanDto): PlanDraft {
  return {
    ...plan,
    entitlements: { ...plan.entitlements },
    features: [...plan.features],
    featureText: plan.features.join('\n'),
    amountCents: plan.prices.find((price) => price.billing_cycle === plan.billing_cycle)?.amount_cents ?? plan.prices[0]?.amount_cents ?? null,
  }
}

function toggleEntitlement(plan: PlanDraft, key: string, event: Event): void {
  plan.entitlements[key] = (event.target as HTMLInputElement).checked
}

function entitlementText(value: EntitlementValue | undefined): string {
  if (value === undefined || value === false) return '未开放'
  if (value === true) return '已开放'
  if (value === 'basic') return '基础'
  if (value === 'advanced') return '高级'
  return String(value)
}

function cycleLabel(cycle: string): string {
  if (cycle === 'monthly') return '月付'
  if (cycle === 'yearly') return '年付'
  if (cycle === 'custom') return '定制'
  if (cycle === 'internal') return '内部'
  if (cycle === 'none') return '无周期'
  return '历史'
}

function validatePlan(plan: PlanDraft): string | null {
  if (plan.contact_sales && plan.amountCents !== null) return '联系销售套餐不能展示固定价格'
  if (!plan.contact_sales && !plan.is_internal && plan.amountCents === null) return '可购买套餐必须配置价格'
  if (!plan.contact_sales && !plan.is_internal && (plan.amountCents ?? 0) < 0) return '价格不能小于 0'
  if (!plan.contact_sales && !plan.is_internal && (plan.beans ?? 0) <= 0) return '可购买套餐必须配置大于 0 的豆子'
  return null
}

async function savePlan(plan: PlanDraft): Promise<void> {
  const validationError = validatePlan(plan)
  if (validationError) {
    message.warning(validationError)
    return
  }
  savingPlanId.value = plan.id
  try {
    const updated = await adminUpdatePlanApi(plan.id, {
      name: plan.name,
      description: plan.description,
      badge: plan.badge,
      cta: plan.cta,
      visible: plan.visible,
      enabled: plan.enabled,
      features: plan.featureText.split('\n').map((item) => item.trim()).filter(Boolean),
      contact_text: plan.contact_text,
      contact_phone: plan.contact_phone,
      billing_cycle: plan.billing_cycle,
      beans: plan.beans,
      recommended: plan.recommended,
      contact_sales: plan.contact_sales,
      entitlements: plan.entitlements,
      amount_cents: plan.contact_sales || plan.is_internal ? null : plan.amountCents,
    })
    plans.value = plans.value.map((item) => item.id === updated.id ? toPlanDraft(updated) : item)
    message.success('套餐已保存')
  } catch (error) {
    message.error(userFacingApiErrorMessage(error) || '套餐保存失败')
  } finally {
    savingPlanId.value = ''
  }
}

function openPackCreate(): void {
  newPack.value = { ...emptyPackDraft }
  packCreateOpen.value = true
}

function validatePack(pack: BeanPackDraft): string | null {
  if (!pack.code.trim() || !pack.name.trim()) return '请填写补豆包编码和名称'
  if (pack.amount_cents <= 0) return '补豆包价格必须大于 0'
  if (pack.beans <= 0) return '补豆包豆子数量必须大于 0'
  return null
}

async function createPack(): Promise<void> {
  const validationError = validatePack(newPack.value)
  if (validationError) {
    message.warning(validationError)
    return
  }
  creatingPack.value = true
  try {
    const created = await adminCreateBeanPackApi({
      code: newPack.value.code.trim(),
      name: newPack.value.name.trim(),
      description: newPack.value.description,
      amount_cents: Number(newPack.value.amount_cents),
      currency: newPack.value.currency || 'CNY',
      beans: Number(newPack.value.beans),
      recommended: newPack.value.recommended,
      enabled: newPack.value.enabled,
      visible: newPack.value.visible,
      sort_order: Number(newPack.value.sort_order),
    })
    packs.value = [...packs.value, created]
    packCreateOpen.value = false
    message.success('补豆包已创建')
  } catch (error) {
    message.error(userFacingApiErrorMessage(error) || '补豆包创建失败')
  } finally {
    creatingPack.value = false
  }
}

async function savePack(pack: BeanPackDto): Promise<void> {
  const validationError = validatePack(pack)
  if (validationError) {
    message.warning(validationError)
    return
  }
  savingPackId.value = pack.id
  try {
    const updated = await adminUpdateBeanPackApi(pack.id, {
      code: pack.code,
      name: pack.name,
      description: pack.description,
      amount_cents: Number(pack.amount_cents),
      currency: pack.currency,
      beans: Number(pack.beans),
      recommended: pack.recommended,
      enabled: pack.enabled,
      visible: pack.visible,
      sort_order: Number(pack.sort_order),
    })
    packs.value = packs.value.map((item) => item.id === updated.id ? updated : item)
    message.success('补豆包已保存')
  } catch (error) {
    message.error(userFacingApiErrorMessage(error) || '补豆包保存失败')
  } finally {
    savingPackId.value = ''
  }
}
</script>

<template>
  <div class="commercial-panel">
    <header class="commercial-hero">
      <div>
        <span>COMMERCIAL V1</span>
        <h2>商业化目录管理</h2>
        <p>维护月付、年付、企业套餐与补豆包；固定计费规则仅展示，不在后台运行时修改。</p>
      </div>
      <div class="commercial-metrics">
        <article v-for="stat in stats" :key="stat.label">
          <small>{{ stat.label }}</small>
          <b>{{ stat.value }}</b>
        </article>
      </div>
    </header>

    <section class="fixed-rules">
      <article>
        <span>扣豆规则</span>
        <strong>{{ config.beans_per_image }} 豆 / 张</strong>
      </article>
      <article>
        <span>失败退款</span>
        <strong>{{ config.refund_on_system_failure ? '系统失败自动返还' : '关闭' }}</strong>
      </article>
      <article>
        <span>视频生成</span>
        <strong>{{ config.video_enabled ? '开启' : '用户侧已关闭' }}</strong>
      </article>
      <article>
        <span>批量能力</span>
        <strong>仅读取 batch_generation</strong>
      </article>
    </section>

    <section v-for="group in [
      { title: '月付套餐', rows: monthlyPlans },
      { title: '年付套餐', rows: yearlyPlans },
      { title: '其他套餐', rows: otherPlans },
    ]" :key="group.title" class="plan-group">
      <header>
        <h3>{{ group.title }}</h3>
        <small>{{ group.rows.length }} 个套餐</small>
      </header>
      <div class="plan-grid">
        <article v-for="plan in group.rows" :key="plan.id" class="plan-card" :class="{ disabled: !plan.enabled }">
          <header>
            <div>
              <code>{{ plan.code }}</code>
              <em v-if="plan.recommended">推荐</em>
              <em v-if="plan.is_internal">内部</em>
            </div>
            <input v-model="plan.name" aria-label="套餐名称" />
          </header>
          <div class="field-grid">
            <label>计费周期
              <select v-model="plan.billing_cycle" :disabled="plan.billing_cycle === 'legacy'">
                <option value="monthly">月付</option>
                <option value="yearly">年付</option>
                <option value="custom">定制</option>
                <option value="none">无周期</option>
                <option value="internal">内部</option>
                <option value="legacy">历史</option>
              </select>
            </label>
            <label>价格（分）
              <input v-if="!plan.contact_sales && !plan.is_internal" v-model.number="plan.amountCents" type="number" min="0" />
              <input v-else value="按商务报价 / 内部使用" disabled />
            </label>
            <label>豆子数量<input v-model.number="plan.beans" type="number" min="0" :disabled="plan.contact_sales || plan.is_internal" /></label>
            <label>展示顺序（由迁移配置）<input :value="plan.sort_order" type="number" disabled /></label>
            <label>角标<input v-model="plan.badge" /></label>
            <label>按钮文案<input v-model="plan.cta" /></label>
          </div>
          <label class="block-field">套餐描述<textarea v-model="plan.description" rows="3" /></label>
          <label class="block-field">展示权益（每行一条）<textarea v-model="plan.featureText" rows="4" /></label>
          <div class="flag-row">
            <label><input v-model="plan.enabled" type="checkbox" />启用</label>
            <label><input v-model="plan.visible" type="checkbox" />前端展示</label>
            <label><input v-model="plan.recommended" type="checkbox" />推荐</label>
            <label><input v-model="plan.contact_sales" type="checkbox" />联系销售</label>
          </div>
          <div class="field-grid entitlement-grid">
            <label>批量生成
              <select v-model="plan.entitlements.batch_generation">
                <option v-for="option in batchEntitlementOptions" :key="String(option.value)" :value="option.value">{{ option.label }}</option>
              </select>
            </label>
            <label>API 接入
              <select v-model="plan.entitlements.api_access">
                <option v-for="option in apiAccessOptions" :key="String(option.value)" :value="option.value">{{ option.label }}</option>
              </select>
            </label>
            <label>优先队列（仅展示）<input :value="entitlementText(plan.entitlements.priority_queue)" disabled /></label>
            <label>团队协作<input :value="entitlementText(plan.entitlements.team_collaboration)" disabled /></label>
          </div>
          <div class="flag-row">
            <label><input type="checkbox" :checked="Boolean(plan.entitlements.team_collaboration)" @change="toggleEntitlement(plan, 'team_collaboration', $event)" />团队协作</label>
            <label><input type="checkbox" :checked="Boolean(plan.entitlements.custom_workflow)" @change="toggleEntitlement(plan, 'custom_workflow', $event)" />定制工作流</label>
            <label><input type="checkbox" :checked="Boolean(plan.entitlements.exclusive_support)" @change="toggleEntitlement(plan, 'exclusive_support', $event)" />专属客服</label>
          </div>
          <div class="field-grid">
            <label>企业联系电话<input v-model="plan.contact_phone" /></label>
            <label>企业联系文案<input v-model="plan.contact_text" /></label>
          </div>
          <button class="primary" type="button" :disabled="savingPlanId === plan.id" @click="savePlan(plan)">
            {{ savingPlanId === plan.id ? '保存中' : '保存套餐' }}
          </button>
        </article>
      </div>
    </section>

    <section class="pack-section">
      <header>
        <div>
          <h3>补豆包目录</h3>
          <p>补豆包不改变会员权益；有有效会员时随会员权益期过期，无有效会员时 30 天内有效。</p>
        </div>
        <button type="button" @click="openPackCreate">新增补豆包</button>
      </header>
      <div class="pack-grid">
        <article v-for="pack in packs" :key="pack.id" class="pack-card">
          <div class="field-grid">
            <label>编码<input v-model="pack.code" /></label>
            <label>名称<input v-model="pack.name" /></label>
            <label>价格（分）<input v-model.number="pack.amount_cents" type="number" min="1" /></label>
            <label>豆子数量<input v-model.number="pack.beans" type="number" min="12" /></label>
            <label>展示顺序<input v-model.number="pack.sort_order" type="number" min="0" /></label>
            <label>推荐<input v-model="pack.recommended" type="checkbox" /></label>
          </div>
          <label class="block-field">说明<textarea v-model="pack.description" rows="2" /></label>
          <div class="flag-row">
            <label><input v-model="pack.enabled" type="checkbox" />启用</label>
            <label><input v-model="pack.visible" type="checkbox" />前端展示</label>
          </div>
          <button class="primary" type="button" :disabled="savingPackId === pack.id" @click="savePack(pack)">
            {{ savingPackId === pack.id ? '保存中' : '保存补豆包' }}
          </button>
        </article>
      </div>
    </section>

    <a-modal v-model:open="packCreateOpen" title="新增补豆包" :footer="null">
      <div class="pack-create-form">
        <div class="field-grid">
          <label>编码<input v-model="newPack.code" placeholder="bean_pack_custom" /></label>
          <label>名称<input v-model="newPack.name" /></label>
          <label>价格（分）<input v-model.number="newPack.amount_cents" type="number" min="1" /></label>
          <label>豆子数量<input v-model.number="newPack.beans" type="number" min="12" /></label>
          <label>展示顺序<input v-model.number="newPack.sort_order" type="number" min="0" /></label>
          <label>推荐<input v-model="newPack.recommended" type="checkbox" /></label>
        </div>
        <label class="block-field">说明<textarea v-model="newPack.description" rows="3" /></label>
        <div class="flag-row">
          <label><input v-model="newPack.enabled" type="checkbox" />启用</label>
          <label><input v-model="newPack.visible" type="checkbox" />前端展示</label>
        </div>
        <button class="primary" type="button" :disabled="creatingPack" @click="createPack">{{ creatingPack ? '创建中' : '创建补豆包' }}</button>
      </div>
    </a-modal>

    <p v-if="loading" class="loading-text">商业化目录加载中...</p>
  </div>
</template>

<style scoped>
.commercial-panel {
  display: grid;
  gap: 20px;
}

.commercial-hero {
  display: flex;
  justify-content: space-between;
  gap: 20px;
  padding: 22px 24px;
  border: 1px solid #e7e9ef;
  border-radius: 8px;
  background: #fff;
}

.commercial-hero span {
  color: #778091;
  font-size: 11px;
  font-weight: 850;
}

.commercial-hero h2 {
  margin: 6px 0;
  color: #1a2032;
  font-size: 22px;
}

.commercial-hero p {
  margin: 0;
  color: #687185;
}

.commercial-metrics {
  display: grid;
  grid-template-columns: repeat(4, minmax(110px, 1fr));
  gap: 8px;
}

.commercial-metrics article {
  display: grid;
  gap: 4px;
  padding: 12px;
  border: 1px solid #edf0f5;
  border-radius: 8px;
  background: #fbfcfe;
}

.fixed-rules {
  display: grid;
  grid-template-columns: repeat(4, minmax(0, 1fr));
  gap: 10px;
}

.fixed-rules article,
.plan-card,
.pack-card {
  border: 1px solid #e6e9f0;
  border-radius: 8px;
  background: #fff;
}

.fixed-rules article {
  display: grid;
  gap: 5px;
  padding: 14px;
}

.fixed-rules span {
  color: #7d8595;
  font-size: 11px;
}

.fixed-rules strong {
  color: #1e2536;
  font-size: 14px;
}

.plan-group > header,
.pack-section > header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
}

.plan-group h3,
.pack-section h3 {
  margin: 0;
  color: #1b2233;
  font-size: 17px;
}

.plan-group small,
.pack-section p {
  margin: 0;
  color: #717a8b;
}

.plan-grid,
.pack-grid {
  display: grid;
  grid-template-columns: repeat(2, minmax(0, 1fr));
  gap: 14px;
}

.plan-card,
.pack-card,
.pack-create-form {
  display: grid;
  gap: 12px;
  padding: 16px;
}

.plan-card.disabled {
  background: #f8f9fb;
}

.plan-card header {
  display: grid;
  gap: 8px;
}

.plan-card header div {
  display: flex;
  align-items: center;
  gap: 7px;
}

.plan-card code {
  color: #687288;
  font-size: 11px;
}

.plan-card em {
  padding: 3px 6px;
  border-radius: 999px;
  background: #eef2fa;
  color: #4c587a;
  font-size: 10px;
  font-style: normal;
  font-weight: 800;
}

.plan-card input,
.pack-card input,
.pack-create-form input,
.plan-card select,
.pack-card select,
.plan-card textarea,
.pack-card textarea,
.pack-create-form textarea {
  width: 100%;
  min-width: 0;
  border: 1px solid #dfe3eb;
  border-radius: 7px;
  padding: 7px 9px;
  color: #28303f;
}

.plan-card input,
.pack-card input,
.pack-create-form input,
.plan-card select {
  height: 34px;
}

.field-grid {
  display: grid;
  grid-template-columns: repeat(3, minmax(0, 1fr));
  gap: 9px;
}

.field-grid label,
.block-field {
  display: grid;
  gap: 5px;
  color: #747d8e;
  font-size: 11px;
  font-weight: 750;
}

.block-field textarea {
  border: 1px solid #dfe3eb;
  border-radius: 7px;
  color: #28303f;
  padding: 8px;
}

.flag-row {
  display: flex;
  flex-wrap: wrap;
  gap: 12px;
}

.flag-row label {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  color: #3c4454;
  font-size: 12px;
}

.primary,
.pack-section > header button {
  height: 36px;
  justify-self: start;
  padding: 0 14px;
  border: 0;
  border-radius: 7px;
  background: #182130;
  color: #fff;
  cursor: pointer;
  font-weight: 800;
}

.pack-section > header button {
  background: #fff;
  border: 1px solid #cfd6e3;
  color: #243047;
}

.loading-text {
  margin: 0;
  color: #77818f;
}

@media (max-width: 1400px) {
  .plan-grid,
  .pack-grid {
    grid-template-columns: 1fr;
  }
}

@media (max-width: 900px) {
  .commercial-hero,
  .fixed-rules,
  .field-grid {
    grid-template-columns: 1fr;
  }

  .commercial-hero,
  .fixed-rules {
    display: grid;
  }

  .commercial-metrics {
    grid-template-columns: repeat(2, minmax(0, 1fr));
  }
}
</style>
