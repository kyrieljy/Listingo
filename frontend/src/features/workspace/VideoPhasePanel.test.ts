// @vitest-environment jsdom

import { flushPromises, mount } from '@vue/test-utils'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { message } from 'ant-design-vue'

import {
  cancelVideoJob,
  getVideoJob,
  listVideoJobs,
  retryFailedVideoItems,
} from '../../api/client'
import VideoPhasePanel from './VideoPhasePanel.vue'
import type { VideoJob } from '../../api/client'

vi.mock('ant-design-vue', async (importActual) => ({
  ...(await importActual<Record<string, unknown>>()),
  message: {
    error: vi.fn(),
    warning: vi.fn(),
    success: vi.fn(),
    info: vi.fn(),
  },
}))

vi.mock('../../api/client', async (importActual) => {
  const actual = await importActual<Record<string, unknown>>()
  return {
    ...actual,
    assistVideoCopywriting: vi.fn(),
    cancelVideoJob: vi.fn(),
    createVideoJob: vi.fn(),
    editVideoItem: vi.fn(),
    getVideoJob: vi.fn(),
    listVideoJobs: vi.fn().mockResolvedValue([]),
    retryFailedVideoItems: vi.fn(),
    uploadAsset: vi.fn(),
    videoDownloadUrl: vi.fn(),
  }
})

vi.mock('../auth/auth-store', () => ({
  useAuthStore: () => ({ isAuthenticated: true }),
}))

vi.mock('./analytics', () => ({
  trackWorkspaceEvent: vi.fn(),
}))

vi.mock('/demo/video-skincare-source.png', () => ({ default: '/demo/video-skincare-source.png' }))
vi.mock('/demo/video-skincare-result.png', () => ({ default: '/demo/video-skincare-result.png' }))
vi.mock('/demo/video-skincare-hero.png', () => ({ default: '/demo/video-skincare-hero.png' }))
vi.mock('/demo/video-skincare-frame-01.png', () => ({ default: '/demo/video-skincare-frame-01.png' }))
vi.mock('/demo/video-skincare-frame-02.png', () => ({ default: '/demo/video-skincare-frame-02.png' }))
vi.mock('/demo/video-skincare-frame-03.png', () => ({ default: '/demo/video-skincare-frame-03.png' }))

const failedVideoJob = (): VideoJob => ({
  id: 'video-job-1',
  status: 'partial_failed',
  dry_run: true,
  progress: 50,
  count: 2,
  params: {},
  error: 'provider exception',
  created_at: '2026-08-29T08:00:00Z',
  items: [
    {
      id: 'video-item-1',
      index: 0,
      video_type: 'UGC 种草',
      status: 'succeeded',
      provider_id: 'provider',
      provider_task_id: 'task',
      error: null,
      prompt_text: '',
      script_markdown: '',
      current_version_id: 'video-version-1',
      versions: [{
        id: 'video-version-1',
        parent_version_id: null,
        version_no: 1,
        instruction: 'initial',
        url: 'https://example.test/video.mp4',
        created_at: '2026-08-29T08:01:00Z',
        remote_url: 'https://example.test/video.mp4',
      }],
    },
    {
      id: 'video-item-2',
      index: 1,
      video_type: '痛点解决',
      status: 'failed',
      provider_id: null,
      provider_task_id: null,
      error: 'provider exception',
      prompt_text: '',
      script_markdown: '',
      current_version_id: null,
      versions: [],
    },
  ],
})

function deferred<T>() {
  let resolve!: (value: T) => void
  let reject!: (reason?: unknown) => void
  const promise = new Promise<T>((promiseResolve, promiseReject) => {
    resolve = promiseResolve
    reject = promiseReject
  })
  return { promise, resolve, reject }
}

async function mountWithFailedJob(job: VideoJob = failedVideoJob()) {
  vi.mocked(getVideoJob).mockResolvedValue(job)
  const wrapper = mount(VideoPhasePanel, {
    global: {
      stubs: {
        'a-modal': true,
        CheckOutlined: true,
        CloseOutlined: true,
        CloudUploadOutlined: true,
        DownloadOutlined: true,
        EditOutlined: true,
        PlayCircleOutlined: true,
        ReloadOutlined: true,
        RocketOutlined: true,
        ThunderboltOutlined: true,
      },
    },
  })
  await flushPromises()
  await (wrapper.vm as unknown as { openHistoryJob: (job: VideoJob) => Promise<void> }).openHistoryJob(job)
  return wrapper
}

function retryButton(wrapper: ReturnType<typeof mount>) {
  return wrapper.findAll('button').find((button) => button.text().includes('重试失败'))
}

function cancelButtons(wrapper: ReturnType<typeof mount>) {
  return wrapper.findAll('button').filter((button) => button.text().includes('取消任务'))
}

