// @vitest-environment jsdom
import { defineComponent } from 'vue'
import { flushPromises, mount } from '@vue/test-utils'
import { describe, expect, it, vi } from 'vitest'
import BatchHostingModal from './BatchHostingModal.vue'
import BatchTaskCard from './BatchTaskCard.vue'
import SuiteStructureConfig from './SuiteStructureConfig.vue'
import { createDefaultWorkspaceForm } from './workspace-model'
import type { BatchTaskDraft } from './batch-model'
import { createBatchJob } from '../../api/client'

vi.mock('../auth/auth-store', () => ({ useAuthStore: () => ({ isAuthenticated: true, isAdmin: true, showInsufficientBeans: () => false }) }))
vi.mock('./analytics', () => ({ trackWorkspaceEvent: vi.fn() }))
vi.mock('../../api/client', async (original) => ({
  ...await original<object>(),
  getWorkspaceConfig: vi.fn(async () => ({ max_upload_bytes: 1000, max_batch_tasks: 100, max_batch_item_assets: 6, max_active_batch_items: 1, max_provider_concurrency: 4 })),
  createBatchJob: vi.fn(async () => ({ id: 'batch' })),
}))

describe('batch suite modal', () => {
  it('submits 100 configured products and prevents a 101st card', async () => {
    const form = createDefaultWorkspaceForm()
    form.mode = 'custom'
    form.customCounts = { white_background: 1, scene: 0, selling_point: 0, other: 0 }
    const wrapper = mount(BatchHostingModal, {
      props: { open: true, businessType: 'suite', suiteForm: form },
      global: { stubs: {
        'a-modal': defineComponent({ template: '<div><slot /></div>' }),
        BatchHistoryDrawer: true,
      } },
    })
    await flushPromises()
    const first = wrapper.findAllComponents(BatchTaskCard)[0]!
    first.vm.$emit('update', { ...(first.props('task') as BatchTaskDraft), sellingPoints: 'Durable', assets: [{ id: 'asset', url: '/demo.png', original_name: 'demo' }] })
    await flushPromises()
    wrapper.findAllComponents(BatchTaskCard)[1]!.vm.$emit('delete')
    await flushPromises()
    for (let i = 1; i < 100; i++) {
      wrapper.findComponent(BatchTaskCard).vm.$emit('copy')
      await flushPromises()
    }
    expect(wrapper.findAllComponents(BatchTaskCard)).toHaveLength(100)
    await wrapper.find('.batch-add-task').trigger('click')
    expect(wrapper.findAllComponents(BatchTaskCard)).toHaveLength(100)
    const globalStructure = wrapper.findComponent(SuiteStructureConfig)
    expect(globalStructure.props('params')).toMatchObject({ mode: 'custom', count: 1 })
    // Changing unrelated global fields must retain the structure.
    await wrapper.find('.batch-global-grid select').setValue('亚马逊')
    expect(globalStructure.props('params')).toMatchObject({ mode: 'custom', count: 1 })
    await wrapper.find('.submit-batch-action').trigger('click')
    await flushPromises()
    const payload = vi.mocked(createBatchJob).mock.calls.at(-1)![0]
    expect(payload.items).toHaveLength(100)
    expect(payload.global_params).toMatchObject({ mode: 'custom', count: 1, custom_counts: form.customCounts })
    expect(wrapper.text()).toContain('预计生成 100 张')
    wrapper.unmount()
  }, 30000)
})
