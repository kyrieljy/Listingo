import axios from 'axios'

export const api = axios.create({ baseURL: '/api/v1', timeout: 20_000 })

export type Asset = { id: string; original_name: string; url: string; width: number; height: number }
export type Version = { id: string; parent_version_id: string | null; version_no: number; instruction: string; url: string; created_at: string }
export type JobItem = { id: string; index: number; image_type: string; prompt_text: string; status: string; error: string | null; current_version_id: string | null; versions: Version[] }
export type Job = { id: string; status: string; dry_run: boolean; progress: number; count: number; params: Record<string, unknown>; error: string | null; created_at: string; items: JobItem[] }
export type DownloadFormat = 'zip' | 'long_image'
export type VideoVersion = Version & { remote_url: string }
export type VideoItem = {
  id: string
  index: number
  video_type: string
  status: string
  provider_id: string | null
  provider_task_id: string | null
  error: string | null
  prompt_text: string
  script_markdown: string
  current_version_id: string | null
  versions: VideoVersion[]
}
export type VideoJob = { id: string; status: string; dry_run: boolean; progress: number; count: number; params: Record<string, unknown>; error: string | null; created_at: string; items: VideoItem[] }
export type AplusOutputMode = 'detail' | 'amazon_aplus_standard' | 'amazon_aplus_advanced_web' | 'amazon_aplus_advanced_mobile'
export type AplusOutputTarget = { mode: AplusOutputMode; aspect_ratio: string }
export type AplusItem = {
  id: string
  index: number
  module_index: number
  module_name: string
  output_mode: string
  aspect_ratio: string
  image_prompt: string
  copy_requirements: string
  prompt_text: string
  status: string
  provider_id: string | null
  source_web_item_id: string | null
  error: string | null
  current_version_id: string | null
  versions: Version[]
}
export type AplusJob = {
  id: string
  job_type: string
  status: string
  dry_run: boolean
  progress: number
  count: number
  params: Record<string, unknown>
  source_plan_job_id: string | null
  error: string | null
  created_at: string
  completed_at?: string | null
  items: AplusItem[]
}
export type PromptTestRun = {
  id: string
  prompt_id: string
  prompt_code: string
  test_type: 'llm_output' | 'full_chain'
  status: string
  progress: number
  prompt_content_sha256: string
  input_params: Record<string, unknown>
  raw_output: string
  parsed_output: Record<string, unknown>
  validation_errors: string[]
  related_job_type: string | null
  related_job_id: string | null
  artifact_urls: string[]
  provider_code: string | null
  error: string | null
  created_at: string
  updated_at: string
}

export async function uploadAsset(file: File): Promise<Asset> {
  const form = new FormData()
  form.append('file', file)
  return (await api.post('/assets', form)).data
}

export async function createJob(payload: Record<string, unknown>): Promise<Job> {
  return (await api.post('/generation-jobs', payload)).data
}

export async function getJob(id: string): Promise<Job> {
  return (await api.get(`/generation-jobs/${id}`)).data
}

export async function cancelJob(id: string): Promise<Job> {
  return (await api.post(`/generation-jobs/${id}/cancel`)).data
}

export async function listJobs(): Promise<Job[]> {
  return (await api.get('/generation-jobs')).data
}

export async function assistCopywriting(payload: {
  asset_ids: string[]
  platform: string
  market: string
  language: string
  selling_points: string
  dry_run: boolean
}): Promise<{ selling_points: string; dry_run: boolean; provider_code: string | null }> {
  return (await api.post('/copywriting-assist', payload)).data
}

export async function assistVideoCopywriting(payload: Record<string, unknown>): Promise<{ selling_points: string; dry_run: boolean; provider_code: string | null }> {
  return (await api.post('/video-copywriting-assist', payload)).data
}

export async function createVideoJob(payload: Record<string, unknown>): Promise<VideoJob> {
  return (await api.post('/video-jobs', payload)).data
}

export async function getVideoJob(id: string): Promise<VideoJob> {
  return (await api.get(`/video-jobs/${id}`)).data
}

export async function cancelVideoJob(id: string): Promise<VideoJob> {
  return (await api.post(`/video-jobs/${id}/cancel`)).data
}

export async function listVideoJobs(): Promise<VideoJob[]> {
  return (await api.get('/video-jobs')).data
}

export async function createAplusPlanJob(payload: Record<string, unknown>): Promise<AplusJob> {
  return (await api.post('/aplus-plan-jobs', payload)).data
}

export async function getAplusPlanJob(id: string): Promise<AplusJob> {
  return (await api.get(`/aplus-plan-jobs/${id}`)).data
}

export async function cancelAplusPlanJob(id: string): Promise<AplusJob> {
  return (await api.post(`/aplus-plan-jobs/${id}/cancel`)).data
}

export async function createAplusGenerationJob(payload: Record<string, unknown>): Promise<AplusJob> {
  return (await api.post('/aplus-generation-jobs', payload)).data
}

export async function getAplusGenerationJob(id: string): Promise<AplusJob> {
  return (await api.get(`/aplus-generation-jobs/${id}`)).data
}

export async function cancelAplusGenerationJob(id: string): Promise<AplusJob> {
  return (await api.post(`/aplus-generation-jobs/${id}/cancel`)).data
}

export async function listAplusGenerationJobs(): Promise<AplusJob[]> {
  return (await api.get('/aplus-generation-jobs')).data
}

export async function createPromptTestRun(promptId: string, payload: Record<string, unknown>): Promise<PromptTestRun> {
  return (await api.post(`/admin/prompts/${promptId}/test-runs`, payload)).data
}

export async function getPromptTestRun(id: string): Promise<PromptTestRun> {
  return (await api.get(`/admin/prompt-test-runs/${id}`)).data
}

export async function listPromptTestRuns(promptId: string): Promise<PromptTestRun[]> {
  return (await api.get(`/admin/prompts/${promptId}/test-runs`)).data
}

export async function retryFailedVideoItems(jobId: string): Promise<VideoJob> {
  return (await api.post(`/video-jobs/${jobId}/retry-failed`)).data
}

export async function editItem(id: string, instruction: string): Promise<Version> {
  return (await api.post(`/generation-items/${id}/versions`, { instruction })).data
}

export async function editAplusItem(id: string, instruction: string): Promise<Version> {
  return (await api.post(`/aplus-items/${id}/versions`, { instruction })).data
}

export async function retryFailedItems(jobId: string): Promise<Job> {
  return (await api.post(`/generation-jobs/${jobId}/retry-failed`)).data
}

export function generationDownloadUrl(jobId: string, itemIds: string[], format: DownloadFormat = 'zip'): string {
  const params = new URLSearchParams({ item_ids: itemIds.join(','), format })
  return `/api/v1/generation-jobs/${jobId}/download?${params.toString()}`
}

export function videoDownloadUrl(jobId: string, itemIds: string[]): string {
  const params = new URLSearchParams({ item_ids: itemIds.join(',') })
  return `/api/v1/video-jobs/${jobId}/download?${params.toString()}`
}

export function aplusDownloadUrl(jobId: string, itemIds: string[]): string {
  const params = new URLSearchParams({ item_ids: itemIds.join(',') })
  return `/api/v1/aplus-generation-jobs/${jobId}/download?${params.toString()}`
}
