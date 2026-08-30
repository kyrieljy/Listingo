<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import { message } from 'ant-design-vue'
import { userFacingApiErrorMessage } from '../../api/client'
import {
  bulkCreateSensitiveWords,
  createSensitiveWord,
  deleteSensitiveWord,
  formatAliasesInput,
  listSensitiveWords,
  parseAliasesInput,
  previewSensitiveVariants,
  rebuildSensitiveSnapshot,
  snapshotSummary,
  splitBulkTerms,
  updateSensitiveSettings,
  updateSensitiveWord,
  type SensitiveWord,
  type SensitiveWordConfig,
  type SensitiveWordListResponse,
  type SensitiveWordPreviewResponse,
} from './sensitive-words-model'

const loading = ref(false)
const saving = ref(false)
const data = ref<SensitiveWordListResponse | null>(null)
const config = ref<SensitiveWordConfig | null>(null)

// 编辑表单状态
const editingId = ref<string | null>(null)
const formTerm = ref('')
const formAliases = ref('')
const formEnabled = ref(true)
const formNote = ref('')
const formError = ref<string | null>(null)

// 实时变体预览
const preview = ref<SensitiveWordPreviewResponse | null>(null)
const previewDebounce = ref<number | null>(null)
const previewWarning = ref<string | null>(null)

const searchTerm = ref('')
const filteredWords = computed(() => {
  const q = searchTerm.value.trim().toLowerCase()
  const words = data.value?.words ?? []
  if (!q) return words
  return words.filter(
    (w) =>
      w.term.toLowerCase().includes(q) ||
      w.aliases.some((a) => a.toLowerCase().includes(q)) ||
      w.variants.some((v) => v.toLowerCase().includes(q))
  )
})
const limitsText = computed(() => {
  if (!config.value) return ''
  const mb = (config.value.max_snapshot_bytes / (1024 * 1024)).toFixed(1)
  return `单词上限 ${config.value.max_variants_per_word} 变体 · 全量上限 ${config.value.max_total_variants} 变体 · 快照上限 ${mb} MB`
})

async function load() {
  loading.value = true
  try {
    data.value = await listSensitiveWords()
    config.value = data.value.config
  } catch (error: unknown) {
    message.error(userFacingApiErrorMessage(error, '敏感词配置加载失败'))
  } finally {
    loading.value = false
  }
}

function resetForm() {
  editingId.value = null
  formTerm.value = ''
  formAliases.value = ''
  formEnabled.value = true
  formNote.value = ''
  formError.value = null
  preview.value = null
  previewWarning.value = null
}

function startCreate() {
  resetForm()
}

function startEdit(word: SensitiveWord) {
  editingId.value = word.id
  formTerm.value = word.term
  formAliases.value = formatAliasesInput(word.aliases)
  formEnabled.value = word.enabled
  formNote.value = word.note
  formError.value = null
  previewWarning.value = null
  preview.value = null
}

function requestPreview() {
  if (previewDebounce.value !== null) {
    window.clearTimeout(previewDebounce.value)
  }
  previewDebounce.value = window.setTimeout(async () => {
    const term = formTerm.value.trim()
    if (!term) {
      preview.value = null
      previewWarning.value = null
      return
    }
    try {
      preview.value = await previewSensitiveVariants({
        term,
        aliases: parseAliasesInput(formAliases.value),
      })
      previewWarning.value = null
    } catch (error: unknown) {
      preview.value = null
      previewWarning.value = userFacingApiErrorMessage(error, '变体预览失败')
    }
  }, 300)
}

