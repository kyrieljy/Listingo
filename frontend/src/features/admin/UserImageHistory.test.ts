// @vitest-environment jsdom

import { flushPromises, mount } from '@vue/test-utils'
import { expect, it, vi } from 'vitest'
import { api } from '../../api/client'
import UserImageHistory from './UserImageHistory.vue'

vi.mock('../../api/client', () => ({ api: { get: vi.fn() } }))

it('collapses a selected record and ignores its pending response', async () => {
  const get = vi.mocked(api.get)
  const record = { id: 'record', kind: 'suite', status: 'succeeded', count: 7, created_at: '2026-11-10T00:00:00Z' }
  let finishRequest!: (value: { data: { input: string } }) => void
  get.mockResolvedValueOnce({ data: { items: [record], has_more: false } })
  get.mockImplementationOnce(() => new Promise(resolve => { finishRequest = resolve }))
  get.mockResolvedValueOnce({ data: { input: '重新展开的详情' } })

  const slot = { template: '<div><slot /></div>' }
  const wrapper = mount(UserImageHistory, {
    props: { user: { id: 'test-user', display_name: '测试用户' } },
    global: { stubs: { ADrawer: slot, ASpin: slot } },
  })
  await flushPromises()
  const row = wrapper.get('.history-list button')
  await row.trigger('click')
  expect(row.attributes('aria-expanded')).toBe('true')
  expect(wrapper.get('.history-detail').text()).toContain('正在加载任务详情')

  await row.trigger('click')
  expect(row.attributes('aria-expanded')).toBe('false')
  expect(wrapper.find('.history-detail').exists()).toBe(false)
  expect(get).toHaveBeenCalledTimes(2)

  finishRequest({ data: { input: '过期的详情' } })
  await flushPromises()
  expect(wrapper.find('.history-detail').exists()).toBe(false)

  await row.trigger('click')
  await flushPromises()
  expect(wrapper.get('.history-detail').text()).toContain('重新展开的详情')
  await row.trigger('click')
  expect(wrapper.find('.history-detail').exists()).toBe(false)
  wrapper.unmount()
})
