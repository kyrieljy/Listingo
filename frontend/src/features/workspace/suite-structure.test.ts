// @vitest-environment jsdom
import { describe, expect, it } from 'vitest'
import { mount } from '@vue/test-utils'
import SuiteStructureConfig from './SuiteStructureConfig.vue'
import BatchTaskCard from './BatchTaskCard.vue'
import { batchValidationSummary, createBatchGlobalParams, createBatchTaskDraft, effectiveSuiteParams, estimateTaskOutputs, suiteStructureParams, suiteStructureValid } from './batch-model'
import { createDefaultWorkspaceForm } from './workspace-model'

const one = { white_background: 1, scene: 0, selling_point: 0, other: 0 }
const config = { max_upload_bytes: 1, max_batch_tasks: 100, max_batch_item_assets: 6, max_active_batch_items: 1, max_provider_concurrency: 4 }

describe('suite structure', () => {
  it('inherits and copies the single-suite allocation without sharing objects', () => {
    const form = createDefaultWorkspaceForm()
    form.mode = 'custom'
    form.customCounts = { ...one }
    const global = createBatchGlobalParams('suite', form)
    form.customCounts.scene = 2
    expect(global.custom_counts).toEqual(one)
    expect(estimateTaskOutputs('suite', global)).toBe(1)
    expect(estimateTaskOutputs('suite', global, { mode: 'smart', count: 7 })).toBe(7)
    expect(effectiveSuiteParams(global, { mode: 'smart', count: 7 }).custom_counts).toBeNull()
  })

  it('validates custom boundaries and calculates mixed batch outputs', () => {
    for (const counts of [one, { white_background: 4, scene: 2, selling_point: 0, other: 0 }, { white_background: 4, scene: 4, selling_point: 4, other: 0 }]) {
      expect(suiteStructureValid(suiteStructureParams('custom', counts))).toBe(true)
    }
    for (const counts of [{ ...one, white_background: 0 }, { ...one, white_background: 5 }, { white_background: 4, scene: 4, selling_point: 4, other: 1 }]) {
      expect(suiteStructureValid(suiteStructureParams('custom', counts))).toBe(false)
    }
    expect(suiteStructureValid({ mode: 'custom', count: 2, custom_counts: one })).toBe(false)
    const tasks = Array.from({ length: 3 }, (_, i) => ({ ...createBatchTaskDraft(i), assets: [{ id: 'a' }] as ReturnType<typeof createBatchTaskDraft>['assets'], sellingPoints: 'Durable' }))
    tasks[1]!.overrides = suiteStructureParams('custom', one)
    tasks[2]!.overrides = suiteStructureParams('custom', { white_background: 4, scene: 4, selling_point: 4, other: 0 })
    expect(batchValidationSummary('suite', tasks, { mode: 'smart', count: 7 }, config).estimatedImages).toBe(20)
    const hundred = Array.from({ length: 100 }, () => tasks[0]!)
    expect(batchValidationSummary('suite', hundred, {}, config).limitExceeded).toBe(false)
    expect(batchValidationSummary('suite', [...hundred, tasks[0]!], {}, config).limitExceeded).toBe(true)
  })

  it('renders one image, enforces limits, and emits an updated allocation', async () => {
    const wrapper = mount(SuiteStructureConfig, { props: { params: suiteStructureParams('custom', one) } })
    expect(wrapper.text()).toContain('共 1 张')
    expect(wrapper.find('button[aria-label="减少白底图"]').attributes('disabled')).toBeDefined()
    await wrapper.find('button[aria-label="增加场景图"]').trigger('click')
    expect(wrapper.emitted('change')?.[0]?.[0]).toMatchObject({ count: 2, custom_counts: { ...one, scene: 1 } })
  })

  it('freezes a single task allocation and resumes following global changes', async () => {
    const task = createBatchTaskDraft()
    task.overridesOpen = true
    const wrapper = mount(BatchTaskCard, { props: { task, index: 1, businessType: 'suite', config, globalParams: suiteStructureParams('custom', one), canDelete: false, validationMessages: [], highlighted: false } })
    const follow = () => wrapper.find('input[type="checkbox"]')
    await follow().setValue(false)
    const updated = wrapper.emitted('update')!.at(-1)![0] as typeof task
    expect(updated.overrides).toMatchObject({ mode: 'custom', count: 1, custom_counts: one })
    await wrapper.setProps({ task: updated, globalParams: { mode: 'smart', count: 7 } })
    expect(wrapper.text()).toContain('共 1 张')
    await follow().setValue(true)
    const resumed = wrapper.emitted('update')!.at(-1)![0] as typeof task
    expect(resumed.overrides).toEqual({})
    await wrapper.setProps({ task: resumed })
    expect(wrapper.find('select').exists()).toBe(true)
    expect(wrapper.findComponent(SuiteStructureConfig).props('params')).toMatchObject({ mode: 'smart', count: 7 })
  })
})
