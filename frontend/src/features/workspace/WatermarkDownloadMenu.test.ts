// @vitest-environment jsdom

import { defineComponent } from 'vue'
import { mount } from '@vue/test-utils'
import { describe, expect, it } from 'vitest'

import WatermarkDownloadMenu from './WatermarkDownloadMenu.vue'

const AModalStub = defineComponent({
  props: {
    open: { type: Boolean, default: false },
    okText: { type: String, default: '' },
    cancelText: { type: String, default: '' },
    okButtonProps: { type: Object, default: () => ({}) },
  },
  emits: ['ok', 'cancel', 'update:open'],
  template: `
    <section v-if="open" class="modal-stub">
      <slot />
      <button class="modal-close" type="button" @click="$emit('update:open', false)">close</button>
      <button class="modal-cancel" type="button" @click="$emit('cancel'); $emit('update:open', false)">{{ cancelText }}</button>
      <button class="modal-ok" type="button" :disabled="okButtonProps.disabled" @click="$emit('ok')">{{ okText }}</button>
    </section>
  `,
})

async function openWatermarkMenu(canExportWithoutWatermark: boolean) {
  const wrapper = mount(WatermarkDownloadMenu, {
    props: {
      selectedCount: 1,
      includeWatermark: true,
      canExportWithoutWatermark,
    },
    global: {
      stubs: {
        'a-modal': AModalStub,
        DownloadOutlined: true,
        MoreOutlined: true,
      },
    },
  })
  await wrapper.find('[aria-label="下载偏好"]').trigger('click')
  return wrapper
}

describe('WatermarkDownloadMenu', () => {
  it('requires acknowledgement before a subscribed user can disable the watermark', async () => {
    const wrapper = await openWatermarkMenu(true)
    const watermarkInput = wrapper.get('input[type="checkbox"]')

    ;(watermarkInput.element as HTMLInputElement).checked = false
    await watermarkInput.trigger('change')

    expect(wrapper.emitted('update:includeWatermark')).toBeUndefined()
    expect((watermarkInput.element as HTMLInputElement).checked).toBe(true)

    const modal = wrapper.getComponent(AModalStub)
    expect(modal.props('open')).toBe(true)
    expect(modal.props('okButtonProps')).toEqual({ disabled: true, danger: true })
    expect(wrapper.text()).toContain('亲爱的创作者，您即将获取一张无平台印记的AI作品。去掉水印，意味着这张图将完全以“您认为的样子”进入现实世界。')
    expect(wrapper.text()).toContain('AI不是原创者')
    expect(wrapper.text()).toContain('防止误导公众')
    expect(wrapper.get('.watermark-acknowledgement p').text())
      .toBe('亲爱的创作者，您即将获取一张无平台印记的AI作品。去掉水印，意味着这张图将完全以“您认为的样子”进入现实世界。')
    expect(wrapper.findAll('.watermark-acknowledgement p')[1]!.text()).toBe('在此，平台恳请您务必留意：')
    expect(wrapper.get('.watermark-acknowledgement li').text()).toBe('AI不是原创者：AI模型基于海量人类作品训练，生成内容可能存在“风格撞车”风险。AI生成图不具有《著作权法》意义上的“独创性”，若您将其作为“原创”商用，存在被第三方起诉抄袭的风险，此风险需由您自行规避。')
    expect(wrapper.findAll('.watermark-acknowledgement li')[1]!.text()).toBe('防止误导公众：根据法规要求，若您发布的图片涉及新闻时事、公众人物或可能影响社会舆论，请务必在显眼位置标注“由AI生成”。因未标注导致的社会误解或谣言扩散，平台将配合监管部门追溯至您的账号。')

    await modal.get('.modal-ok').trigger('click')
    expect(wrapper.emitted('update:includeWatermark')).toBeUndefined()

    await modal.get('input[type="checkbox"]').setValue(true)
    expect(modal.props('okButtonProps')).toEqual({ disabled: false, danger: true })

    await modal.get('.modal-ok').trigger('click')
    expect(wrapper.emitted('update:includeWatermark')).toEqual([[false]])
  })

  it('keeps watermark state unchanged when acknowledgement is cancelled', async () => {
    const wrapper = await openWatermarkMenu(true)
    const watermarkInput = wrapper.get('input[type="checkbox"]')
    ;(watermarkInput.element as HTMLInputElement).checked = false
    await watermarkInput.trigger('change')

    const modal = wrapper.getComponent(AModalStub)
    await modal.get('input[type="checkbox"]').setValue(true)
    await modal.get('.modal-close').trigger('click')

    expect(wrapper.emitted('update:includeWatermark')).toBeUndefined()
    expect(wrapper.findComponent(AModalStub).props('open')).toBe(false)

    await wrapper.find('[aria-label="下载偏好"]').trigger('click')
    ;(watermarkInput.element as HTMLInputElement).checked = false
    await watermarkInput.trigger('change')
    expect(wrapper.getComponent(AModalStub).props('okButtonProps'))
      .toEqual({ disabled: true, danger: true })
  })

  it('keeps non-subscribed users locked to watermark exports', async () => {
    const wrapper = await openWatermarkMenu(false)
    const watermarkInput = wrapper.get('input[type="checkbox"]')

    expect(watermarkInput.attributes('disabled')).toBeDefined()
    expect(wrapper.text()).toContain('开通会员取消水印')
    await wrapper.get('.watermark-upgrade-link').trigger('click')
    expect(wrapper.emitted('upgrade')).toHaveLength(1)
    expect(wrapper.emitted('update:includeWatermark')).toBeUndefined()
  })

  it('lets a subscribed user turn the watermark back on immediately', async () => {
    const wrapper = mount(WatermarkDownloadMenu, {
      props: {
        selectedCount: 1,
        includeWatermark: false,
        canExportWithoutWatermark: true,
      },
      global: {
        stubs: {
          'a-modal': AModalStub,
          DownloadOutlined: true,
          MoreOutlined: true,
        },
      },
    })
    await wrapper.find('[aria-label="下载偏好"]').trigger('click')
    const watermarkInput = wrapper.get('input[type="checkbox"]')
    ;(watermarkInput.element as HTMLInputElement).checked = true
    await watermarkInput.trigger('change')

    expect(wrapper.emitted('update:includeWatermark')).toEqual([[true]])
  })
})