describe('VideoPhasePanel retry cooldown', () => {
  beforeEach(() => {
    vi.useFakeTimers()
    vi.clearAllMocks()
    vi.mocked(message.error).mockClear()
    vi.mocked(listVideoJobs).mockResolvedValue([])
  })

  afterEach(() => {
    vi.useRealTimers()
  })

  it('submits one retry on the first click and hides cancel through the cooldown', async () => {
    const retryResponse = deferred<VideoJob>()
    vi.mocked(retryFailedVideoItems).mockReturnValue(retryResponse.promise)
    const wrapper = await mountWithFailedJob()
    const button = retryButton(wrapper)
    expect(button).toBeDefined()

    await button!.trigger('click')
    expect(retryFailedVideoItems).toHaveBeenCalledTimes(1)
    expect(retryFailedVideoItems).toHaveBeenCalledWith('video-job-1')
    expect(cancelButtons(wrapper)).toHaveLength(0)
    expect(retryButton(wrapper)?.attributes('disabled')).toBeDefined()

    await button!.trigger('click')
    await button!.trigger('click')
    await vi.advanceTimersByTimeAsync(1998)
    expect(retryFailedVideoItems).toHaveBeenCalledTimes(1)
    expect(cancelVideoJob).not.toHaveBeenCalled()
    expect(cancelButtons(wrapper)).toHaveLength(0)

    // the retry is dispatched to the background queue, so the job comes back as queued
    // with its failed items reset - only a queued job can still be cancelled
    const queuedJob: VideoJob = {
      ...failedVideoJob(),
      status: 'queued',
      error: null,
      items: failedVideoJob().items.map((item) =>
        item.status === 'failed' ? { ...item, status: 'queued', error: null } : item,
      ),
    }
    vi.mocked(getVideoJob).mockResolvedValue(queuedJob)
    retryResponse.resolve(queuedJob)
    await vi.advanceTimersByTimeAsync(2)

    expect(retryButton(wrapper)).toBeUndefined()
    expect(cancelButtons(wrapper).length).toBeGreaterThan(0)

    await cancelButtons(wrapper)[0]!.trigger('click')
    expect(cancelVideoJob).toHaveBeenCalledTimes(1)
    expect(cancelVideoJob).toHaveBeenCalledWith('video-job-1')
  })

  it('keeps cancel hidden after cooldown when retried work is terminal', async () => {
    const initialJob = failedVideoJob()
    const terminalJob = failedVideoJob()
    terminalJob.status = 'succeeded'
    terminalJob.items[1] = {
      ...terminalJob.items[1]!,
      status: 'succeeded',
      error: null,
      current_version_id: 'video-version-2',
      versions: [{
        id: 'video-version-2',
        parent_version_id: null,
        version_no: 1,
        instruction: 'initial',
        url: 'https://example.test/retried.mp4',
        created_at: '2026-08-29T08:02:00Z',
        remote_url: 'https://example.test/retried.mp4',
      }],
    }
    vi.mocked(retryFailedVideoItems).mockResolvedValue(terminalJob)
    const wrapper = await mountWithFailedJob(initialJob)
    vi.mocked(getVideoJob).mockResolvedValue(terminalJob)

    await retryButton(wrapper)!.trigger('click')
    await vi.advanceTimersByTimeAsync(0)
    await vi.advanceTimersByTimeAsync(2001)

    expect(cancelButtons(wrapper)).toHaveLength(0)
    expect(retryButton(wrapper)).toBeUndefined()
  })

  it('restores a retryable failed state only after a failed retry request cooldown', async () => {
    vi.mocked(retryFailedVideoItems).mockRejectedValue(new Error('retry request failed'))
    const wrapper = await mountWithFailedJob()

    await retryButton(wrapper)!.trigger('click')
    await vi.advanceTimersByTimeAsync(0)
    expect(message.error).toHaveBeenCalledTimes(1)
    expect(retryButton(wrapper)?.attributes('disabled')).toBeDefined()

    await vi.advanceTimersByTimeAsync(1998)
    expect(retryButton(wrapper)?.attributes('disabled')).toBeDefined()
    await vi.advanceTimersByTimeAsync(1)
    expect(retryButton(wrapper)?.attributes('disabled')).toBe('')
    expect(retryFailedVideoItems).toHaveBeenCalledTimes(1)
  })

  it('clears the retry cooldown when a new task starts', async () => {
    const retryResponse = deferred<VideoJob>()
    vi.mocked(retryFailedVideoItems).mockReturnValue(retryResponse.promise)
    const wrapper = await mountWithFailedJob()
    await retryButton(wrapper)!.trigger('click')

    await (wrapper.vm as unknown as { startNewTask: () => void }).startNewTask()
    await vi.advanceTimersByTimeAsync(2000)
    retryResponse.resolve({ ...failedVideoJob(), status: 'succeeded' })
    await vi.runAllTimersAsync()

    expect(cancelButtons(wrapper)).toHaveLength(0)
    expect(retryButton(wrapper)).toBeUndefined()
  })
})
