// 敏感词检测管理 — API 类型与调用封装。
// 后端契约见 backend/app/api/admin.py 的 /admin/sensitive-words* 路由，
// 以及 backend/app/services/sensitive_words.py 的快照与变体生成逻辑。

import { api } from '../../api/client'

export type SensitiveWordVariantPreview = {
  source: string
  boundary: 'word' | 'none'
  variants: string[]
}

export type SensitiveWord = {
  id: string
  term: string
  aliases: string[]
  enabled: boolean
  note: string
  variant_count: number
  variants: string[]
  created_at: string
  updated_at: string
}

export type SensitiveWordSnapshotStatus = {
  schema_version?: string
  enabled?: boolean
  source_digest?: string
  word_count?: number
  variant_count?: number
  payload_bytes?: number
} | null

export type SensitiveWordSnapshotState = {
  redis: SensitiveWordSnapshotStatus
  postgres: SensitiveWordSnapshotStatus
  in_sync: boolean
}

export type SensitiveWordConfig = {
  enabled: boolean
  max_variants_per_word: number
  max_total_variants: number
  max_snapshot_bytes: number
  updated_at: string | null
}

export type SensitiveWordListResponse = {
  config: SensitiveWordConfig
  words: SensitiveWord[]
  snapshot: SensitiveWordSnapshotState
}

export type SensitiveWordPreviewResponse = {
  previews: SensitiveWordVariantPreview[]
  variant_count: number
  max_variants_per_word: number
}

export type SensitiveWordCreatePayload = {
  term: string
  aliases?: string[]
  enabled?: boolean
  note?: string
}

export type SensitiveWordUpdatePayload = {
  term?: string
  aliases?: string[]
  enabled?: boolean
  note?: string
}

export type SensitiveWordSettingsPayload = {
  enabled?: boolean
  max_variants_per_word?: number
  max_total_variants?: number
  max_snapshot_bytes?: number
}

export type SensitiveWordMutationResponse = SensitiveWord & {
  redis_synced?: boolean
  snapshot?: SensitiveWordSnapshotState
}

// 将多行 / 逗号分隔的别名输入解析为数组，去除空项与首尾空白。
export function parseAliasesInput(raw: string): string[] {
  return raw
    .split(/[\n,，]/)
    .map((item) => item.trim())
    .filter((item) => item.length > 0)
}

// 将别名数组拼回多行展示文本。
export function formatAliasesInput(aliases: string[] | undefined): string {
  return (aliases || []).join('\n')
}

// 展示快照状态的简短摘要。
export function snapshotSummary(snapshot: SensitiveWordSnapshotState | null | undefined): string {
  if (!snapshot) return '暂无快照'
  const redis = snapshot.redis
  if (!redis) return 'Redis 不可用'
  if (redis.enabled === false) return '检测已关闭（快照禁用）'
  const digest = redis.source_digest ? redis.source_digest.slice(0, 8) : '—'
  const sync = snapshot.in_sync ? '一致' : 'Redis / PostgreSQL 不一致'
  return `词 ${redis.word_count ?? 0} · 变体 ${redis.variant_count ?? 0} · ${digest} · ${sync}`
}

export async function listSensitiveWords(): Promise<SensitiveWordListResponse> {
  const { data } = await api.get<SensitiveWordListResponse>('/admin/sensitive-words')
  return data
}

export async function previewSensitiveVariants(
  payload: SensitiveWordCreatePayload,
): Promise<SensitiveWordPreviewResponse> {
  const { data } = await api.post<SensitiveWordPreviewResponse>('/admin/sensitive-words/preview', payload)
  return data
}

export async function createSensitiveWord(
  payload: SensitiveWordCreatePayload,
): Promise<SensitiveWordMutationResponse> {
  const { data } = await api.post<SensitiveWordMutationResponse>('/admin/sensitive-words', payload)
  return data
}

export async function updateSensitiveWord(
  id: string,
  payload: SensitiveWordUpdatePayload,
): Promise<SensitiveWordMutationResponse> {
  const { data } = await api.patch<SensitiveWordMutationResponse>(`/admin/sensitive-words/${id}`, payload)
  return data
}

export async function deleteSensitiveWord(id: string): Promise<{ deleted: boolean; redis_synced: boolean; snapshot: SensitiveWordSnapshotState }> {
  const { data } = await api.delete(`/admin/sensitive-words/${id}`)
  return data
}

export async function updateSensitiveSettings(
  payload: SensitiveWordSettingsPayload,
): Promise<SensitiveWordConfig & { redis_synced: boolean; snapshot: SensitiveWordSnapshotState }> {
  const { data } = await api.patch('/admin/sensitive-words/settings', payload)
  return data
}

export async function rebuildSensitiveSnapshot(): Promise<{ redis_synced: boolean; snapshot: SensitiveWordSnapshotState }> {
  const { data } = await api.post('/admin/sensitive-words/snapshot/rebuild')
  return data
}

export type SensitiveWordBulkPayload = {
  terms: string[]
  enabled?: boolean
  note?: string
}

export type SensitiveWordBulkError = {
  term: string
  error: string
}

export type SensitiveWordBulkResponse = {
  created: number
  skipped: number
  total: number
  errors: SensitiveWordBulkError[]
  snapshot?: SensitiveWordSnapshotState
}

export async function bulkCreateSensitiveWords(
  payload: SensitiveWordBulkPayload,
): Promise<SensitiveWordBulkResponse> {
  // 批量导入会在后台重建全量快照，给足超时避免大批量时被默认 20s 客户端超时打断。
  const { data } = await api.post<SensitiveWordBulkResponse>('/admin/sensitive-words/bulk', payload, { timeout: 180_000 })
  return data
}

// 将批量导入文本框内容按换行或逗号（含中文逗号）切分为词列表。
export function splitBulkTerms(raw: string): string[] {
  return raw
    .split(/[\n,，]/)
    .map((item) => item.trim())
    .filter((item) => item.length > 0)
}
