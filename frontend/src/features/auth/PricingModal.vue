<script setup lang="ts">
import { computed, nextTick, reactive, ref, watch } from 'vue'
import { CheckOutlined, CloseOutlined, CrownOutlined, SafetyCertificateOutlined } from '@ant-design/icons-vue'
import type { EnterpriseLeadMonthlyUsage } from '../../api/client'
import type { PlanKey } from './auth-model'
import { useAuthStore } from './auth-store'

const props = withDefaults(defineProps<{
  open: boolean
  initialView?: 'plans' | 'packs'
}>(), {
  initialView: 'plans',
})

const emit = defineEmits<{
  'update:open': [value: boolean]
  requireAuth: []
}>()

const authStore = useAuthStore()
const billing = ref<'monthly' | 'yearly'>('monthly')
const submittingPlan = ref('')
const submittingPack = ref('')
const enterpriseOpen = ref(false)
const submittingLead = ref(false)
const leadError = ref('')
const leadForm = reactive({
  name: '',
  phone: '',
  wechat: '',
  company_or_shop: '',
  monthly_usage: '' as EnterpriseLeadMonthlyUsage | '',
  requirement: '',
})
const packSection = ref<HTMLElement | null>(null)

const monthlyUsageOptions: Array<{ value: EnterpriseLeadMonthlyUsage; label: string }> = [
  { value: 'under_1000', label: '1000 张以内 / 月' },
  { value: '1000_5000', label: '1000 - 5000 张 / 月' },
  { value: '5000_20000', label: '5000 - 20000 张 / 月' },
  { value: 'over_20000', label: '20000 张以上 / 月' },
  { value: 'unsure', label: '暂不确定' },
]

const visible = computed({
  get: () => props.open,
  set: (value: boolean) => emit('update:open', value),
})
const enterprisePlan = computed(() => authStore.plans.find((plan) => plan.contactSales && !plan.adminOnly))
const displayPlans = computed(() => [
  ...authStore.plans.filter((plan) => !plan.adminOnly && !plan.contactSales && plan.billingCycle === billing.value),
  ...(enterprisePlan.value ? [enterprisePlan.value] : []),
])
const displayPacks = computed(() => authStore.beanPacks.filter((pack) => pack.enabled && pack.visible))

watch(() => props.open, (open) => {
  if (!open) return
  void authStore.loadPlans()
  void focusInitialView()
})

watch(() => props.initialView, () => {
  if (props.open) void focusInitialView()
})

async function focusInitialView(): Promise<void> {
  await nextTick()
  if (props.initialView === 'packs') packSection.value?.scrollIntoView({ behavior: 'smooth', block: 'start' })
}

function cycleLabel(plan: { billingCycle: string }): string {
  if (plan.billingCycle === 'yearly') return '年'
  if (plan.billingCycle === 'monthly') return '月'
  if (plan.billingCycle === 'custom') return '定制'
  return ''
}

function planSummary(plan: { beans: number | null; contactSales: boolean }): string {
  if (plan.contactSales) return '根据企业用量定制豆子额度'
  if (plan.beans === null) return '--'
  return `${plan.beans} 豆 / ${cycleLabel(plan)}`
}

function packSummary(beans: number): string {
  return `约 ${Math.floor(beans / 12)} 张高清商品图`
}

function openEnterpriseForm() {
  leadError.value = ''
  enterpriseOpen.value = true
}

async function choosePlan(planKey: PlanKey, contactSales: boolean): Promise<void> {
  if (contactSales) {
    openEnterpriseForm()
    return
  }
  if (!authStore.isAuthenticated) {
    emit('requireAuth')
    return
  }
  submittingPlan.value = planKey
  try {
    await authStore.choosePlan(planKey, billing.value)
    visible.value = false
  } finally {
    submittingPlan.value = ''
  }
}

async function purchasePack(packCode: string): Promise<void> {
  if (!authStore.isAuthenticated) {
    emit('requireAuth')
    return
  }
  submittingPack.value = packCode
  try {
    await authStore.purchaseBeanPack(packCode)
  } finally {
    submittingPack.value = ''
  }
}

async function submitLead() {
  if (!leadForm.name.trim() || !leadForm.phone.trim() || !leadForm.company_or_shop.trim() || !leadForm.monthly_usage) {
    leadError.value = '请填写姓名、手机号、店铺名 / 公司名，并选择月生成量'
    return
  }
  const phoneDigits = leadForm.phone.trim().replace(/[\s-]/g, '').replace(/^\+/, '')
  if (!/^\d{5,32}$/.test(phoneDigits)) {
    leadError.value = '请输入有效手机号'
    return
  }
  submittingLead.value = true
  leadError.value = ''
  try {
    await authStore.submitEnterpriseLead({
      name: leadForm.name.trim(),
      phone: leadForm.phone.trim(),
      wechat: leadForm.wechat.trim(),
      company_or_shop: leadForm.company_or_shop.trim(),
      monthly_usage: leadForm.monthly_usage,
      requirement: leadForm.requirement.trim(),
    })
    enterpriseOpen.value = false
  } catch {
    leadError.value = '提交失败，请稍后重试。'
  } finally {
    submittingLead.value = false
  }
}
</script>

