<script setup lang="ts">
import { computed, onMounted, onUnmounted, ref, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { message } from 'ant-design-vue'
import { Background } from '@vue-flow/background'
import { Controls } from '@vue-flow/controls'
import { VueFlow } from '@vue-flow/core'
import '@vue-flow/core/dist/style.css'
import '@vue-flow/core/dist/theme-default.css'
import {
  ApiOutlined, ArrowLeftOutlined, BranchesOutlined, CheckCircleFilled, CodeOutlined,
  CheckOutlined, CloseOutlined, FileTextOutlined, MinusOutlined, PlayCircleOutlined,
  PlusOutlined, SaveOutlined, SettingOutlined, ThunderboltOutlined, UploadOutlined,
} from '@ant-design/icons-vue'
import BrandLogo from '../../components/BrandLogo.vue'
import { api, assistCopywriting, assistVideoCopywriting } from '../../api/client'
import {
  APLUS_MODULE_TOTAL_LIMIT,
  aplusLanguageOptions,
  aplusMarketOptions,
  aplusModuleTotal,
  aplusModules,
  aplusOutputSpecs,
  aplusPlatformOptions,
  buildAplusOutputTargets,
  isAplusAmazon,
  languageOptions as suiteLanguageOptions,
  marketOptions as suiteMarketOptions,
  orderedAplusModuleSelections,
  platformOptions as suitePlatformOptions,
  ratioOptions as suiteRatioOptions,
  renderMarkdown,
  videoCountryOptions,
  videoLanguageOptions,
  videoMarketOptions,
  videoPlatformOptions,
  videoRatioOptions,
  videoTypeOptions,
  type AplusAdvancedTarget,
  type AplusModuleSelection,
  type AplusOutputSpec,
} from '../workspace/workspace-model'
import {
  groupProviderCategoriesByBusinessRoute,
  providerRoutesForCapability,
  providerRuntimeState,
  type ProviderDisplayRecord,
} from './provider-display'

type Provider = ProviderDisplayRecord
const route=useRoute(); const router=useRouter(); const section=computed(()=>String(route.params.section||'providers'))
const providers=ref<Provider[]>([]); const selectedProvider=ref<Provider|null>(null); const providerOpen=ref(false); const apiKey=ref('')
const prompts=ref<any[]>([]); const promptDetail=ref<any>(null); const promptContent=ref(''); const promptNote=ref('')
const promptTestInputs=ref({platform:'亚马逊',market:'美国',country:'美国',language:'英文',aspect_ratio:'1:1',selling_points:'便携保温水杯，适合通勤、健身和日常补水；杯身轻量，密封防漏，适合放入背包。',product_name:'便携保温水杯',product_info:'便携保温水杯，316 不锈钢内胆，杯身轻量，密封防漏，适合通勤、健身和户外短途使用。',instruction:'保持商品本体不变，把画面改成更适合移动端信息流的通勤生活场景。',text:'普通电商商品描述测试。',video_type:'UGC 种草',duration:15,resolution:'1080p',output_spec:'amazon_aplus_standard' as AplusOutputSpec,advanced_targets:['web'] as AplusAdvancedTarget[],target_audience:'20-35 岁通勤与健身人群'})
const promptAplusModules=ref<AplusModuleSelection[]>([{name:'商品主视觉',count:1},{name:'卖点拆解',count:1},{name:'生活场景',count:1}])
const promptTestAssets=ref<any[]>([]); const promptTestRuns=ref<any[]>([]); const promptTestResult=ref<any|null>(null)
const promptTesting=ref(false); const promptFullTesting=ref(false); let promptTestPollTimer:ReturnType<typeof setTimeout>|null=null
const promptAiWriting=ref(false); const promptAiSuggestion=ref(''); const promptAiWriteOpen=ref(false); const promptAiSuggestionEditing=ref(false)
const workflows=ref<any[]>([]); const workflowDetail=ref<any>(null); const nodes=ref<any[]>([]); const edges=ref<any[]>([])
const logs=ref<any[]>([]); const logTotal=ref(0); const loading=ref(false)
const logFilters=ref({ node: '', status: '' })
const runtimeSettings=ref({ public_asset_base_url: '', public_asset_base_url_configured: false })
const savingRuntimeSettings=ref(false)
const nav=[{key:'providers',label:'模型配置',icon:ApiOutlined},{key:'workflow',label:'Workflow',icon:BranchesOutlined},{key:'prompts',label:'提示词资产',icon:CodeOutlined},{key:'logs',label:'执行日志',icon:FileTextOutlined},{key:'settings',label:'基础配置',icon:SettingOutlined}]
const sectionTitle=computed(()=>nav.find((item)=>item.key===section.value)?.label||'运营后台')
const providerCategories=computed(()=>groupProviderCategoriesByBusinessRoute(providers.value))
const selectedProviderRoutes=computed(()=>selectedProvider.value?providerRoutesForCapability(selectedProvider.value.capability):[])
const activeWorkflowVersion=computed(()=>workflowDetail.value?.versions?.find((item:any)=>item.id===workflowDetail.value.active_version_id)||workflowDetail.value?.versions?.[0])
const fullChainPromptCodes=['ecommerce-meta','ecommerce-video-meta-15s','aplus-meta']
const promptSupportsFullChain=computed(()=>fullChainPromptCodes.includes(promptDetail.value?.code))
const promptCanAiRewrite=computed(()=>['ecommerce-meta','ecommerce-video-meta-15s','aplus-meta','copywriting-assist','product-vision','content-safety-review'].includes(promptDetail.value?.code))
const promptIsVideo=computed(()=>promptDetail.value?.code==='ecommerce-video-meta-15s')
const promptIsAplus=computed(()=>promptDetail.value?.code==='aplus-meta')
const promptPlatformChoices=computed(()=>promptIsVideo.value?videoPlatformOptions:promptIsAplus.value?aplusPlatformOptions:suitePlatformOptions)
const promptMarketChoices=computed(()=>promptIsVideo.value?videoMarketOptions:promptIsAplus.value?aplusMarketOptions:suiteMarketOptions)
const promptLanguageChoices=computed(()=>promptIsVideo.value?videoLanguageOptions:promptIsAplus.value?aplusLanguageOptions:suiteLanguageOptions)
const promptCountryChoices=computed(()=>videoCountryOptions)
const promptRatioChoices=computed(()=>promptIsVideo.value?(videoRatioOptions.filter((item)=>item.platform===promptTestInputs.value.platform).length?videoRatioOptions.filter((item)=>item.platform===promptTestInputs.value.platform):videoRatioOptions):suiteRatioOptions.map((value)=>({label:value,value})))
const promptAplusAmazon=computed(()=>isAplusAmazon(promptTestInputs.value.platform))
const promptAplusAvailableOutputSpecs=computed(()=>aplusOutputSpecs.filter((item)=>!item.amazonOnly||promptAplusAmazon.value))
const promptAplusOutputTargets=computed(()=>buildAplusOutputTargets({platform:promptTestInputs.value.platform,market:promptTestInputs.value.market,language:promptTestInputs.value.language,productInfo:promptTestInputs.value.product_info,selectedModules:promptAplusModules.value,outputSpec:promptTestInputs.value.output_spec,advancedTargets:promptTestInputs.value.advanced_targets,dryRun:true}))
const promptAplusSelectedTotal=computed(()=>aplusModuleTotal(promptAplusModules.value))
const promptAiRewriteTargetLabel=computed(()=>promptDetail.value?.code==='content-safety-review'?'审查文本':promptIsAplus.value||promptDetail.value?.code==='product-vision'?'商品信息':'卖点文本')

onMounted(loadSection); watch(section,loadSection)
watch(()=>promptTestInputs.value.platform,()=>{if(promptIsVideo.value){const first=promptRatioChoices.value[0];if(first)promptTestInputs.value.aspect_ratio=first.value}if(!promptAplusAmazon.value&&String(promptTestInputs.value.output_spec).startsWith('amazon_aplus'))promptTestInputs.value.output_spec='1:1'})
onUnmounted(()=>clearPromptTestPoll())
async function loadLogs(){const params:Record<string,string>={};if(logFilters.value.node)params.node=logFilters.value.node;if(logFilters.value.status)params.status=logFilters.value.status;const data=(await api.get('/admin/logs',{params})).data;logs.value=data.items;logTotal.value=data.total}
async function loadSection(){ loading.value=true; try{ if(section.value==='providers')providers.value=(await api.get('/admin/providers')).data; if(section.value==='prompts'){prompts.value=(await api.get('/admin/prompts')).data;if(prompts.value[0])await loadPrompt(prompts.value[0].id)} if(section.value==='workflow'){workflows.value=(await api.get('/admin/workflows')).data;if(workflows.value[0])await loadWorkflow(workflows.value[0].id)} if(section.value==='logs')await loadLogs(); if(section.value==='settings')runtimeSettings.value=(await api.get('/admin/runtime-settings')).data }catch{message.error('后台数据加载失败，请确认 API 已启动')}finally{loading.value=false}}
function go(key:string){router.push(`/admin/${key}`)}
function editProvider(provider:Provider){const copied=JSON.parse(JSON.stringify(provider));copied.route_roles=copied.route_roles||{};selectedProvider.value=copied;apiKey.value='';providerOpen.value=true}
async function saveProvider(){if(!selectedProvider.value)return;const p=selectedProvider.value;await api.patch(`/admin/providers/${p.id}`,{label:p.label,base_url:p.base_url,model_name:p.model_name,enabled:p.enabled,route_roles:p.route_roles,api_key:apiKey.value||undefined,resolution:p.config.resolution,size:p.config.size,quality:p.config.quality,format:p.config.format,compression:p.config.compression,timeout_seconds:p.config.timeout_seconds});providerOpen.value=false;await loadSection();message.success('模型配置已保存')}
async function testProvider(provider:Provider){message.loading({content:`正在测试 ${provider.label}`,key:'provider-test'});try{const result=(await api.post(`/admin/providers/${provider.id}/test`)).data;message[result.ok?'success':'error']({content:result.message,key:'provider-test'})}catch(error:any){message.error({content:error.response?.data?.detail||'连通测试失败',key:'provider-test'})}}
async function toggleProvider(provider:Provider){await api.patch(`/admin/providers/${provider.id}`,{enabled:!provider.enabled});await loadSection()}
function onRouteRoleChange(routeKey:string,event:Event){if(!selectedProvider.value)return;const value=(event.target as HTMLSelectElement).value;const next={...(selectedProvider.value.route_roles||{})};if(value==='none')delete next[routeKey];else next[routeKey]=value as 'primary'|'fallback';selectedProvider.value.route_roles=next}
function providerResolutions(provider:Provider):string[]{return Array.isArray(provider.config.allowed_resolutions)?provider.config.allowed_resolutions as string[]:['1K','2K','4K']}
function providerImage2Sizes(provider:Provider):string[]{return Array.isArray(provider.config.allowed_sizes)?(provider.config.allowed_sizes as string[]).filter((value)=>value!=='follow_ratio'):['auto','1024x1024','1536x1024','1024x1536','2048x2048','2048x1152','3840x2160','2160x3840']}
async function loadPrompt(id:string){promptDetail.value=(await api.get(`/admin/prompts/${id}`)).data;promptContent.value=promptDetail.value.active_version.content;promptNote.value='';await loadPromptTestRuns();promptTestResult.value=promptTestRuns.value[0]||null}
async function savePrompt(){const version=(await api.post(`/admin/prompts/${promptDetail.value.id}/versions`,{content:promptContent.value,change_note:promptNote.value||'后台保存新版本'})).data;await api.post(`/admin/prompts/${promptDetail.value.id}/versions/${version.id}/activate`);await loadPrompt(promptDetail.value.id);message.success('提示词新版本已保存并启用')}
async function uploadPromptFile(event:Event){const input=event.target as HTMLInputElement;const file=input.files?.[0];if(!file||!promptDetail.value)return;const body=new FormData();body.append('file',file);body.append('change_note',promptNote.value||`上传文件：${file.name}`);try{await api.post(`/admin/prompts/${promptDetail.value.id}/versions/upload`,body);await loadPrompt(promptDetail.value.id);message.success('提示词文件已上传为新版本，请在版本历史中选择启用')}catch(error:any){message.error(error.response?.data?.detail||'提示词文件上传失败')}finally{input.value=''}}
async function activatePrompt(version:any){await api.post(`/admin/prompts/${promptDetail.value.id}/versions/${version.id}/activate`);await loadPrompt(promptDetail.value.id);message.success(`已启用提示词 v${version.version_no}，后续 Live 任务将引用此版本`)}
async function loadPromptTestRuns(){if(!promptDetail.value)return;promptTestRuns.value=(await api.get(`/admin/prompts/${promptDetail.value.id}/test-runs`)).data}
function clearPromptTestPoll(){if(promptTestPollTimer){clearTimeout(promptTestPollTimer);promptTestPollTimer=null}}
function promptAplusModuleCount(moduleName:string){return promptAplusModules.value.find((item)=>item.name===moduleName)?.count??0}
function setPromptAplusModuleCount(moduleName:string,count:number){const normalized=Math.max(0,Math.min(APLUS_MODULE_TOTAL_LIMIT,Math.floor(count)||0));const next=promptAplusModules.value.filter((item)=>item.name!==moduleName);if(normalized>0)next.push({name:moduleName,count:normalized});promptAplusModules.value=next}
function togglePromptAplusModule(moduleName:string){if(promptAplusModuleCount(moduleName)>0){setPromptAplusModuleCount(moduleName,0);return}if(promptAplusSelectedTotal.value>=APLUS_MODULE_TOTAL_LIMIT){message.warning(`详情页模块最多生成 ${APLUS_MODULE_TOTAL_LIMIT} 张`);return}setPromptAplusModuleCount(moduleName,1)}
function incrementPromptAplusModule(moduleName:string){if(promptAplusSelectedTotal.value>=APLUS_MODULE_TOTAL_LIMIT){message.warning(`详情页模块最多生成 ${APLUS_MODULE_TOTAL_LIMIT} 张`);return}setPromptAplusModuleCount(moduleName,promptAplusModuleCount(moduleName)+1)}
function decrementPromptAplusModule(moduleName:string){setPromptAplusModuleCount(moduleName,promptAplusModuleCount(moduleName)-1)}
function togglePromptAplusAdvancedTarget(target:AplusAdvancedTarget){const exists=promptTestInputs.value.advanced_targets.includes(target);if(exists&&promptTestInputs.value.advanced_targets.length===1){message.warning('高级 A+ 至少选择 Web 或移动端中的一个');return}promptTestInputs.value.advanced_targets=exists?promptTestInputs.value.advanced_targets.filter((item)=>item!==target):[...promptTestInputs.value.advanced_targets,target]}
function promptTestInputsPayload(){const code=promptDetail.value?.code;const asset_ids=promptTestAssets.value.map((asset:any)=>asset.id);const base={asset_ids,platform:promptTestInputs.value.platform,market:promptTestInputs.value.market,language:promptTestInputs.value.language,selling_points:promptTestInputs.value.selling_points,product_name:promptTestInputs.value.product_name,aspect_ratio:promptTestInputs.value.aspect_ratio,target_audience:promptTestInputs.value.target_audience};if(code==='ecommerce-video-meta-15s')return{...base,country:promptTestInputs.value.country,video_types:[promptTestInputs.value.video_type],duration:promptTestInputs.value.duration,resolution:promptTestInputs.value.resolution};if(code==='aplus-meta'){const moduleSelections=orderedAplusModuleSelections(promptAplusModules.value);return{asset_ids,platform:promptTestInputs.value.platform,market:promptTestInputs.value.market,language:promptTestInputs.value.language,product_info:promptTestInputs.value.product_info,module_selections:moduleSelections,selected_modules:moduleSelections.map((item)=>item.name),output_targets:promptAplusOutputTargets.value}};if(code==='product-vision')return{asset_ids,product_name:promptTestInputs.value.product_name,product_info:promptTestInputs.value.product_info,selling_points:promptTestInputs.value.selling_points};if(code==='edit-rewrite')return{instruction:promptTestInputs.value.instruction,original_prompt:{image_type:'主图',picture_requirement:'商品居中，保持外观、颜色、结构一致。',copywriting_requirements:'使用简洁标题。'}};if(code==='content-safety-review')return{subject:'prompt_test',text:promptTestInputs.value.text};return base}
async function uploadPromptTestAsset(event:Event){const input=event.target as HTMLInputElement;const file=input.files?.[0];if(!file)return;const body=new FormData();body.append('file',file);try{const asset=(await api.post('/assets',body)).data;promptTestAssets.value=[...promptTestAssets.value,asset].slice(-3);message.success('样例商品图已上传')}catch(error:any){message.error(error.response?.data?.detail||'样例图上传失败')}finally{input.value=''}}
function removePromptTestAsset(id:string){promptTestAssets.value=promptTestAssets.value.filter((asset:any)=>asset.id!==id)}
function promptAiTargetValue(){if(promptDetail.value?.code==='content-safety-review')return promptTestInputs.value.text;return promptIsAplus.value||promptDetail.value?.code==='product-vision'?promptTestInputs.value.product_info:promptTestInputs.value.selling_points}
function setPromptAiTargetValue(value:string){if(promptDetail.value?.code==='content-safety-review')promptTestInputs.value.text=value;else if(promptIsAplus.value||promptDetail.value?.code==='product-vision')promptTestInputs.value.product_info=value;else promptTestInputs.value.selling_points=value}
async function runPromptAiWrite(){if(!promptCanAiRewrite.value)return;promptAiWriting.value=true;try{const asset_ids=promptTestAssets.value.map((asset:any)=>asset.id);const text=promptAiTargetValue();const result=promptIsVideo.value?await assistVideoCopywriting({asset_ids,platform:promptTestInputs.value.platform,market:promptTestInputs.value.market,country:promptTestInputs.value.country,language:promptTestInputs.value.language,selling_points:text,video_types:[promptTestInputs.value.video_type],dry_run:false}):await assistCopywriting({asset_ids,platform:promptTestInputs.value.platform,market:promptTestInputs.value.market,language:promptTestInputs.value.language,selling_points:text,dry_run:false});promptAiSuggestion.value=result.selling_points;promptAiSuggestionEditing.value=false;promptAiWriteOpen.value=true}catch(error:any){message.error(error.response?.data?.detail||'AI 转写失败，请检查语言模型配置')}finally{promptAiWriting.value=false}}
async function regeneratePromptAiWrite(){await runPromptAiWrite()}
function applyPromptAiSuggestion(){if(!promptAiSuggestion.value.trim())return message.warning('AI 转写内容为空，请重新生成');setPromptAiTargetValue(promptAiSuggestion.value.trim());promptAiWriteOpen.value=false;promptAiSuggestionEditing.value=false;message.success('AI 转写已确认回填')}
async function runPromptTest(testType:'llm_output'|'full_chain'){if(!promptDetail.value)return;if(testType==='full_chain'&&!promptSupportsFullChain.value){message.warning('当前提示词只支持 LLM 输出测试');return}if(testType==='full_chain'&&!promptTestAssets.value.length){message.warning('完整链路测试至少需要上传一张样例商品图');return}const flag=testType==='full_chain'?promptFullTesting:promptTesting;flag.value=true;try{const run=(await api.post(`/admin/prompts/${promptDetail.value.id}/test-runs`,{test_type:testType,prompt_content:promptContent.value,inputs:promptTestInputsPayload()})).data;promptTestResult.value=run;await loadPromptTestRuns();message.success(testType==='full_chain'?'完整链路测试已开始':'LLM 试跑完成');if(testType==='full_chain')pollPromptTestRun(run.id)}catch(error:any){message.error(error.response?.data?.detail||'提示词测试失败')}finally{flag.value=false}}
async function pollPromptTestRun(id:string){clearPromptTestPoll();try{const run=(await api.get(`/admin/prompt-test-runs/${id}`)).data;promptTestResult.value=run;await loadPromptTestRuns();if(['queued','running'].includes(run.status)){promptTestPollTimer=setTimeout(()=>pollPromptTestRun(id),2000)}else{message[run.status==='succeeded'?'success':'error'](run.status==='succeeded'?'后台测试已完成':run.error||'后台测试失败')}}catch{promptTestPollTimer=setTimeout(()=>pollPromptTestRun(id),3000)}}
function promptTestTypeLabel(type:string){return type==='full_chain'?'完整链路':'LLM 输出'}
function promptTestStatusLabel(status:string){return status==='succeeded'?'成功':status==='failed'?'失败':status==='partial_failed'?'部分失败':status==='running'?'运行中':'排队中'}
function prettyJson(value:any){return JSON.stringify(value??{},null,2)}
function isVideoArtifact(url:string){return /\.(mp4|mov|webm)(\?|$)/i.test(url)}
async function loadWorkflow(id:string){workflowDetail.value=(await api.get(`/admin/workflows/${id}`)).data;const active=workflowDetail.value.versions.find((item:any)=>item.id===workflowDetail.value.active_version_id)||workflowDetail.value.versions[0];nodes.value=active.graph.nodes;edges.value=active.graph.edges}
function onWorkflowSelect(event:Event){const input=event.target as HTMLSelectElement;if(input.value)void loadWorkflow(input.value)}
async function dryrunWorkflow(){const active=activeWorkflowVersion.value;if(!workflowDetail.value||!active)return;const result=(await api.post(`/admin/workflows/${workflowDetail.value.id}/versions/${active.id}/dryrun`)).data;message[result.ok?'success':'error'](result.ok?'Workflow Dryrun 校验通过':result.errors.join('；'))}
function previewWorkflowVersion(version:any){nodes.value=version.graph.nodes;edges.value=version.graph.edges}
async function saveRuntimeSettings(){savingRuntimeSettings.value=true;try{runtimeSettings.value=(await api.patch('/admin/runtime-settings',{public_asset_base_url:runtimeSettings.value.public_asset_base_url})).data;message.success('基础配置已保存到当前运行实例')}catch(error:any){message.error(error.response?.data?.detail||'基础配置保存失败')}finally{savingRuntimeSettings.value=false}}
</script>

<template>
  <div class="admin-shell">
    <header class="admin-top"><BrandLogo/><span class="admin-divider"/> <strong>运营后台</strong><div/><button @click="router.push('/app/suite')"><ArrowLeftOutlined/>返回工作台</button></header>
    <aside class="admin-nav"><p>配置中心</p><button v-for="item in nav" :key="item.key" :class="{active:section===item.key}" @click="go(item.key)"><component :is="item.icon"/>{{ item.label }}</button><div class="admin-safe"><CheckCircleFilled/><span><b>Dryrun 已开启</b><small>外部调用默认关闭</small></span></div></aside>
    <main class="admin-main"><div class="admin-title"><div><h1>{{ sectionTitle }}</h1><p>{{ section==='providers'?'统一配置 LLM 与图片模型，密钥加密保存':section==='workflow'?'低代码节点画布、版本与启用校验':section==='prompts'?'唯一来源为用户上传 MD；Artflo 提示词不参与执行':section==='settings'?'配置视频 Live 模式所需的公网资源地址':'按任务、节点、模型与状态追踪执行链路' }}</p></div><div class="admin-title-actions"><span v-if="loading">加载中…</span></div></div>
      <section v-if="section==='providers'" class="provider-page">
        <div class="provider-activation-note"><CheckCircleFilled/><div><b>Provider 生效条件</b><p>启用开关只是允许调用；还必须配置 API Key，模型才会显示“当前生效”。Live 任务只会调用下方业务分组中已生效的模型。</p><ul class="provider-state-legend"><li class="ready">当前生效：启用且密钥已配置</li><li class="warning">缺少密钥：已启用但无法调用</li><li class="off">未启用：不会进入 Live 链路</li></ul></div></div>
        <section v-for="category in providerCategories" :key="category.key" class="provider-category" :class="`provider-category-${category.key}`">
          <header class="provider-category-head"><h2>{{ category.title }}</h2><p>{{ category.key==='suite'?'套图大板块模型链路':category.key==='aplus'?'A+ 详情页模型链路':'独立模型链路' }}</p></header>
          <section v-for="group in category.groups" :key="group.key" class="provider-group" :class="`provider-group-${group.key}`">
            <header class="provider-group-head"><div><span>{{ group.title }}</span><div><h2>{{ group.categoryKey===group.key?group.title:`${group.categoryTitle} / ${group.title}` }}</h2><p>{{ group.description }}</p></div></div><aside><small>实际调用顺序</small><b>{{ group.route }}</b><em :class="{ready:group.ready}">{{ group.statusLabel }}</em></aside></header>
            <div class="provider-grid"><article v-for="provider in group.providers" :key="provider.id" class="provider-card" :class="`runtime-${providerRuntimeState(provider).tone}`">
              <div class="provider-head"><span><ApiOutlined/></span><div><h3>{{ provider.label }}</h3><p>{{ provider.model_name }}</p></div><button class="toggle" :class="{on:provider.enabled}" :aria-label="`${provider.enabled?'停用':'启用'} ${provider.label}`" :title="provider.enabled?'点击停用 Provider':'点击启用 Provider'" @click="toggleProvider(provider)"/></div>
              <div class="provider-runtime" :class="providerRuntimeState(provider).tone"><i/><span><b>{{ providerRuntimeState(provider).label }}</b><small>{{ providerRuntimeState(provider).detail }}</small></span></div>
              <div class="provider-badges"><em class="business-role">{{ provider.role }}</em><em>{{ provider.capability==='llm'?'语言模型':provider.capability==='video'?'视频模型':'图片模型' }}</em><em :class="provider.has_api_key?'key-ok':'key-empty'">{{ provider.has_api_key?'密钥已配置':'无密钥' }}</em></div>
              <dl><div><dt>端点</dt><dd>{{ provider.base_url }}</dd></div><div><dt>适配器</dt><dd>{{ provider.adapter }}</dd></div><div><dt>默认参数</dt><dd>{{ provider.config.resolution||provider.config.size||'JSON' }} · {{ provider.config.timeout_seconds }}s</dd></div></dl>
              <footer><button @click="testProvider(provider)"><PlayCircleOutlined/>连通测试</button><button class="edit" @click="editProvider(provider)"><SettingOutlined/>配置</button></footer>
            </article><div v-if="!group.providers.length" class="provider-empty-route"><SettingOutlined/><span>未配置{{ group.categoryKey===group.key?group.title:`${group.categoryTitle} / ${group.title}` }}链路</span></div></div>
          </section>
        </section>
      </section>
      <section v-else-if="section==='workflow'" class="workflow-layout">
        <div class="workflow-toolbar">
          <div>
            <select class="workflow-selector" :value="workflowDetail?.id" @change="onWorkflowSelect">
              <option v-for="workflow in workflows" :key="workflow.id" :value="workflow.id">{{ workflow.name }}</option>
            </select>
            <span class="workflow-active-state"><span class="active-dot"/>已启用 v{{ activeWorkflowVersion?.version_no }} · 固定执行器</span>
          </div>
          <button @click="dryrunWorkflow"><PlayCircleOutlined/>Dryrun</button>
        </div>
        <div class="flow-canvas"><VueFlow v-model:nodes="nodes" v-model:edges="edges" fit-view-on-init><Background pattern-color="#dad7ea" :gap="22"/><Controls/></VueFlow></div>
        <aside class="flow-inspector">
          <h3>Workflow 资产</h3>
          <p>{{ workflowDetail?.description }}。当前画布为只读执行链路视图，版本由后端种子与代码变更管理。</p>
          <div v-for="node in nodes" :key="node.id"><span>{{ node.type }}</span><b>{{ node.data?.label }}</b></div>
          <h3>版本历史</h3>
          <button v-for="version in workflowDetail?.versions" :key="version.id" @click="previewWorkflowVersion(version)"><b>v{{ version.version_no }}</b><small>{{ version.change_note }}</small></button>
        </aside>
      </section>
      <section v-else-if="section==='prompts'" class="prompt-layout">
        <aside>
          <h3>提示词资产</h3>
          <button v-for="prompt in prompts" :key="prompt.id" :class="{active:prompt.id===promptDetail?.id}" @click="loadPrompt(prompt.id)"><CodeOutlined/><span><b>{{ prompt.name }}</b><small>{{ prompt.code }} · {{ prompt.version_count }} 个版本</small></span></button>
          <label class="prompt-upload"><UploadOutlined/>上传到当前提示词<input type="file" accept=".md,.txt,text/markdown,text/plain" @change="uploadPromptFile"/></label>
          <div class="source-lock"><CheckCircleFilled/><p><b>Live Prompt 工程</b><br/>套图规划、商品识别、AI 帮写与二次编辑均引用各自当前启用版本。Artflo 不参与执行。</p></div>
        </aside>
        <div class="prompt-editor">
          <header><div><strong>{{ promptDetail?.name }}</strong><span>{{ promptDetail?.description }} · 当前启用 v{{ promptDetail?.versions?.find((v:any)=>v.id===promptDetail.active_version_id)?.version_no }}</span></div><button class="admin-primary" @click="savePrompt"><SaveOutlined/>保存并启用新版本</button></header>
          <textarea v-model="promptContent" spellcheck="false"/>
          <footer><input v-model="promptNote" placeholder="版本说明（可选）"/><span>Live 任务会锁定当前启用版本；Dryrun 仅记录版本并走本地确定性状态机。</span></footer>
        </div>
        <aside class="prompt-test-panel">
          <header class="prompt-test-console-head">
            <div><h3>提示词测试台</h3><p>模拟前台输入表单，使用当前编辑器内容试跑；测试成功不会自动保存或启用版本。</p></div>
            <span>{{ promptDetail?.code }}</span>
          </header>
          <div class="prompt-test-workspace">
            <section class="prompt-test-config">
              <section class="prompt-test-config-section">
                <div class="prompt-test-section-title"><span>1</span><b>商品素材</b><small>{{ promptTestAssets.length }}/3</small></div>
                <label class="prompt-test-upload"><UploadOutlined/><b>上传商品图</b><small>完整链路测试至少 1 张</small><input type="file" accept="image/*" @change="uploadPromptTestAsset"/></label>
                <div v-if="promptTestAssets.length" class="prompt-test-asset-grid">
                  <figure v-for="asset in promptTestAssets" :key="asset.id"><img :src="asset.url" :alt="asset.original_name"/><button @click="removePromptTestAsset(asset.id)">移除</button></figure>
                </div>
              </section>
              <section class="prompt-test-config-section">
                <div class="prompt-test-section-title"><span>2</span><b>目标市场与语言</b><small>{{ promptSupportsFullChain?'支持完整链路':'仅 LLM 节点' }}</small></div>
                <div class="prompt-test-fields">
                  <label>平台<select v-model="promptTestInputs.platform"><option v-for="value in promptPlatformChoices" :key="value" :value="value">{{ value }}</option></select></label>
                  <label>市场<select v-model="promptTestInputs.market"><option v-for="value in promptMarketChoices" :key="value" :value="value">{{ value }}</option></select></label>
                  <label>语言<select v-model="promptTestInputs.language"><option v-for="value in promptLanguageChoices" :key="value" :value="value">{{ value }}</option></select></label>
                  <label v-if="promptIsVideo">国家<select v-model="promptTestInputs.country"><option v-for="value in promptCountryChoices" :key="value" :value="value">{{ value }}</option></select></label>
                  <label v-if="promptDetail?.code==='ecommerce-meta'||promptIsVideo">画面比例<select v-model="promptTestInputs.aspect_ratio"><option v-for="item in promptRatioChoices" :key="item.label" :value="item.value">{{ item.label }}</option></select></label>
                  <label v-if="promptIsVideo">视频类型<select v-model="promptTestInputs.video_type"><option v-for="item in videoTypeOptions" :key="item.key" :value="item.key">{{ item.title }} · {{ item.subtitle }}</option></select></label>
                  <label>商品名称<input v-model="promptTestInputs.product_name" placeholder="可选"/></label>
                  <label>目标人群<input v-model="promptTestInputs.target_audience" placeholder="可选"/></label>
                </div>
              </section>
              <section v-if="promptIsAplus" class="prompt-test-config-section">
                <div class="prompt-test-section-title"><span>3</span><b>A+ 输出规格</b><small>{{ promptAplusOutputTargets.length }} 项</small></div>
                <div class="prompt-option-grid">
                  <button v-for="spec in promptAplusAvailableOutputSpecs" :key="spec.value" type="button" :class="{active:promptTestInputs.output_spec===spec.value}" @click="promptTestInputs.output_spec=spec.value"><i><CheckOutlined v-if="promptTestInputs.output_spec===spec.value"/></i><span><b>{{ spec.label }}</b><small>{{ spec.description }}</small></span></button>
                </div>
                <div v-if="promptAplusAmazon&&promptTestInputs.output_spec==='amazon_aplus_advanced'" class="prompt-advanced-targets">
                  <button type="button" :class="{active:promptTestInputs.advanced_targets.includes('web')}" @click="togglePromptAplusAdvancedTarget('web')"><CheckOutlined v-if="promptTestInputs.advanced_targets.includes('web')"/>Web · 1464:600</button>
                  <button type="button" :class="{active:promptTestInputs.advanced_targets.includes('mobile')}" @click="togglePromptAplusAdvancedTarget('mobile')"><CheckOutlined v-if="promptTestInputs.advanced_targets.includes('mobile')"/>移动端 · 600:450</button>
                </div>
                <div class="prompt-test-section-title sub"><b>详情页模块</b><small>{{ promptAplusSelectedTotal }}/{{ APLUS_MODULE_TOTAL_LIMIT }} 张</small></div>
                <div class="prompt-module-list">
                  <article v-for="module in aplusModules" :key="module.name" :class="{active:promptAplusModuleCount(module.name)>0}">
                    <button type="button" @click="togglePromptAplusModule(module.name)"><span><b>{{ module.name }}</b><small>{{ module.description }}</small></span></button>
                    <div><button type="button" :disabled="promptAplusModuleCount(module.name)<=0" @click.stop="decrementPromptAplusModule(module.name)"><MinusOutlined/></button><strong>{{ promptAplusModuleCount(module.name) }}</strong><button type="button" :disabled="promptAplusSelectedTotal>=APLUS_MODULE_TOTAL_LIMIT" @click.stop="incrementPromptAplusModule(module.name)"><PlusOutlined/></button></div>
                  </article>
                </div>
              </section>
              <section class="prompt-test-config-section">
                <div class="prompt-test-section-title"><span>{{ promptIsAplus?'4':'3' }}</span><b>{{ promptIsAplus||promptDetail?.code==='product-vision'?'商品信息':promptDetail?.code==='edit-rewrite'?'修改指令':promptDetail?.code==='content-safety-review'?'审查文本':'卖点 / 测试文本' }}</b><button v-if="promptCanAiRewrite" type="button" :disabled="promptAiWriting" @click="runPromptAiWrite"><ThunderboltOutlined/>{{ promptAiWriting?'转写中...':'AI 转写' }}</button></div>
                <label v-if="promptIsAplus||promptDetail?.code==='product-vision'" class="prompt-test-textarea"><textarea v-model="promptTestInputs.product_info" rows="7"/></label>
                <label v-else-if="promptDetail?.code==='edit-rewrite'" class="prompt-test-textarea"><textarea v-model="promptTestInputs.instruction" rows="7"/></label>
                <label v-else-if="promptDetail?.code==='content-safety-review'" class="prompt-test-textarea"><textarea v-model="promptTestInputs.text" rows="7"/></label>
                <label v-else class="prompt-test-textarea"><textarea v-model="promptTestInputs.selling_points" rows="7"/></label>
                <div v-if="promptAiWriteOpen" class="prompt-ai-write-panel" role="dialog" aria-label="AI 转写建议">
                  <header><strong><ThunderboltOutlined/>AI 转写建议 · 回填到{{ promptAiRewriteTargetLabel }}</strong><button type="button" aria-label="关闭 AI 转写建议" @click="promptAiWriteOpen=false"><CloseOutlined/></button></header>
                  <button v-if="promptAiSuggestion.trim()&&!promptAiSuggestionEditing" class="prompt-ai-preview" type="button" @click="promptAiSuggestionEditing=true" v-html="renderMarkdown(promptAiSuggestion)"/>
                  <textarea v-else v-model="promptAiSuggestion" rows="7" aria-label="AI 转写候选内容" @blur="promptAiSuggestionEditing=false"/>
                  <footer><button type="button" :disabled="promptAiWriting" @click="regeneratePromptAiWrite"><ThunderboltOutlined/>{{ promptAiWriting?'生成中...':'重新转写' }}</button><button type="button" class="apply" @click="applyPromptAiSuggestion">确认回填</button></footer>
                </div>
              </section>
              <section class="prompt-test-config-section prompt-test-run-section">
                <div class="prompt-test-actions">
                  <button :disabled="promptTesting||promptFullTesting" @click="runPromptTest('llm_output')"><PlayCircleOutlined/>{{ promptTesting?'试跑中...':'LLM 试跑' }}</button>
                  <button class="danger" :disabled="promptTesting||promptFullTesting||!promptSupportsFullChain" @click="runPromptTest('full_chain')"><PlayCircleOutlined/>{{ promptFullTesting?'已开始...':'完整链路生成' }}</button>
                </div>
                <section class="prompt-test-history">
                  <div class="prompt-test-section-title sub"><b>最近测试</b><small>{{ promptTestRuns.length }}</small></div>
                  <button v-for="run in promptTestRuns" :key="run.id" :class="{active:run.id===promptTestResult?.id}" @click="promptTestResult=run"><b>{{ promptTestTypeLabel(run.test_type) }}</b><small>{{ promptTestStatusLabel(run.status) }} · {{ run.prompt_content_sha256.slice(0,8) }}</small></button>
                </section>
              </section>
            </section>
            <section class="prompt-test-preview">
              <header class="prompt-test-preview-head">
                <div><h4>{{ promptTestResult ? `${promptTestTypeLabel(promptTestResult.test_type)} · ${promptTestStatusLabel(promptTestResult.status)}` : '等待试跑' }}</h4><p>{{ promptTestResult ? `进度 ${promptTestResult.progress}% · ${promptTestResult.prompt_content_sha256.slice(0, 8)}` : '点击左侧按钮后，这里会展示完整链路结果。' }}</p></div>
                <span>{{ promptTestResult?.related_job_type || 'admin-test' }}</span>
              </header>
              <p v-if="promptTestResult?.error" class="prompt-test-error">{{ promptTestResult.error }}</p>
              <div v-if="promptTestResult?.validation_errors?.length" class="prompt-test-errors"><b>校验提示</b><span v-for="error in promptTestResult.validation_errors" :key="error">{{ error }}</span></div>
              <div class="prompt-result-flow">
                <article class="prompt-result-card input"><header><span>01</span><b>本次输入</b></header><pre>{{ prettyJson(promptTestResult?.input_params || promptTestInputsPayload()) }}</pre></article>
                <article class="prompt-result-card json"><header><span>02</span><b>结构化 JSON</b></header><pre>{{ promptTestResult ? prettyJson(promptTestResult.parsed_output) : '试跑完成后展示解析后的 JSON。' }}</pre></article>
                <article class="prompt-result-card output"><header><span>03</span><b>模型原始输出</b></header><pre>{{ promptTestResult?.raw_output || 'LLM 节点完成后展示模型原始输出；完整链路也会保留后台任务输出。' }}</pre></article>
                <article class="prompt-result-card artifacts"><header><span>04</span><b>生图 / 视频结果</b></header><div v-if="promptTestResult?.artifact_urls?.length" class="prompt-test-artifacts"><template v-for="url in promptTestResult.artifact_urls" :key="url"><video v-if="isVideoArtifact(url)" :src="url" controls/><img v-else :src="url" alt="测试产物"/></template></div><div v-else class="prompt-artifact-empty">完整链路生成完成后展示图片缩略图或视频链接。</div></article>
              </div>
            </section>
          </div>
        </aside>
        <aside class="version-panel">
          <h3>版本历史</h3>
          <article v-for="version in promptDetail?.versions" :key="version.id" :class="{active:version.id===promptDetail.active_version_id}"><button @click="promptContent=version.content"><b>v{{ version.version_no }}<i v-if="version.id===promptDetail.active_version_id">当前生效</i></b><small>{{ version.change_note }}</small><em>{{ version.content_sha256.slice(0,10) }}…</em></button><button v-if="version.id!==promptDetail.active_version_id" class="activate-version" @click="activatePrompt(version)">启用此版本</button></article>
        </aside>
      </section>
      <section v-else-if="section==='logs'" class="logs-card"><div class="log-filters"><select v-model="logFilters.node"><option value="">全部节点</option><option value="image_generate">image_generate</option><option value="meta_prompt">meta_prompt</option><option value="video_meta_prompt">video_meta_prompt</option><option value="video_submit">video_submit</option><option value="video_generate">video_generate</option></select><select v-model="logFilters.status"><option value="">全部状态</option><option value="succeeded">succeeded</option><option value="failed">failed</option></select><button class="admin-primary" :disabled="loading" @click="loadLogs">筛选</button><span>共 {{ logTotal }} 条</span></div><table><thead><tr><th>时间</th><th>任务 / 节点</th><th>状态</th><th>耗时</th><th>请求摘要</th><th>错误</th></tr></thead><tbody><tr v-for="log in logs" :key="log.id"><td>{{ new Date(log.created_at).toLocaleString() }}</td><td><b>{{ log.node }}</b><small>{{ log.job_id?.slice(0,8) }}</small></td><td><em :class="log.status">{{ log.status }}</em></td><td>{{ log.duration_ms??0 }} ms</td><td><code>{{ JSON.stringify(log.request_summary).slice(0,90) }}</code></td><td>{{ log.error||'—' }}</td></tr></tbody></table></section>
      <section v-else class="runtime-settings-card"><header class="runtime-settings-head"><div><h2>基础配置</h2><p>视频 Live 模式需要公网可访问的资源地址，Seedance 会通过这个地址读取已上传商品图。</p></div></header><label>PUBLIC_ASSET_BASE_URL<input v-model="runtimeSettings.public_asset_base_url" placeholder="https://your-domain.com"/></label><small>正式部署建议配置环境变量 LISTINGO_PUBLIC_ASSET_BASE_URL；这里保存只作用于当前后端运行实例。</small><footer><button class="admin-primary" :disabled="savingRuntimeSettings" @click="saveRuntimeSettings"><SaveOutlined/>{{ savingRuntimeSettings ? '保存中...' : '保存基础配置' }}</button></footer></section>
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
        <div class="provider-route-role-editor">
          <b>业务链路角色</b>
          <label v-for="routeItem in selectedProviderRoutes" :key="routeItem.key">
            <span>{{ routeItem.categoryTitle }} / {{ routeItem.title }}</span>
            <select :value="selectedProvider.route_roles?.[routeItem.key] || 'none'" @change="onRouteRoleChange(routeItem.key, $event)">
              <option value="none">不参与</option>
              <option value="primary">主模型</option>
              <option value="fallback">备用模型</option>
            </select>
          </label>
          <small>同一链路只能有一个主模型和一个备用模型；保存后会自动替换同链路同角色的其他 Provider。</small>
        </div>
        <label class="check"><input v-model="selectedProvider.enabled" type="checkbox"/>启用 Provider</label>
        <p class="provider-enable-help">勾选只代表允许任务调用；还需要保存有效 API Key，并在业务链路角色中配置为主模型或备用模型，卡片才会显示“当前生效”。</p>
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
.admin-title-actions { display: flex; align-items: center; gap: 10px; }
.admin-title-actions .admin-primary { height: 36px; }
.admin-primary {
  background: #5b46e8 !important;
  border-color: #5b46e8 !important;
  color: #fff !important;
  box-shadow: 0 8px 18px rgba(91, 70, 232, .22);
}
.admin-primary:hover:not(:disabled) {
  background: #4d38d6 !important;
  border-color: #4d38d6 !important;
}
.admin-primary:disabled {
  background: #8f82ef !important;
  border-color: #8f82ef !important;
  color: #fff !important;
  opacity: .92;
  cursor: not-allowed;
  box-shadow: none;
}
.runtime-settings-head { display: flex; align-items: flex-start; justify-content: space-between; gap: 18px; }
.runtime-settings-head .admin-primary { flex: 0 0 auto; }
.runtime-settings-card h2 { margin: 0 0 8px; }
.runtime-settings-card p, .runtime-settings-card small { color: #7d8491; line-height: 1.7; }
.runtime-settings-card label { display: flex; flex-direction: column; gap: 8px; margin: 20px 0 8px; font-weight: 650; }
.runtime-settings-card input { height: 40px; border: 1px solid #dfe1e6; border-radius: 8px; padding: 0 12px; }
.runtime-settings-card footer { display: flex; justify-content: flex-end; margin-top: 18px; }
.workflow-toolbar > div { display: flex; align-items: center; gap: 12px; }
.workflow-selector { height: 34px; min-width: 176px; border: 1px solid #dfe1e6; border-radius: 8px; padding: 0 10px; background: #fff; color: #2f343d; font-weight: 650; }
.workflow-active-state { color: #596170; white-space: nowrap; }
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
