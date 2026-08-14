<script setup lang="ts">
import { computed, ref, watch } from 'vue'
import { CheckOutlined, CloseOutlined, CrownOutlined, SafetyCertificateOutlined } from '@ant-design/icons-vue'
import type { MembershipPlan, PlanKey } from './auth-model'
import { useAuthStore } from './auth-store'

const props = defineProps<{ open: boolean }>()

const emit = defineEmits<{
  'update:open': [value: boolean]
  requireAuth: []
}>()

const authStore = useAuthStore()
const billing = ref<'monthly' | 'yearly'>('monthly')
const submittingPlan = ref('')
const visible = computed({
  get: () => props.open,
  set: (value: boolean) => emit('update:open', value),
})

const visiblePlans = computed(() => authStore.plans.filter((plan) => !plan.adminOnly))
const displayPlans = computed(() => visiblePlans.value.map((plan) => displayPlan(plan)))

watch(() => props.open, (open) => {
  if (open) void authStore.loadPlans()
})

function displayPlan(plan: MembershipPlan): MembershipPlan {
  if (!plan.source) return plan
  const price = plan.source.prices.find((item) => item.billing_cycle === billing.value) || plan.source.prices[0]
  return {
    ...plan,
    price: plan.source.is_enterprise ? '联系我们' : price?.price_label || plan.price,
    period: plan.source.is_enterprise ? '' : price?.period_label || plan.period,
  }
}

function quotaSummary(plan: MembershipPlan): string {
  if (Object.values(plan.quota).every((value) => value === 'unlimited')) return '不限额度'
  return `${plan.quota.image_generation ?? 0} 套图 / ${plan.quota.aplus_generation ?? 0} A+ / ${plan.quota.video_generation ?? 0} 视频`
}

async function choosePlan(planKey: PlanKey): Promise<void> {
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
        <p>套餐、价格、权益、额度和企业版联系方式由后台统一配置。</p>
        <div class="pricing-billing-switch" aria-label="计费周期">
          <button type="button" :class="{ active: billing === 'monthly' }" @click="billing = 'monthly'">月付</button>
          <button type="button" :class="{ active: billing === 'yearly' }" @click="billing = 'yearly'">年付</button>
        </div>
      </header>

      <section class="pricing-grid">
        <article v-for="plan in displayPlans" :key="plan.key" class="pricing-card" tabindex="0">
            <div v-if="plan.badge" class="pricing-badge">{{ plan.badge }}</div>
            <header>
              <h3>{{ plan.name }}</h3>
              <p>{{ plan.description }}</p>
              <strong>{{ plan.price }}<small>{{ plan.period }}</small></strong>
              <em>{{ plan.enterprise ? (plan.contactPhone ? `联系 ${plan.contactPhone}` : '企业定制方案') : quotaSummary(plan) }}</em>
            </header>
            <ul>
              <li v-for="feature in plan.features" :key="feature"><CheckOutlined />{{ feature }}</li>
            </ul>
            <button type="button" :disabled="submittingPlan === plan.key || authStore.user?.plan === plan.key" @click="choosePlan(plan.key)">
              {{ submittingPlan === plan.key ? '处理中' : authStore.user?.plan === plan.key ? '当前套餐' : plan.cta }}
            </button>
        </article>
      </section>

      <footer class="pricing-note">
        <SafetyCertificateOutlined />
        <span>企业版不显示金额，可联系商务获取团队账号、私有化部署、品牌流程和定制开发方案。</span>
      </footer>
    </div>
  </a-modal>
</template>