<template>
  <a-modal
    v-model:open="visible"
    :footer="null"
    :closable="false"
    :width="1180"
    centered
    class="pricing-shell-modal"
    wrap-class-name="pricing-modal-wrap"
  >
    <div class="pricing-modal-card">
      <button class="auth-close-button pricing-close" type="button" aria-label="关闭套餐选择" @click="visible = false">
        <CloseOutlined />
      </button>
      <header class="pricing-head">
        <span><CrownOutlined />LISTINGO PLANS</span>
        <h2>选择适合当前生产节奏的套餐</h2>
        <p>套餐、价格、豆子权益和企业版联系方式由后台统一配置。</p>
        <div class="pricing-billing-switch" aria-label="计费周期">
          <button type="button" :class="{ active: billing === 'monthly' }" @click="billing = 'monthly'">月付</button>
          <button type="button" :class="{ active: billing === 'yearly' }" @click="billing = 'yearly'">年付</button>
        </div>
      </header>

      <section class="pricing-grid">
        <article v-for="plan in displayPlans" :key="plan.key" class="pricing-card" :class="{ featured: plan.featured }" tabindex="0">
          <div v-if="plan.badge" class="pricing-badge">{{ plan.badge }}</div>
          <header>
            <h3>{{ plan.name }}</h3>
            <p>{{ plan.description }}</p>
            <strong>{{ plan.price }}<small>{{ plan.period }}</small></strong>
            <em>{{ planSummary(plan) }}</em>
          </header>
          <ul>
            <li v-for="feature in plan.features" :key="feature"><CheckOutlined />{{ feature }}</li>
          </ul>
          <button
            type="button"
            :disabled="submittingPlan === plan.key || (!plan.contactSales && authStore.user?.plan === plan.key)"
            @click="choosePlan(plan.key, plan.contactSales)"
          >
            {{ submittingPlan === plan.key ? '处理中' : (!plan.contactSales && authStore.user?.plan === plan.key) ? '当前套餐' : plan.cta }}
          </button>
        </article>
      </section>

      <section ref="packSection" class="bean-pack-section" :class="{ focused: initialView === 'packs' }">
        <header>
          <h3>单独补豆包</h3>
          <p>补豆包仅补充额度，不解锁会员专属功能。</p>
        </header>
        <div class="bean-pack-grid">
          <article v-for="pack in displayPacks" :key="pack.id" :class="{ recommended: pack.recommended }">
            <div>
              <b>{{ pack.name }}</b>
              <strong>¥{{ pack.amount_cents / 100 }}</strong>
            </div>
            <span>{{ pack.beans }} 豆</span>
            <small>{{ packSummary(pack.beans) }}</small>
            <button type="button" :disabled="submittingPack === pack.code" @click="purchasePack(pack.code)">
              {{ submittingPack === pack.code ? '支付中' : '立即购买' }}
            </button>
          </article>
        </div>
        <p class="bean-pack-rules">12 豆可生成 1 张高清商品图。系统生成失败不扣豆，已扣豆将自动返还。</p>
      </section>

      <footer class="pricing-note">
        <SafetyCertificateOutlined />
        <span>企业版不显示固定价格，可联系商务获取团队协作、API 接入、定制工作流和专属报价。</span>
      </footer>
    </div>

    <a-modal
      v-model:open="enterpriseOpen"
      :footer="null"
      :width="520"
      centered
      class="enterprise-lead-modal"
      wrap-class-name="enterprise-lead-modal-wrap"
    >
      <div class="enterprise-lead-card">
        <header>
          <h3>申请企业定制方案</h3>
          <p>请留下您的联系方式，我们会根据您的使用规模和业务需求，为您提供专属报价。</p>
        </header>
        <div class="enterprise-lead-fields">
          <label>姓名<input v-model="leadForm.name" placeholder="请输入您的姓名" /></label>
          <label>手机号<input v-model="leadForm.phone" placeholder="请输入手机号" /></label>
          <label>微信号<input v-model="leadForm.wechat" placeholder="请输入微信号" /></label>
          <label>店铺名 / 公司名<input v-model="leadForm.company_or_shop" placeholder="请输入店铺名或公司名" /></label>
          <label>月生成量
            <select v-model="leadForm.monthly_usage">
              <option value="" disabled>请选择预计月生成量</option>
              <option v-for="option in monthlyUsageOptions" :key="option.value" :value="option.value">{{ option.label }}</option>
            </select>
          </label>
          <label>需求说明<textarea v-model="leadForm.requirement" rows="3" placeholder="请简单描述您的需求" /></label>
        </div>
        <p v-if="leadError" class="enterprise-lead-error">{{ leadError }}</p>
        <footer>
          <button type="button" class="secondary" :disabled="submittingLead" @click="enterpriseOpen = false">取消</button>
          <button type="button" class="primary" :disabled="submittingLead" @click="submitLead">
            {{ submittingLead ? '提交中' : '提交咨询' }}
          </button>
        </footer>
      </div>
    </a-modal>
  </a-modal>
</template>
