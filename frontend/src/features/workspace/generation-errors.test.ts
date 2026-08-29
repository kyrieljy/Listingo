import { describe, expect, it } from 'vitest'

import {
  GENERATION_FAILURE_MESSAGES,
  resolveGenerationFailureMessage,
} from './generation-errors'

describe('generation failure messages', () => {
  it('returns phase-specific fallbacks in production', () => {
    const failedImageJob = {
      status: 'partial_failed',
      error: 'provider exploded',
      items: [{ index: 0, status: 'failed', error: 'internal trace' }],
    }

    expect(resolveGenerationFailureMessage('image', failedImageJob, { detailed: false }))
      .toBe('生成图片失败，请稍后重试')
    expect(resolveGenerationFailureMessage('video', new Error('provider exploded'), { detailed: false }))
      .toBe('生成视频失败，请稍后重试')
    expect(GENERATION_FAILURE_MESSAGES).toEqual({
      image: '生成图片失败，请稍后重试',
      video: '生成视频失败，请稍后重试',
    })
  })

  it('returns job, item, and request details in development or test builds', () => {
    expect(resolveGenerationFailureMessage('image', {
      status: 'failed',
      error: 'image provider timeout',
      items: [],
    }, { detailed: true })).toBe('image provider timeout')

    expect(resolveGenerationFailureMessage('image', {
      status: 'partial_failed',
      error: null,
      items: [{ index: 1, image_type: '首屏主视觉', status: 'failed', error: 'model rejected prompt' }],
    }, { detailed: true })).toBe('首屏主视觉：model rejected prompt')

    expect(resolveGenerationFailureMessage('video', new Error('video worker disconnected'), { detailed: true }))
      .toBe('video worker disconnected')
    expect(resolveGenerationFailureMessage('video', undefined, { detailed: true }))
      .toBe('生成视频失败，请稍后重试')
  })
})
