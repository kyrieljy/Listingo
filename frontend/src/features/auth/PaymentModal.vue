<script setup lang="ts">
import { computed, onUnmounted, ref, watch } from 'vue'
import { createNativePaymentApi, getPaymentOrderApi, type PaymentOrderDto } from '../../api/client'
import { useAuthStore } from './auth-store'

const props = defineProps<{ order: PaymentOrderDto | null }>()
const emit = defineEmits<{ close: []; paid: []; retry: [] }>()
const auth = useAuthStore()
const codeUrl = ref('')
const expiresAt = ref('')
const status = ref('pending')
const error = ref('')
const loading = ref(false)
const now = ref(Date.now())
let timer: ReturnType<typeof setTimeout> | undefined
let generation = 0
const expired = computed(() => !!expiresAt.value && now.value >= Date.parse(expiresAt.value))
const terminal = computed(() => ['closed', 'expired', 'manual_review', 'refunded'].includes(status.value))
const canRetry = computed(() => expired.value || ['closed', 'expired'].includes(status.value))

function errorMessage(e: unknown) {
  const detail = (e as { response?: { data?: { detail?: unknown } } })?.response?.data?.detail
  return typeof detail === 'string' ? detail : '网络暂不可用，请重试。已付款订单会在后台继续确认，请勿重复付款。'
}

function stop() {
  generation++
  clearTimeout(timer)
}

async function poll(id: string, token: number) {
  if (token !== generation) return
  now.value = Date.now()
  try {
    const order = await getPaymentOrderApi(id)
    if (token !== generation) return
    now.value = Date.now()
    status.value = order.status
    if (codeUrl.value) error.value = ''
    if (order.status === 'paid') {
      status.value = 'paid'
      try { await auth.refreshAfterPayment() } catch { error.value = '支付已成功，账户刷新失败，请刷新页面查看权益。' }
      if (token === generation) emit('paid')
      return
    }
    if (terminal.value) return
  } catch (e) {
    if (token !== generation) return
    error.value = errorMessage(e)
  }
  // Keep checking local state after QR expiry: a just-completed payment may still be confirming.
  if (token === generation) timer = setTimeout(() => void poll(id, token), 3000)
}

async function start() {
  stop()
  const order = props.order
  if (!order) return
  const token = generation
  codeUrl.value = ''
  error.value = ''
  status.value = 'pending'
  expiresAt.value = order.expires_at || ''
  now.value = Date.now()
  loading.value = true
  try {
    const payment = await createNativePaymentApi(order.id)
    if (token !== generation) return
    codeUrl.value = payment.code_url
    expiresAt.value = payment.expires_at
  } catch (e) {
    if (token !== generation) return
    error.value = errorMessage(e)
  } finally {
    if (token === generation) {
      loading.value = false
      void poll(order.id, token)
    }
  }
}

watch(() => props.order?.id, () => { if (props.order) void start(); else stop() }, { immediate: true })
onUnmounted(stop)
</script>

<template>
  <a-modal :open="!!order" title="微信扫码支付" :footer="null" :width="420" centered @cancel="emit('close')">
    <div class="payment-content" aria-live="polite">
      <p>{{ order?.product_type === 'bean_pack' ? order.bean_pack_name : order?.plan_name }}</p>
      <strong class="payment-price">¥{{ ((order?.amount_cents || 0) / 100).toFixed(2) }}</strong>
      <a-spin v-if="loading" tip="正在获取支付二维码" />
      <template v-else-if="codeUrl && !expired && !terminal && status !== 'paid'">
        <a-qrcode :value="codeUrl" :size="220" error-level="M" />
        <p>请使用微信扫一扫完成支付</p>
      </template>
      <p v-if="status === 'paid'" role="status">支付成功，权益已到账</p>
      <p v-else-if="status === 'manual_review'" role="status">订单需要人工核对，请联系客服并提供订单号，请勿重复付款。</p>
      <p v-else-if="canRetry">二维码已过期或订单已关闭。若已付款，请等待到账确认。</p>
      <p v-else-if="status === 'refunded'">订单已退款</p>
      <a-alert v-if="error" :message="error" type="warning" show-icon />
      <a-button v-if="!loading && !codeUrl && !terminal && !expired && status !== 'paid'" @click="start">重试获取二维码</a-button>
      <a-button v-if="canRetry" @click="emit('retry')">重新下单</a-button>
      <small>订单号：{{ order?.order_no }}</small>
      <small>关闭此窗口后，已完成的付款仍会自动确认到账。</small>
    </div>
  </a-modal>
</template>

<style scoped>
.payment-content { display: flex; align-items: center; flex-direction: column; gap: 14px; padding: 12px 0; text-align: center; }
.payment-content p { margin: 0; }
.payment-price { font-size: 30px; }
.payment-content small { color: #687384; overflow-wrap: anywhere; }
</style>
