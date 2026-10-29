// @vitest-environment jsdom
import { defineComponent } from 'vue'
import { flushPromises, mount } from '@vue/test-utils'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import PaymentModal from './PaymentModal.vue'
import { createNativePaymentApi, getPaymentOrderApi, type PaymentOrderDto } from '../../api/client'

const mocks = vi.hoisted(() => ({ refresh: vi.fn() }))
vi.mock('../../api/client', () => ({ createNativePaymentApi: vi.fn(), getPaymentOrderApi: vi.fn() }))
vi.mock('./auth-store', () => ({ useAuthStore: () => ({ refreshAfterPayment: mocks.refresh }) }))

const order = { id: 'one', order_no: 'ORDER1', product_type: 'bean_pack', bean_pack_name: '补豆包', amount_cents: 5000,
  expires_at: new Date(Date.now() + 1800000).toISOString() } as PaymentOrderDto
const stubs = {
  'a-modal': defineComponent({ props: ['open'], template: '<section v-if="open"><slot /></section>' }),
  'a-qrcode': defineComponent({ props: ['value'], template: '<div class="qr">{{ value }}</div>' }),
  'a-button': defineComponent({ template: '<button><slot /></button>' }),
  'a-alert': defineComponent({ props: ['message'], template: '<p>{{ message }}</p>' }),
  'a-spin': true,
}

describe('Wechat payment window', () => {
  beforeEach(() => {
    vi.useFakeTimers()
    vi.mocked(createNativePaymentApi).mockResolvedValue({ order_id: order.id, code_url: 'weixin://wxpay/test', expires_at: order.expires_at! })
    vi.mocked(getPaymentOrderApi).mockResolvedValue({ ...order, status: 'pending' })
    mocks.refresh.mockResolvedValue(undefined)
  })
  afterEach(() => { vi.useRealTimers(); vi.clearAllMocks() })

  it('shows QR and refreshes account only after server reports paid', async () => {
    const wrapper = mount(PaymentModal, { props: { order }, global: { stubs } })
    await flushPromises()
    expect(wrapper.find('.qr').text()).toBe('weixin://wxpay/test')
    expect(mocks.refresh).not.toHaveBeenCalled()
    vi.mocked(getPaymentOrderApi).mockResolvedValue({ ...order, status: 'paid' })
    await vi.advanceTimersByTimeAsync(3000)
    await flushPromises()
    expect(mocks.refresh).toHaveBeenCalledTimes(1)
    expect(wrapper.emitted('paid')).toHaveLength(1)
    expect(wrapper.find('.qr').exists()).toBe(false)
    wrapper.unmount()
  })

  it('stops polling after close and ignores a late response', async () => {
    const wrapper = mount(PaymentModal, { props: { order }, global: { stubs } })
    await flushPromises()
    const calls = vi.mocked(getPaymentOrderApi).mock.calls.length
    await wrapper.setProps({ order: null })
    await vi.advanceTimersByTimeAsync(9000)
    expect(getPaymentOrderApi).toHaveBeenCalledTimes(calls)
    wrapper.unmount()
  })

  it('offers retry after expiry and never grants on manual review', async () => {
    const past = new Date(Date.now() - 1000).toISOString()
    vi.mocked(createNativePaymentApi).mockResolvedValue({ order_id: order.id, code_url: 'weixin://wxpay/test', expires_at: past })
    const wrapper = mount(PaymentModal, { props: { order }, global: { stubs } })
    await flushPromises()
    expect(wrapper.find('.qr').exists()).toBe(false)
    expect(wrapper.text()).toContain('重新下单')
    vi.mocked(getPaymentOrderApi).mockResolvedValue({ ...order, status: 'manual_review' })
    await vi.advanceTimersByTimeAsync(3000)
    await flushPromises()
    expect(wrapper.text()).toContain('人工核对')
    expect(mocks.refresh).not.toHaveBeenCalled()
    wrapper.unmount()
  })

  it('shows configuration failure and permits QR retry', async () => {
    vi.mocked(createNativePaymentApi).mockRejectedValue({ response: { data: { detail: '微信支付尚未配置，请联系客服' } } })
    const wrapper = mount(PaymentModal, { props: { order }, global: { stubs } })
    await flushPromises()
    expect(wrapper.text()).toContain('微信支付尚未配置')
    expect(wrapper.text()).toContain('重试获取二维码')
    expect(mocks.refresh).not.toHaveBeenCalled()
    wrapper.unmount()
  })
})