async function submitForm() {
  const term = formTerm.value.trim()
  if (!term) {
    formError.value = '敏感词不能为空'
    return
  }
  const aliases = parseAliasesInput(formAliases.value)
  saving.value = true
  formError.value = null
  try {
    if (editingId.value) {
      await updateSensitiveWord(editingId.value, { term, aliases, enabled: formEnabled.value, note: formNote.value })
      message.success('敏感词已更新')
    } else {
      await createSensitiveWord({ term, aliases, enabled: formEnabled.value, note: formNote.value })
      message.success('敏感词已新增，快照已同步')
    }
    resetForm()
    await load()
  } catch (error: unknown) {
    formError.value = userFacingApiErrorMessage(error, '保存失败')
  } finally {
    saving.value = false
  }
}

async function toggleWord(word: SensitiveWord) {
  try {
    await updateSensitiveWord(word.id, { enabled: !word.enabled })
    message.success(!word.enabled ? '已启用' : '已停用')
    await load()
  } catch (error: unknown) {
    message.error(userFacingApiErrorMessage(error, '状态切换失败'))
  }
}

async function removeWord(word: SensitiveWord) {
  try {
    await deleteSensitiveWord(word.id)
    message.success('已删除并重建快照')
    await load()
  } catch (error: unknown) {
    message.error(userFacingApiErrorMessage(error, '删除失败'))
  }
}

async function toggleGlobalEnabled(next: boolean) {
  if (!config.value) return
  try {
    await updateSensitiveSettings({ enabled: next })
    message.success(next ? '敏感信息检测已开启' : '敏感信息检测已关闭')
    await load()
  } catch (error: unknown) {
    message.error(userFacingApiErrorMessage(error, '开关更新失败'))
  }
}

async function rebuild() {
  try {
    await rebuildSensitiveSnapshot()
    message.success('快照已从 PostgreSQL 重建并同步 Redis')
    await load()
  } catch (error: unknown) {
    message.error(userFacingApiErrorMessage(error, '快照重建失败'))
  }
}

// 批量导入
const batchInput = ref('')
const batchEnabled = ref(true)
const batchNote = ref('')
const batchImporting = ref(false)
const batchResult = ref<string | null>(null)
const batchPreviewCount = computed(() => splitBulkTerms(batchInput.value).length)

async function submitBatch() {
  const terms = splitBulkTerms(batchInput.value)
  if (terms.length === 0) {
    batchResult.value = '没有可导入的词，请用换行或逗号分隔后粘贴。'
    return
  }
  if (terms.length > 2000) {
    batchResult.value = `单次最多导入 2000 个，当前 ${terms.length} 个，请分批导入。`
    return
  }
  batchImporting.value = true
  batchResult.value = null
  try {
    const res = await bulkCreateSensitiveWords({
      terms,
      enabled: batchEnabled.value,
      note: batchNote.value.trim(),
    })
    message.success(`成功导入 ${res.created} 个，跳过重复 ${res.skipped} 个`)
    if (res.errors.length) {
      batchResult.value = `已完成：新增 ${res.created} · 跳过重复 ${res.skipped} · 无效/超长 ${res.errors.length} 个`
    } else {
      batchResult.value = `已完成：新增 ${res.created} · 跳过重复 ${res.skipped}`
    }
    batchInput.value = ''
    batchNote.value = ''
    await load()
  } catch (error: unknown) {
    batchResult.value = userFacingApiErrorMessage(error, '批量导入失败')
  } finally {
    batchImporting.value = false
  }
}

onMounted(load)
</script>

