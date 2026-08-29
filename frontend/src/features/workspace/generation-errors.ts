/// <reference types="vite/client" />
import { userFacingApiErrorMessage } from '../../api/client'
import { generationFailureMessage, type GenerationFailureLike } from './workspace-model'

export type GenerationErrorKind = 'image' | 'video'

export const GENERATION_FAILURE_MESSAGES: Record<GenerationErrorKind, string> = {
  image: '生成图片失败，请稍后重试',
  video: '生成视频失败，请稍后重试',
}

// Detailed diagnostics must stay impossible to enable in a production bundle.
const detailedGenerationErrorsEnabled = import.meta.env.MODE !== 'production'
  && (
    import.meta.env.DEV
    || import.meta.env.MODE === 'test'
    || import.meta.env.VITE_SHOW_DETAILED_GENERATION_ERRORS === 'true'
  )

export function resolveGenerationFailureMessage(
  kind: GenerationErrorKind,
  source: unknown,
  options: { detailed: boolean },
): string {
  const fallback = GENERATION_FAILURE_MESSAGES[kind]
  if (!options.detailed) return fallback

  const jobDetail = generationFailureMessage(source as GenerationFailureLike)
  const requestDetail = source == null ? '' : userFacingApiErrorMessage(source)
  return jobDetail || requestDetail || fallback
}

export function generationFailureMessageFor(kind: GenerationErrorKind, source: unknown): string {
  return resolveGenerationFailureMessage(kind, source, { detailed: detailedGenerationErrorsEnabled })
}
