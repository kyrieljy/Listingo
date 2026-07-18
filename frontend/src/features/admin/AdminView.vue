<script setup lang="ts">
import { computed, onMounted, ref, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { message } from 'ant-design-vue'
import { Background } from '@vue-flow/background'
import { Controls } from '@vue-flow/controls'
import { VueFlow } from '@vue-flow/core'
import '@vue-flow/core/dist/style.css'
import '@vue-flow/core/dist/theme-default.css'
import {
  ApiOutlined, ArrowLeftOutlined, BranchesOutlined, CheckCircleFilled, CodeOutlined,
  FileTextOutlined, PlayCircleOutlined, SaveOutlined, SettingOutlined, UploadOutlined,
} from '@ant-design/icons-vue'
import BrandLogo from '../../components/BrandLogo.vue'
import { api } from '../../api/client'
import { groupProvidersByBusinessRoute, providerRuntimeState, type ProviderDisplayRecord } from './provider-display'

type Provider = ProviderDisplayRecord
const route=useRoute(); const router=useRouter(); const section=computed(()=>String(route.params.section||'providers'))
const providers=ref<Provider[]>([]); const selectedProvider=ref<Provider|null>(null); const providerOpen=ref(false); const apiKey=ref('')
const prompts=ref<any[]>([]); const promptDetail=ref<any>(null); const promptContent=ref(''); const promptNote=ref('')
const workflows=ref<any[]>([]); const workflowDetail=ref<any>(null); const nodes=ref<any[]>([]); const edges=ref<any[]>([])
const logs=ref<any[]>([]); const logTotal=ref(0); const loading=ref(false)
const runtimeSettings=ref({ public_asset_base_url: '', public_asset_base_url_configured: false })
const nav=[{key:'providers',label:'模型配置',icon:ApiOutlined},{key:'workflow',label:'Workflow',icon:BranchesOutlined},{key:'prompts',label:'提示词资产',icon:CodeOutlined},{key:'logs',label:'执行日志',icon:FileTextOutlined},{key:'settings',label:'基础配置',icon:SettingOutlined}]
const sectionTitle=computed(()=>nav.find((item)=>item.key===section.value)?.label||'运营后台')
const providerGroups=computed(()=>groupProvidersByBusinessRoute(providers.value))

onMounted(loadSection); watch(section,loadSection)
async function loadSection(){ loading.value=true; try{ if(section.value==='providers')providers.value=(await api.get('/admin/providers')).data; if(section.value==='prompts'){prompts.value=(await api.get('/admin/prompts')).data;if(prompts.value[0])await loadPrompt(prompts.value[0].id)} if(section.value==='workflow'){workflows.value=(await api.get('/admin/workflows')).data;if(workflows.value[0])await loadWorkflow(workflows.value[0].id)} if(section.value==='logs'){const data=(await api.get('/admin/logs')).data;logs.value=data.items;logTotal.value=data.total} if(section.value==='settings')runtimeSettings.value=(await api.get('/admin/runtime-settings')).data }catch{message.error('后台数据加载失败，请确认 API 已启动')}finally{loading.value=false}}
function go(key:string){router.push(`/admin/${key}`)}
function editProvider(provider:Provider){selectedProvider.value=JSON.parse(JSON.stringify(provider));apiKey.value='';providerOpen.value=true}
async function saveProvider(){if(!selectedProvider.value)return;const p=selectedProvider.value;await api.patch(`/admin/providers/${p.id}`,{label:p.label,base_url:p.base_url,model_name:p.model_name,enabled:p.enabled,is_default:p.is_default,is_fallback:p.is_fallback,api_key:apiKey.value||undefined,resolution:p.config.resolution,size:p.config.size,quality:p.config.quality,format:p.config.format,compression:p.config.compression,timeout_seconds:p.config.timeout_seconds});providerOpen.value=false;await loadSection();message.success('模型配置已保存')}
async function testProvider(provider:Provider){message.loading({content:`正在测试 ${provider.label}`,key:'provider-test'});try{const result=(await api.post(`/admin/providers/${provider.id}/test`)).data;message[result.ok?'success':'error']({content:result.message,key:'provider-test'})}catch(error:any){message.error({content:error.response?.data?.detail||'连通测试失败',key:'provider-test'})}}
async function toggleProvider(provider:Provider){await api.patch(`/admin/providers/${provider.id}`,{enabled:!provider.enabled});await loadSection()}
function providerResolutions(provider:Provider):string[]{return Array.isArray(provider.config.allowed_resolutions)?provider.config.allowed_resolutions as string[]:['1K','2K','4K']}
function providerImage2Sizes(provider:Provider):string[]{return Array.isArray(provider.config.allowed_sizes)?(provider.config.allowed_sizes as string[]).filter((value)=>value!=='follow_ratio'):['auto','1024x1024','1536x1024','1024x1536','2048x2048','2048x1152','3840x2160','2160x3840']}
async function loadPrompt(id:string){promptDetail.value=(await api.get(`/admin/prompts/${id}`)).data;promptContent.value=promptDetail.value.active_version.content;promptNote.value=''}
async function savePrompt(){const version=(await api.post(`/admin/prompts/${promptDetail.value.id}/versions`,{content:promptContent.value,change_note:promptNote.value||'后台保存新版本'})).data;await api.post(`/admin/prompts/${promptDetail.value.id}/versions/${version.id}/activate`);await loadPrompt(promptDetail.value.id);message.success('提示词新版本已保存并启用')}
async function uploadPromptFile(event:Event){const input=event.target as HTMLInputElement;const file=input.files?.[0];if(!file||!promptDetail.value)return;const body=new FormData();body.append('file',file);body.append('change_note',promptNote.value||`上传文件：${file.name}`);try{await api.post(`/admin/prompts/${promptDetail.value.id}/versions/upload`,body);await loadPrompt(promptDetail.value.id);message.success('提示词文件已上传为新版本，请在版本历史中选择启用')}catch(error:any){message.error(error.response?.data?.detail||'提示词文件上传失败')}finally{input.value=''}}
async function activatePrompt(version:any){await api.post(`/admin/prompts/${promptDetail.value.id}/versions/${version.id}/activate`);await loadPrompt(promptDetail.value.id);message.success(`已启用提示词 v${version.version_no}，后续 Live 任务将引用此版本`)}
async function loadWorkflow(id:string){workflowDetail.value=(await api.get(`/admin/workflows/${id}`)).data;const active=workflowDetail.value.versions.find((item:any)=>item.id===workflowDetail.value.active_version_id)||workflowDetail.value.versions[0];nodes.value=active.graph.nodes;edges.value=active.graph.edges}
async function dryrunWorkflow(){const active=workflowDetail.value.versions.find((item:any)=>item.id===workflowDetail.value.active_version_id);const result=(await api.post(`/admin/workflows/${workflowDetail.value.id}/versions/${active.id}/dryrun`)).data;message[result.ok?'success':'error'](result.ok?'Workflow Dryrun 校验通过':result.errors.join('；'))}
async function saveWorkflow(){const graph={schema_version:'1.0',viewport:{x:30,y:90,zoom:.9},nodes:nodes.value,edges:edges.value};const version=(await api.post(`/admin/workflows/${workflowDetail.value.id}/versions`,{graph,change_note:'画布编辑保存'})).data;if(!version.validation_errors.length)await api.post(`/admin/workflows/${workflowDetail.value.id}/versions/${version.id}/activate`);await loadWorkflow(workflowDetail.value.id);message.success(version.validation_errors.length?'已保存草稿，存在校验错误':'新版本已保存并启用')}
async function saveRuntimeSettings(){runtimeSettings.value=(await api.patch('/admin/runtime-settings',{public_asset_base_url:runtimeSettings.value.public_asset_base_url})).data;message.success('基础配置已保存到当前运行实例')}
</script>

<template>
  <div class="admin-shell">
    <header class="admin-top"><BrandLogo/><span class="admin-divider"/> <strong>运营后台</strong><div/><button @click="router.push('/app/suite')"><ArrowLeftOutlined/>返回工作台</button></header>
    <aside class="admin-nav"><p>配置中心</p><button v-for="item in nav" :key="item.key" :class="{active:section===item.key}" @click="go(item.key)"><component :is="item.icon"/>{{ item.label }}</button><div class="admin-safe"><CheckCircleFilled/><span><b>Dryrun 已开启</b><small>外部调用默认关闭</small></span></div></aside>
    <main class="admin-main"><div class="admin-title"><div><h1>{{ sectionTitle }}</h1><p>{{ section==='providers'?'统一配置 LLM 与图片模型，密钥加密保存':section==='workflow'?'低代码节点画布、版本与启用校验':section==='prompts'?'唯一来源为用户上传 MD；Artflo 提示词不参与执行':'按任务、节点、模型与状态追踪执行链路' }}</p></div><span v-if="loading">加载中…</span></div>
      <section v-if="section==='providers'" class="provider-page">
        <div class="provider-activation-note"><CheckCircleFilled/><div><b>Provider 生效条件</b><p>启用开关只是允许调用；还必须配置 API Key，模型才会显示“当前生效”。Live 任务只会调用下方业务分组中已生效的模型。</p><ul class="provider-state-legend"><li class="ready">当前生效：启用且密钥已配置</li><li class="warning">缺少密钥：已启用但无法调用</li><li class="off">未启用：不会进入 Live 链路</li></ul></div></div>
        <section v-for="group in providerGroups" :key="group.key" class="provider-group" :class="`provider-group-${group.key}`">
          <header class="provider-group-head"><div><span>{{ group.key==='prompt'?'01':group.key==='fidelity'?'02':'03' }}</span><div><h2>{{ group.title }}</h2><p>{{ group.description }}</p></div></div><aside><small>实际调用顺序</small><b>{{ group.route }}</b><em :class="{ready:group.ready}">{{ group.statusLabel }}</em></aside></header>
          <div class="provider-grid"><article v-for="provider in group.providers" :key="provider.id" class="provider-card" :class="`runtime-${providerRuntimeState(provider).tone}`">
            <div class="provider-head"><span><ApiOutlined/></span><div><h3>{{ provider.label }}</h3><p>{{ provider.model_name }}</p></div><button class="toggle" :class="{on:provider.enabled}" :aria-label="`${provider.enabled?'停用':'启用'} ${provider.label}`" :title="provider.enabled?'点击停用 Provider':'点击启用 Provider'" @click="toggleProvider(provider)"/></div>
            <div class="provider-runtime" :class="providerRuntimeState(provider).tone"><i/><span><b>{{ providerRuntimeState(provider).label }}</b><small>{{ providerRuntimeState(provider).detail }}</small></span></div>
            <div class="provider-badges"><em class="business-role">{{ provider.role }}</em><em>{{ provider.capability==='llm'?'语言模型':provider.capability==='video'?'视频模型':'图片模型' }}</em><em :class="provider.has_api_key?'key-ok':'key-empty'">{{ provider.has_api_key?'密钥已配置':'无密钥' }}</em></div>
            <dl><div><dt>端点</dt><dd>{{ provider.base_url }}</dd></div><div><dt>适配器</dt><dd>{{ provider.adapter }}</dd></div><div><dt>默认参数</dt><dd>{{ provider.config.resolution||provider.config.size||'JSON' }} · {{ provider.config.timeout_seconds }}s</dd></div></dl>
            <footer><button @click="testProvider(provider)"><PlayCircleOutlined/>连通测试</button><button class="edit" @click="editProvider(provider)"><SettingOutlined/>配置</button></footer>
          </article></div>
        </section>
      </section>
      <section v-else-if="section==='workflow'" class="workflow-layout"><div class="workflow-toolbar"><div><span class="active-dot"/>已启用 v{{ workflowDetail?.versions?.find((v:any)=>v.id===workflowDetail.active_version_id)?.version_no }} · 固定执行器</div><button @click="dryrunWorkflow"><PlayCircleOutlined/>Dryrun</button><button class="admin-primary" @click="saveWorkflow"><SaveOutlined/>保存新版本</button></div><div class="flow-canvas"><VueFlow v-model:nodes="nodes" v-model:edges="edges" fit-view-on-init><Background pattern-color="#dad7ea" :gap="22"/><Controls/></VueFlow></div><aside class="flow-inspector"><h3>节点属性</h3><p>版本保存、连线校验和任务版本引用会生效；当前运行顺序仍由后端固定执行器控制，移动或修改画布不会动态改写执行代码。</p><div v-for="node in nodes" :key="node.id"><span>{{ node.type }}</span><b>{{ node.data?.label }}</b></div><h3>版本历史</h3><button v-for="version in workflowDetail?.versions" :key="version.id" @click="nodes=version.graph.nodes;edges=version.graph.edges"><b>v{{ version.version_no }}</b><small>{{ version.change_note }}</small></button></aside></section>
      <section v-else-if="section==='prompts'" class="prompt-layout"><aside><h3>提示词资产</h3><button v-for="prompt in prompts" :key="prompt.id" :class="{active:prompt.id===promptDetail?.id}" @click="loadPrompt(prompt.id)"><CodeOutlined/><span><b>{{ prompt.name }}</b><small>{{ prompt.code }} · {{ prompt.version_count }} 个版本</small></span></button><label class="prompt-upload"><UploadOutlined/>上传到当前提示词<input type="file" accept=".md,.txt,text/markdown,text/plain" @change="uploadPromptFile"/></label><div class="source-lock"><CheckCircleFilled/><p><b>Live Prompt 工程</b><br/>套图规划、商品识别、AI 帮写与二次编辑均引用各自当前启用版本。Artflo 不参与执行。</p></div></aside><div class="prompt-editor"><header><div><strong>{{ promptDetail?.name }}</strong><span>{{ promptDetail?.description }} · 当前启用 v{{ promptDetail?.versions?.find((v:any)=>v.id===promptDetail.active_version_id)?.version_no }}</span></div><button class="admin-primary" @click="savePrompt"><SaveOutlined/>保存并启用新版本</button></header><textarea v-model="promptContent" spellcheck="false"/><footer><input v-model="promptNote" placeholder="版本说明（可选）"/><span>Live 任务会锁定当前启用版本；Dryrun 仅记录版本并走本地确定性状态机。</span></footer></div><aside class="version-panel"><h3>版本历史</h3><article v-for="version in promptDetail?.versions" :key="version.id" :class="{active:version.id===promptDetail.active_version_id}"><button @click="promptContent=version.content"><b>v{{ version.version_no }}<i v-if="version.id===promptDetail.active_version_id">当前生效</i></b><small>{{ version.change_note }}</small><em>{{ version.content_sha256.slice(0,10) }}…</em></button><button v-if="version.id!==promptDetail.active_version_id" class="activate-version" @click="activatePrompt(version)">启用此版本</button></article></aside></section>
      <section v-else-if="section==='logs'" class="logs-card"><div class="log-filters"><select><option>全部节点</option><option>image_generate</option><option>meta_prompt</option><option>video_meta_prompt</option><option>video_submit</option><option>video_generate</option></select><select><option>全部状态</option><option>succeeded</option><option>failed</option></select><span>共 {{ logTotal }} 条</span></div><table><thead><tr><th>时间</th><th>任务 / 节点</th><th>状态</th><th>耗时</th><th>请求摘要</th><th>错误</th></tr></thead><tbody><tr v-for="log in logs" :key="log.id"><td>{{ new Date(log.created_at).toLocaleString() }}</td><td><b>{{ log.node }}</b><small>{{ log.job_id?.slice(0,8) }}</small></td><td><em :class="log.status">{{ log.status }}</em></td><td>{{ log.duration_ms??0 }} ms</td><td><code>{{ JSON.stringify(log.request_summary).slice(0,90) }}</code></td><td>{{ log.error||'—' }}</td></tr></tbody></table></section>
      <section v-else class="runtime-settings-card"><h2>基础配置</h2><p>视频 Live 模式需要公网可访问的资源地址，Seedance 会通过这个地址读取已上传商品图。</p><label>PUBLIC_ASSET_BASE_URL<input v-model="runtimeSettings.public_asset_base_url" placeholder="https://your-domain.com"/></label><small>正式部署建议配置环境变量 LISTINGO_PUBLIC_ASSET_BASE_URL；这里保存只作用于当前后端运行实例。</small><button class="admin-primary" @click="saveRuntimeSettings"><SaveOutlined/>保存基础配置</button></section>
    </main>
    <a-drawer v-model:open="providerOpen" title="模型配置" width="480">
      <div v-if="selectedProvider" class="provider-form">
        <label>名称<input v-model="selectedProvider.label"/></label>
        <label>模型名<input v-model="selectedProvider.model_name"/></label>
        <label>API 端点<input v-model="selectedProvider.base_url"/></label>
        <label>API Key<input v-model="apiKey" type="password" :placeholder="selectedProvider.api_key_masked||'手工录入，不自动复制'"/></label>
        <label>超时（秒）<input v-model.number="selectedProvider.config.timeout_seconds" type="number"/></label>
        <label v-if="selectedProvider.adapter==='gemini_generate_content'">
          清晰度档位（imageSize）
          <select v-model="selectedProvider.config.resolution">
            <option v-for="value in providerResolutions(selectedProvider)" :key="value" :value="value">{{ value }}</option>
          </select>
          <small>Nano / Nano Pro 只在后台配置清晰度档位；画面比例始终由前台任务单独传入，不在这里设置。</small>
        </label>
        <label v-else-if="selectedProvider.adapter==='openai_images_generation'">
          输出尺寸（size）
          <select v-model="selectedProvider.config.size">
            <option value="follow_ratio">跟随前台画面比例（推荐）</option>
            <optgroup label="高级固定尺寸（可能覆盖前台比例）">
              <option v-for="value in providerImage2Sizes(selectedProvider)" :key="value" :value="value">{{ value }}</option>
            </optgroup>
          </select>
          <small>Image 2 使用像素尺寸；推荐保持“跟随前台画面比例”，系统会按用户选择的比例自动映射尺寸。</small>
          <small v-if="selectedProvider.config.size && selectedProvider.config.size !== 'follow_ratio'" class="image2-size-warning">当前为固定 size，会覆盖前台比例；若与任务比例不匹配，后端会在调用模型前直接失败并提示精确原因。</small>
        </label>
        <div v-if="selectedProvider.capability==='image'" class="two-col">
          <label>质量<select v-model="selectedProvider.config.quality"><option v-for="value in ['auto','low','medium','high']" :key="value">{{ value }}</option></select></label>
          <label>格式<select v-model="selectedProvider.config.format"><option v-for="value in ['png','jpeg','webp']" :key="value">{{ value }}</option></select></label>
        </div>
        <label class="check"><input v-model="selectedProvider.enabled" type="checkbox"/>启用 Provider</label>
        <p class="provider-enable-help">勾选只代表允许任务调用；还需要保存有效 API Key，卡片才会显示“当前生效”。模型在业务链路中的主用、备用或排版角色由系统预设。</p>
        <p>“连通测试”只验证密钥与模型目录，不计费生图；真实图像冒烟测试需显式运行后端脚本。</p>
        <button class="admin-primary full" @click="saveProvider">保存配置</button>
      </div>
    </a-drawer>
  </div>
</template>

<style>
.admin-shell button { border: 0; background: none; }
.provider-form select { height: 38px; border: 1px solid #dfe1e6; border-radius: 8px; padding: 0 10px; background: #fff; }
.provider-form label > small { color: #979da7; line-height: 1.5; }
.provider-form .image2-size-warning { color: #d46b08; background: #fff7e6; border: 1px solid #ffe1ad; border-radius: 7px; padding: 7px 9px; }
.runtime-settings-card { max-width: 720px; background: #fff; border-radius: 14px; padding: 24px; box-shadow: 0 8px 28px rgba(31,35,41,.07); }
.runtime-settings-card h2 { margin: 0 0 8px; }
.runtime-settings-card p, .runtime-settings-card small { color: #7d8491; line-height: 1.7; }
.runtime-settings-card label { display: flex; flex-direction: column; gap: 8px; margin: 20px 0 8px; font-weight: 650; }
.runtime-settings-card input { height: 40px; border: 1px solid #dfe1e6; border-radius: 8px; padding: 0 12px; }
.runtime-settings-card button { margin-top: 18px; }
@media (max-width: 900px) {
  .admin-top { padding: 0 12px; }
  .admin-divider, .admin-top>strong { display: none; }
  .admin-top>button { white-space: nowrap; font-size: 11px; }
  .admin-nav>p { font-size: 0; }
  .admin-nav>button { font-size: 0 !important; justify-content: center; }
  .admin-nav>button>.anticon { font-size: 18px; }
}
</style>
<style src="./admin.css"/>
<style src="./admin-provider-groups.css"/>
<style src="./admin-prompt-upload.css"/>