<template>
  <section class="sensitive-panel">
    <header class="sensitive-head">
      <div>
        <h2>敏感词检测</h2>
        <p>运营可维护敏感词清单并开关检测；用户端在任务进入生成队列前检测卖点文本与上传图片 OCR 文本。</p>
      </div>
      <label class="sensitive-switch">
        <input type="checkbox" :checked="config?.enabled ?? false" @change="toggleGlobalEnabled(($event.target as HTMLInputElement).checked)" />
        <span>{{ config?.enabled ? '检测已开启' : '检测已关闭' }}</span>
      </label>
    </header>

    <p v-if="config" class="sensitive-limits">{{ limitsText }}</p>

    <article class="sensitive-batch">
      <div class="batch-head">
        <h3>批量导入</h3>
        <span class="batch-count">待导入 {{ batchPreviewCount }} 个</span>
      </div>
      <p class="batch-hint">将大量敏感词粘贴到下方文本框，按换行或逗号（含中文逗号）自动切分，单次最多 2000 个。已存在的词会被跳过。</p>
      <textarea
        v-model="batchInput"
        class="batch-input"
        rows="5"
        placeholder="例如：&#10;套图&#10;暴力,违禁&#10;政治相关"
      />
      <div class="batch-options">
        <label class="sensitive-switch inline">
          <input v-model="batchEnabled" type="checkbox" />
          <span>导入后启用</span>
        </label>
        <label class="field batch-note">
          <span>备注（可选，统一应用到本批）</span>
          <input v-model="batchNote" type="text" maxlength="500" placeholder="可选" />
        </label>
      </div>
      <p v-if="batchResult" class="batch-result">{{ batchResult }}</p>
      <footer class="editor-actions">
        <button class="admin-primary" :disabled="batchImporting || batchPreviewCount === 0" @click="submitBatch">
          {{ batchImporting ? '导入中...' : '批量导入' }}
        </button>
        <button class="admin-soft-button" :disabled="batchImporting" @click="batchInput = ''; batchResult = null">清空</button>
      </footer>
    </article>

    <div class="sensitive-body">
      <article class="sensitive-editor">
        <h3>{{ editingId ? '编辑敏感词' : '新增敏感词' }}</h3>
        <label class="field">
          <span>敏感词</span>
          <input v-model="formTerm" type="text" maxlength="120" placeholder="例如：套图" @input="requestPreview" />
        </label>
        <label class="field">
          <span>人工别名（每行或逗号分隔，最多 20 个）</span>
          <textarea v-model="formAliases" rows="3" placeholder="tao圖" @input="requestPreview" />
        </label>
        <label class="field">
          <span>备注</span>
          <input v-model="formNote" type="text" maxlength="500" placeholder="可选" />
        </label>
        <label class="sensitive-switch inline">
          <input v-model="formEnabled" type="checkbox" />
          <span>启用该词</span>
        </label>

        <div v-if="preview" class="preview-box">
          <div class="preview-title">
            实时变体预览（{{ preview.variant_count }} / 上限 {{ preview.max_variants_per_word }}）
          </div>
          <div v-for="item in preview.previews" :key="item.source" class="preview-item">
            <code class="preview-source">{{ item.source }}</code>
            <span class="preview-boundary">{{ item.boundary === 'word' ? '词边界' : '宽松' }}</span>
            <div class="preview-variants">
              <span v-for="variant in item.variants" :key="variant" class="variant-chip">{{ variant }}</span>
            </div>
          </div>
        </div>
        <p v-if="previewWarning" class="preview-warning">{{ previewWarning }}</p>

        <p v-if="formError" class="form-error">{{ formError }}</p>

        <footer class="editor-actions">
          <button class="admin-primary" :disabled="saving" @click="submitForm">{{ saving ? '保存中...' : (editingId ? '保存修改' : '新增敏感词') }}</button>
          <button v-if="editingId" class="admin-soft-button" @click="resetForm">取消</button>
          <button v-else class="admin-soft-button" @click="resetForm">清空</button>
        </footer>
      </article>

      <article class="sensitive-list">
          <div class="list-head">
            <h3>敏感词清单（{{ filteredWords.length }}）</h3>
            <button class="admin-text-button" :disabled="loading" @click="rebuild">重建快照</button>
          </div>

          <div v-if="data?.snapshot" class="snapshot-state">
            快照状态：{{ snapshotSummary(data.snapshot) }}
          </div>

          <div class="sensitive-search">
            <input v-model="searchTerm" type="text" class="search-input" placeholder="搜索敏感词、别名或变体…" />
            <button v-if="searchTerm" class="search-clear" type="button" aria-label="清除搜索" @click="searchTerm = ''">×</button>
          </div>

          <table class="sensitive-table">
          <thead>
            <tr>
              <th>敏感词</th>
              <th>别名</th>
              <th>变体</th>
              <th>状态</th>
              <th>操作</th>
            </tr>
          </thead>
          <tbody>
            <tr v-for="word in filteredWords" :key="word.id">
              <td>{{ word.term }}</td>
              <td class="aliases">{{ word.aliases.length ? word.aliases.join('、') : '—' }}</td>
              <td class="variants-cell">
                <div v-if="word.variants.length" class="variant-chips">
                  <span v-for="variant in word.variants" :key="variant" class="variant-chip">{{ variant }}</span>
                </div>
                <span v-else class="muted-dash">—</span>
              </td>
              <td class="status-cell">
                <button class="toggle" :class="{ on: word.enabled }" :aria-label="word.enabled ? '已启用' : '已停用'" @click="toggleWord(word)">
                  <span class="knob"></span>
                </button>
              </td>
              <td class="row-actions">
                <button class="admin-text-button" @click="startEdit(word)">编辑</button>
                <button class="admin-text-button danger" @click="removeWord(word)">删除</button>
              </td>
            </tr>
            <tr v-if="!filteredWords.length">
              <td colspan="5" class="empty">{{ searchTerm ? '没有匹配的敏感词' : '尚未配置任何敏感词' }}</td>
            </tr>
          </tbody>
        </table>
      </article>
    </div>
  </section>
