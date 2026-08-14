// @vitest-environment jsdom

import { flushPromises, mount } from '@vue/test-utils'
import { beforeEach, describe, expect, it, vi } from 'vitest'

import { adminGetBusinessUserMetricsApi } from '../../api/client'
import UserDrilldownPanel from './UserDrilldownPanel.vue'
import type { MetricDefinition, MetricRow, MonitoringQueryState } from './monitoring-data'

vi.mock('../../api/client', () => ({
  adminGetBusinessUserMetricsApi: vi.fn(),
  userFacingApiErrorMessage: (error: unknown) => error instanceof Error ? error.message : '请求失败',
}))

const filters: MonitoringQueryState = {
  start_at: '2026-08-07T11:20',
  end_at: '2026-08-14T11:20',
  granularity: 'day',
}

const definitions: Record<string, MetricDefinition> = {}

const missingUser: MetricRow = {
  user_id: 'missing-user',
  display_name: 'Missing User',
  uid: 'U-MISSING',
  plan: 'internal',
  top_feature: 'A+ 详情',
  top_platform: '亚马逊',
}

function mountPanel(users: MetricRow[], prototypeMode = false) {
  return mount(UserDrilldownPanel, {
    props: { users, filters, definitions, prototypeMode },
    global: {
      stubs: {
        ComparisonMatrix: { props: ['rows'], template: '<div class="matrix-stub">{{ rows.length }}</div>' },
        MetricKpiStrip: { props: ['cards'], template: '<div class="kpi-stub">{{ cards.length }}</div>' },
        MonitoringPager: { template: '<div class="pager-stub" />' },
        SearchOutlined: true,
      },
    },
  })
}

describe('UserDrilldownPanel', () => {
  beforeEach(() => {
    vi.mocked(adminGetBusinessUserMetricsApi).mockReset()
  })

  it('keeps stale user detail failures local to the drilldown panel', async () => {
    vi.mocked(adminGetBusinessUserMetricsApi).mockRejectedValue(new Error('用户不存在'))

    const wrapper = mountPanel([missingUser])
    await flushPromises()
    await flushPromises()

    expect(adminGetBusinessUserMetricsApi).toHaveBeenCalledWith('missing-user', {
      start_at: new Date(filters.start_at).toISOString(),
      end_at: new Date(filters.end_at).toISOString(),
      granularity: 'day',
    })
    expect(wrapper.find('.monitoring-inline-error').text()).toContain('用户详情暂不可用：用户不存在')
    expect(wrapper.text()).not.toContain('监控模块暂不可用')
  })

  it('does not request prototype users on the live dashboard when real user rows are empty', async () => {
    const wrapper = mountPanel([])
    await flushPromises()

    expect(adminGetBusinessUserMetricsApi).not.toHaveBeenCalled()
    expect(wrapper.text()).toContain('未选择用户')
    expect(wrapper.text()).not.toContain('U10027891')
  })
})