</template>

<style scoped>
.sensitive-panel { max-width: 1080px; }
.sensitive-head { display: flex; align-items: flex-start; justify-content: space-between; gap: 16px; }
.sensitive-head h2 { margin: 0 0 4px; }
.sensitive-head p { margin: 0; color: #596170; font-size: 13px; max-width: 640px; }
.sensitive-switch { display: inline-flex; align-items: center; gap: 8px; font-weight: 600; }
.sensitive-switch.inline { margin: 4px 0 2px; color: #343a46; font-weight: 500; }
.sensitive-limits { color: #596170; font-size: 12px; margin: 8px 0 18px; }
.sensitive-body { display: grid; grid-template-columns: minmax(300px, 340px) 1fr; gap: 24px; align-items: start; }
.sensitive-batch { border: 1px solid #e7e9f0; border-radius: 10px; padding: 16px; background: #fff; margin-bottom: 22px; }
.sensitive-batch h3 { margin: 0 0 6px; }
.batch-head { display: flex; align-items: baseline; justify-content: space-between; }
.batch-count { font-size: 12px; color: #7a8194; }
.batch-hint { color: #596170; font-size: 12px; margin: 0 0 10px; }
.batch-input { width: 100%; border: 1px solid #dfe3ea; border-radius: 8px; padding: 10px 12px; font-size: 13px; font-family: inherit; resize: vertical; line-height: 1.6; }
.batch-input:focus { outline: none; border-color: #b9c0d0; }
.batch-options { display: flex; flex-wrap: wrap; align-items: flex-end; gap: 22px; margin: 12px 0 4px; }
.batch-note { margin-bottom: 0; flex: 1 1 260px; }
.batch-note input { width: 100%; border: 1px solid #dfe3ea; border-radius: 8px; padding: 9px 11px; font-size: 13px; font-family: inherit; }
.batch-result { font-size: 12px; color: #1f8a4c; margin: 10px 0 0; }
.sensitive-editor, .sensitive-list { border: 1px solid #e7e9f0; border-radius: 10px; padding: 16px; background: #fff; }
.sensitive-editor h3, .sensitive-list h3 { margin: 0 0 12px; }
.field { display: grid; gap: 6px; margin-bottom: 12px; color: #343a46; font-size: 13px; }
.field input, .field textarea { border: 1px solid #dfe3ea; border-radius: 8px; padding: 9px 11px; font-size: 13px; font-family: inherit; }
.field textarea { resize: vertical; }
.preview-box { border: 1px dashed #d3d8e3; border-radius: 8px; padding: 10px; background: #fafbff; margin-top: 6px; }
.preview-title { font-size: 12px; color: #596170; margin-bottom: 8px; }
.preview-item { display: grid; grid-template-columns: 120px 56px 1fr; gap: 8px; align-items: center; margin-bottom: 8px; }
.preview-source { background: #eef0f6; border-radius: 6px; padding: 3px 6px; font-size: 12px; }
.preview-boundary { font-size: 11px; color: #7a8194; }
.preview-variants { display: flex; flex-wrap: wrap; gap: 5px; }
.variant-chip { border: 1px solid #e2e6ef; border-radius: 999px; padding: 2px 9px; font-size: 12px; background: #fff; }
.preview-warning, .form-error { color: #c0392b; font-size: 12px; margin: 6px 0 0; }
.editor-actions { display: flex; gap: 10px; margin-top: 10px; }
.list-head { display: flex; align-items: center; justify-content: space-between; }
.sensitive-search { position: relative; margin-bottom: 12px; }
.search-input { width: 100%; border: 1px solid #dfe3ea; border-radius: 8px; padding: 9px 32px 9px 12px; font-size: 13px; font-family: inherit; }
.search-input:focus { outline: none; border-color: #b9c0d0; }
.search-clear { position: absolute; right: 8px; top: 50%; transform: translateY(-50%); border: 0; background: transparent; color: #9aa1b1; font-size: 18px; line-height: 1; cursor: pointer; padding: 0 4px; }
.search-clear:hover { color: #596170; }
.snapshot-state { font-size: 12px; color: #596170; border: 1px solid #eef0f6; border-radius: 8px; padding: 8px 10px; margin-bottom: 12px; background: #fafbff; }
.sensitive-table { width: 100%; border-collapse: collapse; font-size: 13px; }
.sensitive-table th, .sensitive-table td { text-align: left; padding: 10px 12px; vertical-align: top; border-bottom: 1px solid #eef0f6; }
.sensitive-table th { color: #7a8194; font-weight: 600; }
.sensitive-table .aliases { color: #596170; word-break: break-word; }
.variants-cell { word-break: break-word; }
.variant-chips { display: flex; flex-wrap: wrap; gap: 5px; }
.variant-chips .variant-chip { border: 1px solid #e2e6ef; border-radius: 999px; padding: 2px 9px; font-size: 12px; background: #fff; white-space: nowrap; }
.muted-dash { color: #9aa1b1; }
.row-actions { display: flex; gap: 8px; flex-wrap: wrap; }
.status-cell { white-space: nowrap; }
.toggle { position: relative; box-sizing: border-box; width: 44px; height: 24px; border-radius: 999px; border: 1px solid #cfd4de; background: #e6e8ee; cursor: pointer; padding: 0; transition: background .15s, border-color .15s; }
.toggle.on { background: #1f8a4c; border-color: #1f8a4c; }
.toggle .knob { position: absolute; top: 2px; left: 2px; width: 18px; height: 18px; border-radius: 50%; background: #fff; box-shadow: 0 1px 2px rgba(0, 0, 0, 0.2); transition: left .15s; }
.toggle.on .knob { left: 22px; }
.empty { text-align: center; color: #9aa1b1; padding: 18px 0; }
.admin-text-button.danger { color: #c0392b; }
.admin-primary { height: 38px; border: 0 !important; background: #171a22 !important; color: #fff !important; border-radius: 8px; padding: 0 16px; cursor: pointer; }
.admin-soft-button { height: 34px; padding: 0 14px; border: 1px solid #dfe3ea !important; background: #fff !important; color: #202631 !important; border-radius: 8px; cursor: pointer; }
</style>
