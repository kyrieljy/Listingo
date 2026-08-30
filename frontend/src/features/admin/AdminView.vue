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
  ApiOutlined, ArrowLeftOutlined, BarChartOutlined, BranchesOutlined, CheckCircleFilled, CodeOutlined, SafetyOutlined,
  CheckOutlined, CloseOutlined, FileTextOutlined, MinusOutlined, PlayCircleOutlined,
  PlusOutlined, SaveOutlined, SettingOutlined, ThunderboltOutlined, UploadOutlined, DashboardOutlined,
} from '@ant-design/icons-vue'
import BrandLogo from '../../components/BrandLogo.vue'
import { api, assistCopywriting, assistVideoCopywriting, userFacingApiErrorMessage } from '../../api/client'
import MonitoringDashboard from './MonitoringDashboard.vue'
import SensitiveWordsPanel from './SensitiveWordsPanel.vue'
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
  providerRouteChainConfigValue,
  providerRouteRoleOrder,
  providerRoutesForCapability,
  providerRuntimeState,
  type ProviderBusinessGroup,
  type ProviderDisplayRecord,
} from './provider-display'

type Provider = ProviderDisplayRecord
const route=useRoute(); const router=useRouter(); const section=computed(()=>String(route.params.section||'providers'))
const providers=ref<Provider[]>([]); const selectedProvider=ref<Provider|null>(null); const providerOpen=ref(false); const apiKey=ref(''); const savingProvider=ref(false)
const providerGroups=ref<any[]>([]); const selectedProviderGroups=ref<Record<string,string>>({}); const routeChainDrafts=ref<Record<string,string[]>>({}); const savingRouteChain=ref(''); const healthResults=ref<Record<string,any[]>>({}); const checkingProviderGroup=ref('')
const prompts=ref<any[]>([]); const promptDetail=ref<any>(null); const promptContent=ref(''); const promptNote=ref(''); const promptViewedVersionId=ref('')
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
const defaultOcrSettings={ocr_engine:'rapidocr',ocr_primary_model:'PP-OCRv5',ocr_fallback_model:'PP-OCRv6',ocr_device:'cpu',ocr_text_score_threshold:0.62,ocr_box_score_threshold:0.6,ocr_short_text_score_threshold:0.86,ocr_min_box_width:5,ocr_min_box_height:5,ocr_min_box_area:40,ocr_filter_isolated_cjk:true,ocr_filter_watermark_text:true,ocr_use_enhanced_variants:false,supported_engines:['paddleocr','rapidocr','auto'],supported_models:['PP-OCRv6','PP-OCRv5','PP-OCRv4','PP-OCRv3'],cache_size:0}
const ocrSettings=ref<any>({...defaultOcrSettings})
const ocrPrewarmResult=ref<any|null>(null)
const savingOcrSettings=ref(false)
const prewarmingOcr=ref(false)
const clearingOcrCache=ref(false)
const ocrEngineOptions=[{value:'paddleocr',label:'PaddleOCR（PP-OCRv6 优先）'},{value:'auto',label:'Auto（PaddleOCR + RapidOCR）'},{value:'rapidocr',label:'RapidOCR 兼容模式'}]
const ocrModelOptions=computed(()=>ocrSettings.value.supported_models?.length?ocrSettings.value.supported_models:defaultOcrSettings.supported_models)
const adminUsers=ref<any[]>([]); const adminPlans=ref<any[]>([]); const adminOrders=ref<any[]>([]); const smsSettings=ref<any>({}); const smsTest=ref({phone:'18928268686',purpose:'login'}); const smsTesting=ref(false); const smsTestResult=ref<any|null>(null); const broadcast=ref({title:'',body:''})
const nav=[{key:'providers',label:'模型配置',icon:ApiOutlined},{key:'ops-monitoring',label:'运维监控',icon:DashboardOutlined},{key:'business-metrics',label:'运营指标监控',icon:BarChartOutlined},{key:'users',label:'用户管理',icon:SettingOutlined},{key:'subscriptions',label:'订阅额度',icon:FileTextOutlined},{key:'payments',label:'支付订单管理',icon:FileTextOutlined},{key:'sms',label:'短信服务',icon:SettingOutlined},{key:'notifications',label:'站内信',icon:FileTextOutlined},{key:'provider-health',label:'中转站健康',icon:ThunderboltOutlined},{key:'workflow',label:'Workflow',icon:BranchesOutlined},{key:'prompts',label:'提示词资产',icon:CodeOutlined},{key:'sensitive-words',label:'敏感词',icon:SafetyOutlined},{key:'ocr',label:'OCR配置',icon:FileTextOutlined},{key:'logs',label:'执行日志',icon:FileTextOutlined},{key:'settings',label:'基础配置',icon:SettingOutlined}]
const sectionTitle=computed(()=>nav.find((item)=>item.key===section.value)?.label||'运营后台')
const adminSectionDescription=computed(()=>section.value==='ops-monitoring'?'按中转站、节点、业务链路和队列状态监控成功率、失败率与耗时':section.value==='business-metrics'?'观察用户画像、核心功能点击率、平台偏好、尺寸偏好、A+ 模块和视频类型表现':section.value==='providers'?'统一配置 LLM 与图片模型，密钥加密保存':section.value==='workflow'?'低代码节点画布、版本与启用校验':section.value==='prompts'?'唯一来源为用户上传 MD；Artflo 提示词不参与执行':section.value==='sensitive-words'?'运营维护敏感词清单与检测开关，覆盖套图、A+ 与视频文本的敏感信息预检':section.value==='ocr'?'管理 OCR 引擎、模型回退、噪声过滤和模型预热':section.value==='settings'?'配置视频 Live 模式所需的公网资源地址':'按任务、节点、模型与状态追踪执行链路')
const adminUserStats=computed(()=>[{label:'用户总数',value:adminUsers.value.length},{label:'管理员',value:adminUsers.value.filter((user)=>user.role==='admin').length},{label:'正常账号',value:adminUsers.value.filter((user)=>user.status==='active').length},{label:'套餐数量',value:adminPlans.value.length}])
const subscriptionStats=computed(()=>[{label:'套餐总数',value:adminPlans.value.length},{label:'前端展示',value:adminPlans.value.filter((plan)=>plan.visible&&!plan.is_internal).length},{label:'内部套餐',value:adminPlans.value.filter((plan)=>plan.is_internal).length},{label:'额度规则',value:adminPlans.value.filter(planShowsQuotaRules).reduce((total,plan)=>total+(plan.quota_rules?.length||0),0)}])
const paymentStats=computed(()=>[{label:'订单总数',value:adminOrders.value.length},{label:'已支付',value:adminOrders.value.filter((order)=>order.status==='paid').length},{label:'待支付',value:adminOrders.value.filter((order)=>order.status==='pending').length}])
const providerCategories=computed(()=>groupProviderCategoriesByBusinessRoute(providers.value,selectedProviderGroups.value))
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
const promptAplusOutputTargets=computed(()=>buildAplusOutputTargets({platform:promptTestInputs.value.platform,market:promptTestInputs.value.market,language:promptTestInputs.value.language,category:String(promptTestInputs.value.category||''),productInfo:promptTestInputs.value.product_info,selectedModules:promptAplusModules.value,outputSpec:promptTestInputs.value.output_spec,advancedTargets:promptTestInputs.value.advanced_targets,dryRun:true}))
const promptAplusSelectedTotal=computed(()=>aplusModuleTotal(promptAplusModules.value))
const promptAiRewriteTargetLabel=computed(()=>promptDetail.value?.code==='content-safety-review'?'审查文本':promptIsAplus.value||promptDetail.value?.code==='product-vision'?'商品信息':'卖点文本')

onMounted(loadSection); watch(section,loadSection)
watch(()=>promptTestInputs.value.platform,()=>{if(promptIsVideo.value){const first=promptRatioChoices.value[0];if(first)promptTestInputs.value.aspect_ratio=first.value}if(!promptAplusAmazon.value&&String(promptTestInputs.value.output_spec).startsWith('amazon_aplus'))promptTestInputs.value.output_spec='1:1'})
onUnmounted(()=>clearPromptTestPoll())
async function loadLogs(){const params:Record<string,string>={};if(logFilters.value.node)params.node=logFilters.value.node;if(logFilters.value.status)params.status=logFilters.value.status;const data=(await api.get('/admin/logs',{params})).data;logs.value=data.items;logTotal.value=data.total}
async function loadSection(){ loading.value=true; try{ if(section.value==='providers'||section.value==='provider-health'){providers.value=(await api.get('/admin/providers')).data;providerGroups.value=(await api.get('/admin/provider-groups')).data} if(section.value==='users'){adminUsers.value=(await api.get('/admin/users')).data;adminPlans.value=(await api.get('/admin/subscription-plans')).data} if(section.value==='subscriptions')adminPlans.value=(await api.get('/admin/subscription-plans')).data; if(section.value==='payments')adminOrders.value=(await api.get('/admin/payment-orders')).data; if(section.value==='sms')smsSettings.value=(await api.get('/admin/sms-settings')).data; if(section.value==='prompts'){prompts.value=(await api.get('/admin/prompts')).data;if(prompts.value[0])await loadPrompt(prompts.value[0].id)} if(section.value==='workflow'){workflows.value=(await api.get('/admin/workflows')).data;if(workflows.value[0])await loadWorkflow(workflows.value[0].id)} if(section.value==='ocr')ocrSettings.value={...defaultOcrSettings,...(await api.get('/admin/ocr-settings')).data}; if(section.value==='logs')await loadLogs(); if(section.value==='settings')runtimeSettings.value=(await api.get('/admin/runtime-settings')).data }catch{message.error('后台数据加载失败，请确认 API 已启动')}finally{loading.value=false}}
function go(key:string){router.push(`/admin/${key}`)}
async function saveAdminUser(user:any){await api.patch(`/admin/users/${user.id}`,{role:user.role,status:user.status,plan_code:user.plan});await loadSection();message.success('用户已保存')}
async function saveAdminPlan(plan:any){await api.patch(`/admin/subscription-plans/${plan.id}`,{name:plan.name,description:plan.description,badge:plan.badge,cta:plan.cta,visible:plan.visible,enabled:plan.enabled,features:plan.features,contact_text:plan.contact_text,contact_phone:plan.contact_phone});await loadSection();message.success('套餐已保存')}
async function saveQuotaRule(rule:any){await api.patch(`/admin/quota-rules/${rule.id}`,{monthly_limit:rule.monthly_limit,cost_multiplier:rule.cost_multiplier,warning_threshold:rule.warning_threshold,enabled:rule.enabled});message.success('额度规则已保存')}
async function saveSmsSettings(){smsSettings.value=(await api.patch('/admin/sms-settings',smsSettings.value)).data;message.success('短信配置已保存')}
function adminApiErrorMessage(error:any,fallback:string){const text=userFacingApiErrorMessage(error);return text==='操作失败，请稍后重试'?fallback:text}
async function testSmsSettings(){if(!smsTest.value.phone.trim())return message.warning('请输入测试手机号');smsTesting.value=true;smsTestResult.value=null;try{const result=(await api.post('/admin/sms-settings/test-send',smsTest.value)).data;smsTestResult.value=result;message.success(result.debug_code?`测试发送成功，调试验证码 ${result.debug_code}`:result.message)}catch(error:any){const text=adminApiErrorMessage(error,'测试发送失败，请检查短信配置');smsTestResult.value={ok:false,message:text};message.error(text)}finally{smsTesting.value=false}}
async function sendBroadcast(){if(!broadcast.value.title.trim())return message.warning('请输入通知标题');const result=(await api.post('/admin/notifications/broadcast',{title:broadcast.value.title,body:broadcast.value.body})).data;broadcast.value={title:'',body:''};message.success(`已发送 ${result.count} 条站内信`)}
function adminPlanOptions(user:any){return adminPlans.value.length?adminPlans.value:[{code:user.plan,name:user.plan}]}
function userInitial(user:any){return String(user.display_name||user.username||user.uid||'用').slice(0,1).toUpperCase()}
function planPriceLabel(plan:any,cycle:'monthly'|'yearly'){if(plan.is_enterprise)return '商务报价';const price=plan.prices?.find((item:any)=>item.billing_cycle===cycle)||plan.prices?.[0];if(!price)return '未配置';if(price.amount_cents===null)return price.price_label||'内部';return price.price_label||`¥${(price.amount_cents/100).toFixed(0)}`}
function planPeriodLabel(plan:any,cycle:'monthly'|'yearly'){if(plan.is_enterprise)return '';const price=plan.prices?.find((item:any)=>item.billing_cycle===cycle)||plan.prices?.[0];return price?.period_label||''}
function quotaLimitLabel(rule:any){return rule.monthly_limit===null||rule.monthly_limit===undefined?'不限':`${rule.monthly_limit}${rule.unit||''}`}
function planMonthlyQuotaTotal(plan:any){const rules=plan.quota_rules||[];if(rules.some((rule:any)=>rule.monthly_limit===null||rule.monthly_limit===undefined))return '不限';return rules.reduce((total:number,rule:any)=>total+Number(rule.monthly_limit||0),0)}
function featurePreview(plan:any){return Array.isArray(plan.features)?plan.features.slice(0,4):[]}
function planToneClass(plan:any){return plan.is_internal?'internal':plan.is_enterprise?'enterprise':plan.code==='advanced'?'advanced':plan.code==='standard'?'standard':'free'}
function planShowsQuotaRules(plan:any){return !plan.is_enterprise&&!plan.is_internal}
function moneyLabel(cents:number|null|undefined){return cents===null||cents===undefined?'企业联系':`¥${(cents/100).toFixed(2)}`}
function billingCycleLabel(cycle:string){return cycle==='yearly'?'年付':cycle==='monthly'?'月付':cycle}
function orderStatusLabel(status:string){return status==='paid'?'已支付':status==='pending'?'待支付':status==='cancelled'?'已取消':status==='expired'?'已过期':status}
function orderStatusClass(status:string){return ['paid','pending','cancelled','expired'].includes(status)?status:'default'}
function formatAdminTime(value:any){if(!value)return '-';const date=new Date(value);return Number.isNaN(date.getTime())?String(value):date.toLocaleString('zh-CN',{hour12:false})}
function providerParameterSchema(provider:Provider|null){const schema=provider?.config?.parameter_schema;return Array.isArray(schema)?schema.filter((item:any)=>item&&item.key):[]}
function providerParameterOptions(parameter:any){return Array.isArray(parameter.options)?parameter.options:[]}
function providerParameterGroups(provider:Provider|null){const schema=providerParameterSchema(provider);const sections=[{key:'core',title:'常用参数',description:'日常只需要关注尺寸、比例、画质、格式等生产指标'},{key:'runtime',title:'运行参数',description:'控制超时、轮询、参考图上限和执行前检查'},{key:'advanced',title:'高级参数',description:'供应商文档里的独有参数；不确定时保持为空'}];return sections.map((section)=>({...section,parameters:schema.filter((parameter:any)=>(parameter.section||'advanced')===section.key)})).filter((section)=>section.parameters.length)}
function parameterDefaultText(parameter:any){if(parameter.default!==undefined){if(parameter.default==='follow_frontend')return '默认：根据前端输入传参';if(parameter.default===true)return '默认：开启';if(parameter.default===false)return '默认：关闭';return `默认：${parameter.default}`}return parameter.optional?'不填：不传该字段，使用中转站默认值':'必填：留空时后端会使用系统默认值'}
function parameterHelpText(parameter:any){const fallback=parameterDefaultText(parameter);return parameter.help?`${parameter.help} ${fallback}`:fallback}
function hasProviderParameterValue(provider:Provider,parameter:any){return Boolean(provider.config&&Object.prototype.hasOwnProperty.call(provider.config,parameter.key))}
function providerParameterValues(provider:Provider){return Object.fromEntries(providerParameterSchema(provider).filter((parameter:any)=>hasProviderParameterValue(provider,parameter)).map((parameter:any)=>[parameter.key,provider.config?.[parameter.key]]))}
function editProvider(provider:Provider){const copied=JSON.parse(JSON.stringify(provider));copied.route_roles=copied.route_roles||{};copied.config=copied.config||{};for(const parameter of providerParameterSchema(copied)){if(copied.config[parameter.key]===undefined&&parameter.default!==undefined)copied.config[parameter.key]=parameter.default}selectedProvider.value=copied;apiKey.value='';providerOpen.value=true}
async function saveProvider(){if(!selectedProvider.value||savingProvider.value)return;const p=selectedProvider.value;savingProvider.value=true;try{await api.patch(`/admin/providers/${p.id}`,{label:p.label,base_url:p.base_url,model_name:p.model_name,enabled:p.enabled,route_roles:p.route_roles,api_key:apiKey.value||undefined,resolution:p.config.resolution,size:p.config.size,quality:p.config.quality,style:p.config.style,format:p.config.format,response_format:p.config.response_format,compression:p.config.compression,timeout_seconds:p.config.timeout_seconds,poll_interval_seconds:p.config.poll_interval_seconds,max_reference_images:p.config.max_reference_images,parameter_values:providerParameterValues(p)});providerOpen.value=false;await loadSection();message.success('模型配置已保存')}catch(error:any){message.error(adminApiErrorMessage(error,'模型配置保存失败，请检查参数'))}finally{savingProvider.value=false}}
async function testProvider(provider:Provider){message.loading({content:`正在测试 ${provider.label}`,key:'provider-test'});try{const result=(await api.post(`/admin/providers/${provider.id}/test`)).data;message[result.ok?'success':'error']({content:result.message,key:'provider-test'})}catch(error:any){message.error({content:adminApiErrorMessage(error,'连通测试失败'),key:'provider-test'})}}
async function toggleProvider(provider:Provider){await api.patch(`/admin/providers/${provider.id}`,{enabled:!provider.enabled});await loadSection()}
function activeProviderGroupValue(group:ProviderBusinessGroup){return selectedProviderGroups.value[group.key]||group.selectedProviderGroup}
function normalizedRouteDraft(codes:string[]){return [...codes,'','','','',''].slice(0,5)}
function initializeRouteChainDraft(group:ProviderBusinessGroup){if(!routeChainDrafts.value[group.key])routeChainDrafts.value={...routeChainDrafts.value,[group.key]:normalizedRouteDraft(group.assignedProviderCodes)}}
function routeChainDraft(group:ProviderBusinessGroup){initializeRouteChainDraft(group);return routeChainDrafts.value[group.key]}
function setRouteChainSlot(group:ProviderBusinessGroup,index:number,event:Event){const next=normalizedRouteDraft(routeChainDraft(group));next[index]=(event.target as HTMLSelectElement).value;routeChainDrafts.value={...routeChainDrafts.value,[group.key]:next}}
function setSelectedProviderGroup(routeKey:string,event:Event){const value=(event.target as HTMLSelectElement).value;selectedProviderGroups.value={...selectedProviderGroups.value,[routeKey]:value};if(value===providerRouteChainConfigValue){const group=providerCategories.value.flatMap((category)=>category.groups).find((item)=>item.key===routeKey);if(group)initializeRouteChainDraft(group)}}
async function saveProviderRouteChain(group:ProviderBusinessGroup){const provider_codes=routeChainDraft(group).filter(Boolean);savingRouteChain.value=group.key;try{await api.patch(`/admin/provider-routes/${group.key}/chain`,{provider_codes});routeChainDrafts.value={...routeChainDrafts.value,[group.key]:normalizedRouteDraft(provider_codes)};await loadSection();message.success('5段主备链路已保存')}catch(error:any){message.error(adminApiErrorMessage(error,'链路保存失败'))}finally{savingRouteChain.value=''}}
async function checkProviderGroup(groupKey:string){checkingProviderGroup.value=groupKey;try{const data=(await api.post(`/admin/provider-groups/${groupKey}/health-check`)).data;healthResults.value={...healthResults.value,[groupKey]:data.results};await loadSection();message.success('中转站健康检查完成')}catch(error:any){message.error(adminApiErrorMessage(error,'中转站健康检查失败'))}finally{checkingProviderGroup.value=''}}
function healthTone(status:any){return status==='ok'?'ready':status==='unknown'?'warning':'failed'}
function healthLabel(status:any){return status==='ok'?'可用':status==='unknown'?'未知':'异常'}
function onRouteRoleChange(routeKey:string,event:Event){if(!selectedProvider.value)return;const value=(event.target as HTMLSelectElement).value;const next={...(selectedProvider.value.route_roles||{})};if(value==='none')delete next[routeKey];else next[routeKey]=value as any;selectedProvider.value.route_roles=next}
async function loadPrompt(id:string){promptDetail.value=(await api.get(`/admin/prompts/${id}`)).data;promptContent.value=promptDetail.value.active_version.content;promptViewedVersionId.value=promptDetail.value.active_version.id;promptNote.value='';await loadPromptTestRuns();promptTestResult.value=promptTestRuns.value[0]||null}
function viewPromptVersion(version:any){promptContent.value=version.content;promptViewedVersionId.value=version.id}
async function savePrompt(){const version=(await api.post(`/admin/prompts/${promptDetail.value.id}/versions`,{content:promptContent.value,change_note:promptNote.value||'后台保存新版本'})).data;await api.post(`/admin/prompts/${promptDetail.value.id}/versions/${version.id}/activate`);await loadPrompt(promptDetail.value.id);message.success('提示词新版本已保存并启用')}
async function uploadPromptFile(event:Event){const input=event.target as HTMLInputElement;const file=input.files?.[0];if(!file||!promptDetail.value)return;const body=new FormData();body.append('file',file);body.append('change_note',promptNote.value||`上传文件：${file.name}`);try{await api.post(`/admin/prompts/${promptDetail.value.id}/versions/upload`,body);await loadPrompt(promptDetail.value.id);message.success('提示词文件已上传为新版本，请在版本历史中选择启用')}catch(error:any){message.error(adminApiErrorMessage(error,'提示词文件上传失败'))}finally{input.value=''}}
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
async function uploadPromptTestAsset(event:Event){const input=event.target as HTMLInputElement;const file=input.files?.[0];if(!file)return;const body=new FormData();body.append('file',file);try{const asset=(await api.post('/assets',body)).data;promptTestAssets.value=[...promptTestAssets.value,asset].slice(-3);message.success('样例商品图已上传')}catch(error:any){message.error(adminApiErrorMessage(error,'样例图上传失败'))}finally{input.value=''}}
function removePromptTestAsset(id:string){promptTestAssets.value=promptTestAssets.value.filter((asset:any)=>asset.id!==id)}
function promptAiTargetValue(){if(promptDetail.value?.code==='content-safety-review')return promptTestInputs.value.text;return promptIsAplus.value||promptDetail.value?.code==='product-vision'?promptTestInputs.value.product_info:promptTestInputs.value.selling_points}
function setPromptAiTargetValue(value:string){if(promptDetail.value?.code==='content-safety-review')promptTestInputs.value.text=value;else if(promptIsAplus.value||promptDetail.value?.code==='product-vision')promptTestInputs.value.product_info=value;else promptTestInputs.value.selling_points=value}
async function runPromptAiWrite(){if(!promptCanAiRewrite.value)return;promptAiWriting.value=true;try{const asset_ids=promptTestAssets.value.map((asset:any)=>asset.id);const text=promptAiTargetValue();const result=promptIsVideo.value?await assistVideoCopywriting({asset_ids,platform:promptTestInputs.value.platform,market:promptTestInputs.value.market,country:promptTestInputs.value.country,language:promptTestInputs.value.language,selling_points:text,video_types:[promptTestInputs.value.video_type],dry_run:false}):await assistCopywriting({asset_ids,platform:promptTestInputs.value.platform,market:promptTestInputs.value.market,language:promptTestInputs.value.language,selling_points:text,dry_run:false});promptAiSuggestion.value=result.selling_points;promptAiSuggestionEditing.value=false;promptAiWriteOpen.value=true}catch(error:any){message.error(adminApiErrorMessage(error,'AI 转写失败，请检查语言模型配置'))}finally{promptAiWriting.value=false}}
async function regeneratePromptAiWrite(){await runPromptAiWrite()}
function applyPromptAiSuggestion(){if(!promptAiSuggestion.value.trim())return message.warning('AI 转写内容为空，请重新生成');setPromptAiTargetValue(promptAiSuggestion.value.trim());promptAiWriteOpen.value=false;promptAiSuggestionEditing.value=false;message.success('AI 转写已确认回填')}
async function runPromptTest(testType:'llm_output'|'full_chain'){if(!promptDetail.value)return;if(testType==='full_chain'&&!promptSupportsFullChain.value){message.warning('当前提示词只支持 LLM 输出测试');return}if(testType==='full_chain'&&!promptTestAssets.value.length){message.warning('完整链路测试至少需要上传一张样例商品图');return}const flag=testType==='full_chain'?promptFullTesting:promptTesting;flag.value=true;try{const run=(await api.post(`/admin/prompts/${promptDetail.value.id}/test-runs`,{test_type:testType,prompt_content:promptContent.value,inputs:promptTestInputsPayload()})).data;promptTestResult.value=run;await loadPromptTestRuns();message.success(testType==='full_chain'?'完整链路测试已开始':'LLM 试跑完成');if(testType==='full_chain')pollPromptTestRun(run.id)}catch(error:any){message.error(adminApiErrorMessage(error,'提示词测试失败'))}finally{flag.value=false}}
async function pollPromptTestRun(id:string){clearPromptTestPoll();try{const run=(await api.get(`/admin/prompt-test-runs/${id}`)).data;promptTestResult.value=run;await loadPromptTestRuns();if(['queued','running'].includes(run.status)){promptTestPollTimer=setTimeout(()=>pollPromptTestRun(id),2000)}else{message[run.status==='succeeded'?'success':'error'](run.status==='succeeded'?'后台测试已完成':run.error||'后台测试失败')}}catch{promptTestPollTimer=setTimeout(()=>pollPromptTestRun(id),3000)}}
function promptTestTypeLabel(type:string){return type==='full_chain'?'完整链路':'LLM 输出'}
function promptTestStatusLabel(status:string){return status==='succeeded'?'成功':status==='failed'?'失败':status==='partial_failed'?'部分失败':status==='running'?'运行中':'排队中'}
function prettyJson(value:any){return JSON.stringify(value??{},null,2)}
function isVideoArtifact(url:string){return /\.(mp4|mov|webm)(\?|$)/i.test(url)}
async function loadWorkflow(id:string){workflowDetail.value=(await api.get(`/admin/workflows/${id}`)).data;const active=workflowDetail.value.versions.find((item:any)=>item.id===workflowDetail.value.active_version_id)||workflowDetail.value.versions[0];nodes.value=active.graph.nodes;edges.value=active.graph.edges}
function onWorkflowSelect(event:Event){const input=event.target as HTMLSelectElement;if(input.value)void loadWorkflow(input.value)}
async function dryrunWorkflow(){const active=activeWorkflowVersion.value;if(!workflowDetail.value||!active)return;const result=(await api.post(`/admin/workflows/${workflowDetail.value.id}/versions/${active.id}/dryrun`)).data;message[result.ok?'success':'error'](result.ok?'Workflow Dryrun 校验通过':result.errors.join('；'))}
function previewWorkflowVersion(version:any){nodes.value=version.graph.nodes;edges.value=version.graph.edges}
async function saveRuntimeSettings(){savingRuntimeSettings.value=true;try{runtimeSettings.value=(await api.patch('/admin/runtime-settings',{public_asset_base_url:runtimeSettings.value.public_asset_base_url})).data;message.success('基础配置已保存到当前运行实例')}catch(error:any){message.error(adminApiErrorMessage(error,'基础配置保存失败'))}finally{savingRuntimeSettings.value=false}}
function ocrSettingsPayload(){const s=ocrSettings.value;return{ocr_engine:s.ocr_engine,ocr_primary_model:s.ocr_primary_model,ocr_fallback_model:s.ocr_fallback_model,ocr_device:s.ocr_device,ocr_text_score_threshold:Number(s.ocr_text_score_threshold),ocr_box_score_threshold:Number(s.ocr_box_score_threshold),ocr_short_text_score_threshold:Number(s.ocr_short_text_score_threshold),ocr_min_box_width:Number(s.ocr_min_box_width),ocr_min_box_height:Number(s.ocr_min_box_height),ocr_min_box_area:Number(s.ocr_min_box_area),ocr_filter_isolated_cjk:Boolean(s.ocr_filter_isolated_cjk),ocr_filter_watermark_text:Boolean(s.ocr_filter_watermark_text),ocr_use_enhanced_variants:Boolean(s.ocr_use_enhanced_variants)}}
async function saveOcrSettings(){savingOcrSettings.value=true;try{ocrSettings.value={...defaultOcrSettings,...(await api.patch('/admin/ocr-settings',ocrSettingsPayload())).data};ocrPrewarmResult.value=null;message.success('OCR 配置已保存，旧模型缓存已清空')}catch(error:any){message.error(adminApiErrorMessage(error,'OCR 配置保存失败'))}finally{savingOcrSettings.value=false}}
async function prewarmOcr(){prewarmingOcr.value=true;try{const data=(await api.post('/admin/ocr-settings/prewarm',undefined,{timeout:180000})).data;ocrSettings.value={...defaultOcrSettings,...data};ocrPrewarmResult.value=data.prewarm;message.success('OCR 模型预热完成')}catch(error:any){message.error(adminApiErrorMessage(error,'OCR 模型预热失败'))}finally{prewarmingOcr.value=false}}
async function clearOcrCache(){clearingOcrCache.value=true;try{ocrSettings.value={...defaultOcrSettings,...(await api.post('/admin/ocr-settings/cache/clear')).data};ocrPrewarmResult.value=null;message.success('OCR 模型缓存已清空')}catch(error:any){message.error(adminApiErrorMessage(error,'OCR 缓存清理失败'))}finally{clearingOcrCache.value=false}}
function ocrPrewarmSummary(){const warmed=ocrPrewarmResult.value?.warmed||[];if(!warmed.length)return '尚未在后台预热';return warmed.map((item:any)=>`${item.engine} ${item.model}: ${item.ok?'成功':'失败'} ${item.elapsed_ms||0}ms`).join(' / ')}
function ocrAutoPrewarmSummary(){const status=ocrSettings.value?.prewarm_status;if(!status||!status.status||status.status==='pending')return '启动后自动预热尚未开始';if(status.status==='skipped_testing')return '测试模式：已跳过自动预热';if(status.status==='running')return '自动预热进行中…';if(status.status==='superseded')return '自动预热已被新配置取代';if(status.status==='failed')return '自动预热失败：'+(status.error||'未知错误');const warmed=(status.result&&status.result.warmed)||[];if(!warmed.length)return '自动预热完成（无可用模型信息）';return '自动预热已完成：'+warmed.map((item:any)=>`${item.engine} ${item.model}: ${item.ok?'成功':'失败'} ${item.elapsed_ms||0}ms`).join(' / ')}
</script>

<template>
  <div class="admin-shell">
    <header class="admin-top"><BrandLogo/><span class="admin-divider"/> <strong>运营后台</strong><div/><button @click="router.push('/app/suite')"><ArrowLeftOutlined/>返回工作台</button></header>
    <aside class="admin-nav"><p>配置中心</p><button v-for="item in nav" :key="item.key" :class="{active:section===item.key}" @click="go(item.key)"><component :is="item.icon"/>{{ item.label }}</button><div class="admin-safe"><CheckCircleFilled/><span><b>Dryrun 已开启</b><small>外部调用默认关闭</small></span></div></aside>
    <main class="admin-main"><div class="admin-title"><div><h1>{{ sectionTitle }}</h1><p>{{ adminSectionDescription }}</p></div><div class="admin-title-actions"><span v-if="loading">加载中…</span></div></div>
      <MonitoringDashboard v-if="section==='ops-monitoring'" kind="ops" />
      <MonitoringDashboard v-else-if="section==='business-metrics'" kind="business" />
      <section v-else-if="section==='users'" class="admin-module-shell">
        <div class="admin-module-hero">
          <div><span>USER ACCESS</span><h2>用户与身份</h2><p>角色、账号状态和套餐归属集中管理，管理员可为内部测试账号分配 Internal。</p></div>
          <div class="admin-hero-metrics"><article v-for="stat in adminUserStats" :key="stat.label"><small>{{ stat.label }}</small><b>{{ stat.value }}</b></article></div>
        </div>
        <div class="admin-table-card">
          <table class="admin-data-table">
            <thead><tr><th>用户</th><th>手机号</th><th>角色</th><th>状态</th><th>套餐</th><th></th></tr></thead>
            <tbody>
              <tr v-for="user in adminUsers" :key="user.id">
                <td><div class="admin-user-cell"><i>{{ userInitial(user) }}</i><span><b>{{ user.display_name }}</b><small>{{ user.uid }} / {{ user.username || '未设置用户名' }}</small></span></div></td>
                <td><span class="admin-muted-text">{{ user.phone_masked }}</span></td>
                <td><select v-model="user.role" class="admin-compact-select"><option value="user">普通用户</option><option value="admin">管理员</option></select></td>
                <td><select v-model="user.status" class="admin-compact-select"><option value="active">正常</option><option value="disabled">停用</option></select></td>
                <td><select v-model="user.plan" class="admin-compact-select plan"><option v-for="plan in adminPlanOptions(user)" :key="plan.code" :value="plan.code">{{ plan.name }}</option></select></td>
                <td><button class="admin-soft-button" @click="saveAdminUser(user)">保存</button></td>
              </tr>
            </tbody>
          </table>
        </div>
      </section>
      <section v-else-if="section==='subscriptions'" class="admin-module-shell">
        <div class="admin-module-hero">
          <div><span>PLANS & QUOTAS</span><h2>订阅额度管理</h2><p>套餐文案、展示开关、企业联系信息和每个业务动作的月额度都在这里维护。</p></div>
          <div class="admin-hero-metrics"><article v-for="stat in subscriptionStats" :key="stat.label"><small>{{ stat.label }}</small><b>{{ stat.value }}</b></article></div>
        </div>
        <section class="admin-plan-board">
          <article v-for="plan in adminPlans" :key="plan.id" :class="['admin-plan-card', 'tone-' + planToneClass(plan)]">
            <header class="admin-plan-card-head">
              <div class="admin-plan-kicker"><span>{{ plan.code }}</span><em v-if="plan.badge">{{ plan.badge }}</em><em v-if="plan.is_internal">内部</em></div>
              <input v-model="plan.name" class="admin-plan-name-input" aria-label="套餐名称" />
              <p>{{ plan.description || '未填写套餐描述' }}</p>
              <div class="admin-plan-price-row">
                <strong>{{ planPriceLabel(plan,'monthly') }}<small>{{ planPeriodLabel(plan,'monthly') }}</small></strong>
                <span>{{ planPriceLabel(plan,'yearly') }}{{ planPeriodLabel(plan,'yearly') }}</span>
              </div>
              <div class="admin-plan-flags">
                <label class="admin-switch"><input v-model="plan.enabled" type="checkbox" /><span></span>启用</label>
                <label class="admin-switch"><input v-model="plan.visible" type="checkbox" /><span></span>前端展示</label>
              </div>
            </header>
            <div class="admin-plan-fields">
              <label>套餐描述<textarea v-model="plan.description" rows="3"></textarea></label>
              <div>
                <label>角标<input v-model="plan.badge" /></label>
                <label>按钮文案<input v-model="plan.cta" /></label>
              </div>
              <template v-if="plan.is_enterprise">
                <label>企业联系方式<input v-model="plan.contact_phone" placeholder="企业版可填写手机号或微信" /></label>
                <label>企业联系文案<textarea v-model="plan.contact_text" rows="3" placeholder="企业定制、团队账号、私有化部署、专属支持等"></textarea></label>
              </template>
            </div>
            <div v-if="featurePreview(plan).length" class="admin-feature-row"><span v-for="feature in featurePreview(plan)" :key="feature">{{ feature }}</span></div>
            <button class="admin-save-button" @click="saveAdminPlan(plan)">保存套餐</button>
            <section v-if="planShowsQuotaRules(plan)" class="admin-quota-stack">
              <header><b>额度规则</b><small>月总额 {{ planMonthlyQuotaTotal(plan) }}</small></header>
              <div v-for="rule in plan.quota_rules" :key="rule.id" class="admin-quota-row" :class="{off:!rule.enabled}">
                <div class="admin-quota-row-head">
                  <div class="admin-quota-title"><b>{{ rule.action_label }}</b><small>{{ quotaLimitLabel(rule) }} / {{ rule.action_key }}</small></div>
                  <div class="admin-quota-actions">
                    <label class="admin-mini-switch" title="启用额度规则"><input v-model="rule.enabled" type="checkbox" /><span></span></label>
                    <button class="admin-text-button" @click="saveQuotaRule(rule)">保存</button>
                  </div>
                </div>
                <div class="admin-quota-controls">
                  <label><span>月额度</span><input v-model.number="rule.monthly_limit" type="number" min="0" /></label>
                  <label><span>倍率</span><input v-model.number="rule.cost_multiplier" type="number" min="1" max="100" /></label>
                  <label><span>告警%</span><input v-model.number="rule.warning_threshold" type="number" min="1" max="100" /></label>
                </div>
              </div>
            </section>
          </article>
        </section>
      </section>
      <section v-else-if="section==='payments'" class="admin-module-shell">
        <div class="admin-module-hero">
          <div><span>PAYMENT ORDERS</span><h2>支付订单管理</h2><p>集中查看订阅订单、支付状态、套餐绑定和支付消息触发情况。</p></div>
          <div class="admin-hero-metrics"><article v-for="stat in paymentStats" :key="stat.label"><small>{{ stat.label }}</small><b>{{ stat.value }}</b></article></div>
        </div>
        <div class="admin-table-card">
          <table class="admin-data-table">
            <thead><tr><th>订单号</th><th>套餐</th><th>周期</th><th>金额</th><th>状态</th><th>创建时间</th></tr></thead>
            <tbody><tr v-for="order in adminOrders" :key="order.id"><td><code>{{ order.order_no }}</code></td><td><b>{{ order.plan_name }}</b><small>{{ order.plan_code }}</small></td><td>{{ billingCycleLabel(order.billing_cycle) }}</td><td>{{ moneyLabel(order.amount_cents) }}</td><td><span :class="['admin-status-pill','order-'+orderStatusClass(order.status)]">{{ orderStatusLabel(order.status) }}</span></td><td>{{ formatAdminTime(order.created_at) }}</td></tr></tbody>
          </table>
        </div>
      </section>
      <section v-else-if="section==='sms'" class="admin-module-shell">
        <div class="admin-module-hero">
          <div><span>ALIYUN SMS</span><h2>短信服务配置</h2><p>支持普通短信 SendSms 和号码认证 PNVS；当前推荐使用 PNVS 赠送签名和模板。</p></div>
          <div class="admin-service-state" :class="{on:smsSettings.enabled}"><i></i><span>{{ smsSettings.enabled ? '短信已启用' : '短信已关闭' }}</span></div>
        </div>
        <div class="admin-sms-guide">
          <article><b>1. Provider</b><p><code>aliyun_pnvs</code> 会调用号码认证服务的 SendSmsVerifyCode。</p></article>
          <article><b>2. 签名名称</b><p>PNVS 填赠送签名，例如 <code>速通互联验证码</code>；普通短信填短信服务签名。</p></article>
          <article><b>3. 模板 CODE</b><p>PNVS 模板通常是 <code>100001</code>；普通短信模板通常是 <code>SMS_...</code>。</p></article>
          <article><b>4. AccessKey</b><p>填写已授权号码认证服务的 RAM AccessKey。Secret 保存后加密存储，不会在后台明文展示。</p></article>
        </div>
        <div class="admin-settings-grid">
          <article class="admin-settings-panel compact">
            <header><span>服务状态</span><b>验证码通道</b></header>
            <label class="admin-provider-select">服务类型<select v-model="smsSettings.provider"><option value="aliyun_pnvs">号码认证 PNVS</option><option value="aliyun">普通短信 SendSms</option></select><small>{{ smsSettings.provider === 'aliyun_pnvs' ? '使用赠送签名 + 100001 等模板号' : '使用短信服务签名 + SMS_ 开头模板' }}</small></label>
            <label class="admin-toggle-row"><input v-model="smsSettings.enabled" type="checkbox" /><span><b>启用短信服务</b><small>关闭后仅调试环境可返回验证码</small></span></label>
            <label class="admin-toggle-row"><input v-model="smsSettings.debug_mode" type="checkbox" /><span><b>调试模式</b><small>用于本地和测试环境联调</small></span></label>
          </article>
          <article class="admin-settings-panel">
            <header><span>阿里云参数</span><b>AccessKey 与签名</b></header>
            <div class="admin-field-grid"><label>RegionId<input v-model="smsSettings.region_id" placeholder="cn-hangzhou" /><small>国内短信一般保持 cn-hangzhou</small></label><label>SignName 签名名称<input v-model="smsSettings.sign_name" :placeholder="smsSettings.provider === 'aliyun_pnvs' ? '速通互联验证码' : '已审核通过的短信签名'" /><small>{{ smsSettings.provider === 'aliyun_pnvs' ? 'PNVS 赠送签名，例如速通互联验证码' : '不是登录名称，必须和签名管理里完全一致' }}</small></label><label>AccessKey ID<input v-model="smsSettings.access_key_id" placeholder="RAM 用户 AccessKey ID" /><small>不是账号登录名</small></label><label>AccessKey Secret<input v-model="smsSettings.access_key_secret" type="password" placeholder="创建 AccessKey 时保存的 Secret" /><small>{{ smsSettings.has_access_key_secret ? '已保存 Secret；不修改可留空' : '必填，保存后后台加密存储' }}</small></label></div>
          </article>
          <article class="admin-settings-panel wide">
            <header><span>模板与频控</span><b>验证码策略</b></header>
            <div class="admin-field-grid four"><label>登录模板 CODE<input v-model="smsSettings.login_template_code" :placeholder="smsSettings.provider === 'aliyun_pnvs' ? '100001' : 'SMS_xxxxxxxxx'" /><small>登录、注册默认用它</small></label><label>注册模板 CODE<input v-model="smsSettings.register_template_code" :placeholder="smsSettings.provider === 'aliyun_pnvs' ? '100001' : '可和登录模板相同'" /><small>留空时回退到登录模板</small></label><label>换绑模板 CODE<input v-model="smsSettings.change_phone_template_code" :placeholder="smsSettings.provider === 'aliyun_pnvs' ? '100002' : '可和登录模板相同'" /><small>留空时回退到登录模板</small></label><label>管理员模板 CODE<input v-model="smsSettings.admin_template_code" :placeholder="smsSettings.provider === 'aliyun_pnvs' ? '100005' : '管理员首登验证码模板'" /><small>留空时回退到登录模板</small></label><label>任务通知模板 CODE<input v-model="smsSettings.notify_template_code" :placeholder="smsSettings.provider === 'aliyun_pnvs' ? '100006' : '任务完成通知模板 SMS_'" /><small>任务完成通知短信模板；留空则不发通知短信</small></label><label>验证码有效期<input v-model.number="smsSettings.code_ttl_seconds" type="number" /><small>单位：秒；PNVS 会同步传 ValidTime</small></label><label>发送冷却<input v-model.number="smsSettings.cooldown_seconds" type="number" /><small>单位：秒，同手机号同用途</small></label><label>单日上限<input v-model.number="smsSettings.daily_limit_per_phone" type="number" /><small>同手机号 24 小时内上限</small></label></div>
          </article>
        </div>
        <article class="admin-sms-test-panel">
          <header><span>发送测试</span><b>测试验证码是否生效</b><small>这里走和前台登录一致的发送链路。调试模式会返回验证码；真实模式会调用阿里云短信接口。</small></header>
          <div class="admin-sms-test-form">
            <label>测试手机号<input v-model="smsTest.phone" placeholder="18928268686" /></label>
            <label>验证码用途<select v-model="smsTest.purpose"><option value="login">登录</option><option value="register">注册</option><option value="change_phone">换绑手机号</option><option value="admin">管理员验证</option></select></label>
            <button class="admin-primary" :disabled="smsTesting" @click="testSmsSettings">{{ smsTesting ? '发送中...' : '发送测试验证码' }}</button>
          </div>
          <p v-if="smsTestResult" :class="{error:!smsTestResult.ok}">{{ smsTestResult.ok ? (smsTestResult.debug_code ? `测试成功，调试验证码：${smsTestResult.debug_code}` : smsTestResult.message) : smsTestResult.message }}</p>
        </article>
        <div class="admin-footer-actions"><button class="admin-primary" @click="saveSmsSettings">保存短信配置</button></div>
      </section>
      <section v-else-if="section==='notifications'" class="admin-module-shell">
        <div class="admin-module-hero">
          <div><span>MESSAGE CENTER</span><h2>站内信管理</h2><p>用于注册欢迎、批量进度、支付状态、订阅变更、额度告急和管理员通知。</p></div>
        </div>
        <div class="admin-broadcast-layout">
          <article class="admin-composer-panel">
            <header><span>广播通知</span><b>发送给全部用户</b></header>
            <label>通知标题<input v-model="broadcast.title" placeholder="例如：系统维护通知" /></label>
            <label>通知内容<textarea v-model="broadcast.body" rows="7" placeholder="填写站内信正文"></textarea></label>
            <button class="admin-primary" @click="sendBroadcast">发送站内信</button>
          </article>
          <aside class="admin-preview-panel">
            <span>通知预览</span>
            <h3>{{ broadcast.title || '通知标题' }}</h3>
            <p>{{ broadcast.body || '站内信正文会出现在这里。' }}</p>
            <dl><div><dt>发送对象</dt><dd>全部用户</dd></div><div><dt>状态</dt><dd>未读提醒</dd></div></dl>
          </aside>
        </div>
      </section>
      <section v-else-if="section==='providers'" class="provider-page">
        <div class="provider-activation-note"><CheckCircleFilled/><div><b>Provider 生效条件</b><p>启用开关只是允许调用；还必须配置 API Key，模型才会显示“当前生效”。Live 任务只会调用下方业务分组中已生效的模型。</p><ul class="provider-state-legend"><li class="ready">当前生效：启用且密钥已配置</li><li class="warning">缺少密钥：已启用但无法调用</li><li class="off">未启用：不会进入 Live 链路</li></ul></div></div>
        <section v-for="category in providerCategories" :key="category.key" class="provider-category" :class="`provider-category-${category.key}`">
          <header class="provider-category-head"><h2>{{ category.title }}</h2><p>{{ category.key==='suite'?'套图大板块模型链路':category.key==='aplus'?'A+ 详情页模型链路':'独立模型链路' }}</p></header>
          <section v-for="group in category.groups" :key="group.key" class="provider-group" :class="`provider-group-${group.key}`">
            <header class="provider-group-head"><div><span>{{ group.title }}</span><div><h2>{{ group.categoryKey===group.key?group.title:`${group.categoryTitle} / ${group.title}` }}</h2><p>{{ group.description }}</p></div></div><aside><label class="provider-group-filter">中转站<select :value="activeProviderGroupValue(group)" @change="setSelectedProviderGroup(group.key,$event)"><option v-for="providerGroup in group.providerGroups" :key="providerGroup.key" :value="providerGroup.key">{{ providerGroup.label }} · {{ providerGroup.count }}</option><option :value="providerRouteChainConfigValue">配置5段链路</option></select></label><em :class="{ready:group.ready}">{{ group.statusLabel }}</em></aside></header>
            <div class="provider-route-strip"><span>实际调用顺序</span><b :title="group.routeModels">{{ group.routeModels }}</b></div>
            <section v-if="group.selectionMode==='chain_config'" class="provider-chain-editor">
              <header><b>5段主备链路</b><small>保存后真实任务按主模型、备1、备2、备3、备4顺序检测并执行。</small></header>
              <div class="provider-chain-flow">
                <label v-for="(role,index) in providerRouteRoleOrder" :key="role" class="provider-chain-node">
                  <span class="provider-chain-index">{{ index + 1 }}</span>
                  <b>{{ role==='primary'?'主模型':`备${role.replace('backup','')}` }}</b>
                  <select :value="routeChainDraft(group)[index]||''" @change="setRouteChainSlot(group,index,$event)">
                    <option value="">未配置</option>
                    <option v-for="candidate in group.chainCandidates" :key="candidate.code" :value="candidate.code">{{ candidate.provider_group_label || candidate.provider_group }} / {{ candidate.label }}</option>
                  </select>
                </label>
              </div>
              <footer><button class="admin-primary" :disabled="savingRouteChain===group.key" @click="saveProviderRouteChain(group)"><SaveOutlined/>{{ savingRouteChain===group.key?'保存中...':'保存5段链路' }}</button></footer>
            </section>
            <div class="provider-grid"><article v-for="provider in group.providers" :key="provider.id" class="provider-card" :class="`runtime-${providerRuntimeState(provider).tone}`">
              <div class="provider-head"><span><ApiOutlined/></span><div><h3>{{ provider.label }}</h3><p>{{ provider.model_name }}</p></div><button class="toggle" :class="{on:provider.enabled}" :aria-label="`${provider.enabled?'停用':'启用'} ${provider.label}`" :title="provider.enabled?'点击停用 Provider':'点击启用 Provider'" @click="toggleProvider(provider)"/></div>
              <div class="provider-runtime" :class="providerRuntimeState(provider).tone"><i/><span><b>{{ providerRuntimeState(provider).label }}</b><small>{{ providerRuntimeState(provider).detail }}</small></span></div>
            <div class="provider-badges"><em class="business-role">{{ provider.role }}</em><em>{{ provider.provider_group_label||'中转站' }}</em><em>{{ provider.supports_exact_custom_size?'精确 size':provider.supports_custom_size?'比例枚举':'size 未确认' }}</em><em v-if="provider.operation==='edit'||provider.supports_edit">edit</em><em>{{ provider.capability==='llm'?'语言模型':provider.capability==='video'?'视频模型':'图片模型' }}</em><em :class="provider.has_api_key?'key-ok':'key-empty'">{{ provider.has_api_key?'密钥已配置':'无密钥' }}</em></div>
              <dl><div><dt>端点</dt><dd>{{ provider.base_url }}</dd></div><div><dt>适配器</dt><dd>{{ provider.adapter }} · {{ provider.operation||'operation' }}</dd></div><div><dt>默认参数</dt><dd>{{ provider.config.resolution||provider.config.size_param_mode||provider.config.size||'JSON' }} · {{ provider.config.timeout_seconds }}s</dd></div><div><dt>成本/健康</dt><dd>{{ provider.pricing?.cost ?? '待压测' }} {{ provider.pricing?.unit || '' }} · {{ healthLabel(provider.health?.status) }}</dd></div></dl>
              <footer><button @click="testProvider(provider)"><PlayCircleOutlined/>连通测试</button><button class="edit" @click="editProvider(provider)"><SettingOutlined/>配置</button></footer>
            </article><div v-if="!group.providers.length" class="provider-empty-route"><SettingOutlined/><span>未配置{{ group.categoryKey===group.key?group.title:`${group.categoryTitle} / ${group.title}` }}链路</span></div></div>
          </section>
        </section>
      </section>
      <section v-else-if="section==='provider-health'" class="provider-page provider-health-page">
        <div class="provider-activation-note"><ThunderboltOutlined/><div><b>中转站健康检查</b><p>按中转站执行非计费连通检查；异常标红，无法非计费确认模型目录的供应商显示未知，不会发起真实生成任务。</p></div></div>
        <section class="provider-health-grid">
          <article v-for="group in providerGroups" :key="group.key" class="provider-health-card">
            <header><div><h2>{{ group.label }}</h2><p>{{ group.website }}</p></div><button :disabled="checkingProviderGroup===group.key" @click="checkProviderGroup(group.key)"><PlayCircleOutlined/>{{ checkingProviderGroup===group.key?'检查中':'检查' }}</button></header>
            <div class="provider-health-stats"><span>模型 {{ group.provider_count }}</span><span>启用 {{ group.enabled_count }}</span><span>密钥 {{ group.keyed_count }}</span></div>
            <table><thead><tr><th>模型</th><th>能力</th><th>成本</th><th>状态</th></tr></thead><tbody><tr v-for="result in (healthResults[group.key]||providers.filter((provider)=>provider.provider_group===group.key))" :key="result.code" :class="`health-${healthTone(result.status||result.health?.status)}`"><td><b>{{ result.label }}</b><small>{{ result.model_name }}</small></td><td>{{ result.operation }} · {{ result.supports_exact_custom_size?'精确size':result.supports_custom_size?'比例枚举':'' }} {{ result.supports_edit?'edit':'' }}</td><td>{{ result.pricing?.cost ?? '待压测' }} {{ result.pricing?.unit || '' }}</td><td><em>{{ healthLabel(result.status||result.health?.status) }}</em><small>{{ result.message||result.health?.message }}</small></td></tr></tbody></table>
          </article>
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
          <article v-for="version in promptDetail?.versions" :key="version.id" :class="{active:version.id===promptDetail.active_version_id, selected:version.id===promptViewedVersionId}"><button @click="viewPromptVersion(version)" :aria-selected="version.id===promptViewedVersionId"><b>v{{ version.version_no }}<i v-if="version.id===promptDetail.active_version_id">当前生效</i></b><small>{{ version.change_note }}</small><em>{{ version.content_sha256.slice(0,10) }}…</em></button><button v-if="version.id!==promptDetail.active_version_id" class="activate-version" @click="activatePrompt(version)">启用此版本</button></article>
        </aside>
      </section>
      <section v-else-if="section==='ocr'" class="runtime-settings-card ocr-settings-card">
        <header class="runtime-settings-head"><div><h2>OCR 配置</h2><p>默认主路径为 RapidOCR；需要 PaddleOCR 时可手动切换，并保留 PP-OCRv5 / PP-OCRv6 模型配置。</p></div><span class="ocr-cache-pill">缓存 {{ ocrSettings.cache_size || 0 }}</span></header>
        <div class="ocr-form-grid">
          <label>OCR 引擎<select v-model="ocrSettings.ocr_engine"><option v-for="item in ocrEngineOptions" :key="item.value" :value="item.value">{{ item.label }}</option></select></label>
          <label>主模型<select v-model="ocrSettings.ocr_primary_model"><option v-for="model in ocrModelOptions" :key="model" :value="model">{{ model }}</option></select></label>
          <label>回退模型<select v-model="ocrSettings.ocr_fallback_model"><option v-for="model in ocrModelOptions" :key="model" :value="model">{{ model }}</option></select></label>
          <label>推理设备<input v-model="ocrSettings.ocr_device" placeholder="cpu"/></label>
          <label>识别分数阈值<input v-model.number="ocrSettings.ocr_text_score_threshold" type="number" min="0" max="1" step="0.01"/></label>
          <label>检测框阈值<input v-model.number="ocrSettings.ocr_box_score_threshold" type="number" min="0" max="1" step="0.01"/></label>
          <label>短文本阈值<input v-model.number="ocrSettings.ocr_short_text_score_threshold" type="number" min="0" max="1" step="0.01"/></label>
          <label>最小框宽<input v-model.number="ocrSettings.ocr_min_box_width" type="number" min="0"/></label>
          <label>最小框高<input v-model.number="ocrSettings.ocr_min_box_height" type="number" min="0"/></label>
          <label>最小框面积<input v-model.number="ocrSettings.ocr_min_box_area" type="number" min="0"/></label>
        </div>
        <div class="ocr-switches">
          <label><input v-model="ocrSettings.ocr_filter_isolated_cjk" type="checkbox"/>过滤英文任务中的孤立中文单字</label>
          <label><input v-model="ocrSettings.ocr_filter_watermark_text" type="checkbox"/>过滤水印区域噪声</label>
          <label><input v-model="ocrSettings.ocr_use_enhanced_variants" type="checkbox"/>启用增强图二次 OCR</label>
        </div>
        <div class="ocr-prewarm-state"><b>启动自动预热</b><span>{{ ocrAutoPrewarmSummary() }}</span></div>
        <div class="ocr-prewarm-state"><b>手动预热</b><span>{{ ocrPrewarmSummary() }}</span></div>
        <footer class="ocr-actions"><button type="button" :disabled="prewarmingOcr" @click="prewarmOcr"><PlayCircleOutlined/>{{ prewarmingOcr ? '预热中...' : '重新预热' }}</button><button type="button" :disabled="clearingOcrCache" @click="clearOcrCache"><CloseOutlined/>{{ clearingOcrCache ? '清理中...' : '清空缓存' }}</button><button class="admin-primary" :disabled="savingOcrSettings" @click="saveOcrSettings"><SaveOutlined/>{{ savingOcrSettings ? '保存中...' : '保存 OCR 配置' }}</button></footer>
      </section>
      <SensitiveWordsPanel v-else-if="section==='sensitive-words'" />
      <section v-else-if="section==='logs'" class="logs-card"><div class="log-filters"><select v-model="logFilters.node"><option value="">全部节点</option><option value="image_generate">image_generate</option><option value="meta_prompt">meta_prompt</option><option value="video_meta_prompt">video_meta_prompt</option><option value="video_submit">video_submit</option><option value="video_generate">video_generate</option></select><select v-model="logFilters.status"><option value="">全部状态</option><option value="succeeded">succeeded</option><option value="failed">failed</option></select><button class="admin-primary" :disabled="loading" @click="loadLogs">筛选</button><span>共 {{ logTotal }} 条</span></div><table><thead><tr><th>时间</th><th>任务 / 节点</th><th>状态</th><th>耗时</th><th>请求摘要</th><th>错误</th></tr></thead><tbody><tr v-for="log in logs" :key="log.id"><td>{{ new Date(log.created_at).toLocaleString() }}</td><td><b>{{ log.node }}</b><small>{{ log.job_id?.slice(0,8) }}</small></td><td><em :class="log.status">{{ log.status }}</em></td><td>{{ log.duration_ms??0 }} ms</td><td><code>{{ JSON.stringify(log.request_summary).slice(0,90) }}</code></td><td>{{ log.error||'—' }}</td></tr></tbody></table></section>
      <section v-else class="runtime-settings-card"><header class="runtime-settings-head"><div><h2>基础配置</h2><p>视频 Live 模式需要公网可访问的资源地址，Seedance 会通过这个地址读取已上传商品图。</p></div></header><label>PUBLIC_ASSET_BASE_URL<input v-model="runtimeSettings.public_asset_base_url" placeholder="https://your-domain.com"/></label><small>正式部署建议配置环境变量 LISTINGO_PUBLIC_ASSET_BASE_URL；这里保存只作用于当前后端运行实例。</small><footer><button class="admin-primary" :disabled="savingRuntimeSettings" @click="saveRuntimeSettings"><SaveOutlined/>{{ savingRuntimeSettings ? '保存中...' : '保存基础配置' }}</button></footer></section>
    </main>
    <a-drawer v-model:open="providerOpen" title="模型配置" width="480">
      <div v-if="selectedProvider" class="provider-form">
        <label>名称<input v-model="selectedProvider.label"/></label>
        <label>模型名<input v-model="selectedProvider.model_name"/></label>
        <label>API 端点<input v-model="selectedProvider.base_url"/></label>
        <label>API Key<input v-model="apiKey" type="password" :placeholder="selectedProvider.api_key_masked||'手工录入，不自动复制'"/></label>
        <div v-if="providerParameterSchema(selectedProvider).length" class="provider-parameter-editor">
          <section v-for="parameterGroup in providerParameterGroups(selectedProvider)" :key="parameterGroup.key" class="provider-parameter-section">
            <template v-if="parameterGroup.key==='core'">
              <header><b>{{ parameterGroup.title }}</b><small>{{ parameterGroup.description }}</small></header>
              <label v-for="parameter in parameterGroup.parameters" :key="parameter.key" :class="{check:parameter.type==='boolean'}">
                <template v-if="parameter.type==='boolean'">
                  <input v-model="selectedProvider.config[parameter.key]" type="checkbox"/>{{ parameter.label }}
                </template>
                <template v-else>
                  <span>{{ parameter.label }}</span>
                  <select v-if="parameter.type==='select'" v-model="selectedProvider.config[parameter.key]">
                    <option v-if="parameter.optional" value="">不传，使用中转站默认</option>
                    <option v-for="option in providerParameterOptions(parameter)" :key="option.value" :value="option.value">{{ option.label }}</option>
                  </select>
                  <input v-else-if="parameter.type==='number'" v-model.number="selectedProvider.config[parameter.key]" type="number" :min="parameter.min" :max="parameter.max" :step="parameter.step||1" :placeholder="parameter.optional?'不填=中转默认':''"/>
                  <input v-else v-model="selectedProvider.config[parameter.key]" :placeholder="parameter.optional?'不填=中转默认':''"/>
                </template>
                <small>{{ parameterHelpText(parameter) }}</small>
                <small v-if="parameter.key==='size' && selectedProvider.config[parameter.key] && !['follow_frontend','follow_ratio','auto'].includes(String(selectedProvider.config[parameter.key]))" class="image2-size-warning">当前为固定尺寸，会覆盖前端尺寸参数。</small>
              </label>
            </template>
            <details v-else>
              <summary><span>{{ parameterGroup.title }}</span><small>{{ parameterGroup.description }}</small></summary>
              <label v-for="parameter in parameterGroup.parameters" :key="parameter.key" :class="{check:parameter.type==='boolean'}">
                <template v-if="parameter.type==='boolean'">
                  <input v-model="selectedProvider.config[parameter.key]" type="checkbox"/>{{ parameter.label }}
                </template>
                <template v-else>
                  <span>{{ parameter.label }}</span>
                  <select v-if="parameter.type==='select'" v-model="selectedProvider.config[parameter.key]">
                    <option v-if="parameter.optional" value="">不传，使用中转站默认</option>
                    <option v-for="option in providerParameterOptions(parameter)" :key="option.value" :value="option.value">{{ option.label }}</option>
                  </select>
                  <input v-else-if="parameter.type==='number'" v-model.number="selectedProvider.config[parameter.key]" type="number" :min="parameter.min" :max="parameter.max" :step="parameter.step||1" :placeholder="parameter.optional?'不填=中转默认':''"/>
                  <input v-else v-model="selectedProvider.config[parameter.key]" :placeholder="parameter.optional?'不填=中转默认':''"/>
                </template>
                <small>{{ parameterHelpText(parameter) }}</small>
                <small v-if="parameter.key==='size' && selectedProvider.config[parameter.key] && !['follow_frontend','follow_ratio','auto'].includes(String(selectedProvider.config[parameter.key]))" class="image2-size-warning">当前为固定尺寸，会覆盖前端尺寸参数。</small>
              </label>
            </details>
          </section>
        </div>
        <div class="provider-route-role-editor">
          <b>业务链路角色</b>
          <label v-for="routeItem in selectedProviderRoutes" :key="routeItem.key">
            <span>{{ routeItem.categoryTitle }} / {{ routeItem.title }}</span>
            <select :value="selectedProvider.route_roles?.[routeItem.key] || 'none'" @change="onRouteRoleChange(routeItem.key, $event)">
              <option value="none">不参与</option>
              <option v-for="role in providerRouteRoleOrder" :key="role" :value="role">{{ role==='primary'?'主模型':`备${role.replace('backup','')}` }}</option>
            </select>
          </label>
          <small>同一链路每个槽位只能有一个模型；保存后会自动替换同链路同角色的其他 Provider。</small>
        </div>
        <label class="check"><input v-model="selectedProvider.enabled" type="checkbox"/>启用 Provider</label>
        <p class="provider-enable-help">勾选只代表允许任务调用；还需要保存有效 API Key，并在业务链路角色中配置为主模型或备用模型，卡片才会显示“当前生效”。</p>
        <p>“连通测试”只验证密钥与模型目录，不计费生图；真实图像冒烟测试需显式运行后端脚本。</p>
        <button class="admin-primary full" :disabled="savingProvider" @click="saveProvider">{{ savingProvider ? '保存中...' : '保存配置' }}</button>
      </div>
    </a-drawer>
  </div>
</template>

<style>
.admin-shell button { border: 0; background: none; }
.provider-form select { height: 38px; border: 1px solid #dfe1e6; border-radius: 8px; padding: 0 10px; background: #fff; }
.provider-form label > small { color: #979da7; line-height: 1.5; }
.provider-form .image2-size-warning { color: #d46b08; background: #fff7e6; border: 1px solid #ffe1ad; border-radius: 7px; padding: 7px 9px; }
.provider-parameter-editor,.provider-chain-editor { display: grid; gap: 10px; border: 1px solid #e5e7ee; border-radius: 11px; padding: 12px; background: #fafbff; }
.provider-parameter-section { display: grid; gap: 10px; padding: 10px; border: 1px solid #edf0f6; border-radius: 9px; background: #fff; }
.provider-parameter-section header { display: flex; justify-content: space-between; gap: 12px; align-items: flex-start; }
.provider-parameter-section header b,.provider-parameter-section summary span,.provider-chain-editor b { color: #2f343d; font-size: 12px; font-weight: 800; }
.provider-parameter-section header small,.provider-parameter-section summary small { color: #8991a0; font-size: 10px; line-height: 1.45; text-align: right; }
.provider-parameter-section details { display: grid; gap: 10px; }
.provider-parameter-section details[open] { gap: 10px; }
.provider-parameter-section summary { cursor: pointer; display: flex; justify-content: space-between; gap: 12px; align-items: flex-start; list-style: none; }
.provider-parameter-section summary::-webkit-details-marker { display: none; }
.provider-parameter-section summary:before { content: "›"; color: #7f88a0; font-size: 16px; line-height: 14px; transition: transform .16s ease; }
.provider-parameter-section details[open] summary:before { transform: rotate(90deg); }
.provider-parameter-section summary span { margin-right: auto; }
.provider-parameter-editor label,.provider-chain-editor label { display: grid; gap: 7px; margin: 0!important; }
.provider-parameter-editor label.check { display: flex!important; align-items: center; gap: 8px; color: #343a46; }
.provider-parameter-editor label.check input { width: 16px; height: 16px; }
.provider-chain-editor header { display: flex; align-items: baseline; justify-content: space-between; gap: 12px; }
.provider-chain-editor header small { color: #7f8794; line-height: 1.5; }
.provider-chain-editor label { grid-template-columns: 64px 1fr; align-items: center; }
.provider-chain-editor label span { font-weight: 700; color: #343a46; }
.provider-chain-editor footer { display: flex; justify-content: flex-end; }
.runtime-settings-card { max-width: 720px; background: #fff; border-radius: 14px; padding: 24px; box-shadow: 0 8px 28px rgba(31,35,41,.07); }
.admin-title-actions { display: flex; align-items: center; gap: 10px; }
.admin-title-actions .admin-primary { height: 36px; }
.admin-module-shell { display: grid; gap: 18px; max-width: 1420px; }
.admin-module-hero { display: flex; align-items: stretch; justify-content: space-between; gap: 18px; padding: 22px 24px; border: 1px solid #e8eaf0; border-radius: 16px; background: #fff; box-shadow: 0 16px 40px rgba(28, 32, 44, .06); }
.admin-module-hero h2 { margin: 6px 0 8px; font-size: 24px; line-height: 1.2; color: #151922; letter-spacing: 0; }
.admin-module-hero p { margin: 0; max-width: 620px; color: #747b88; line-height: 1.65; }
.admin-module-hero>div:first-child>span,.admin-settings-panel header span,.admin-composer-panel header span,.admin-preview-panel>span { color: #8e96a6; font-size: 11px; font-weight: 800; letter-spacing: .12em; text-transform: uppercase; }
.admin-hero-metrics { display: grid; grid-template-columns: repeat(4, minmax(84px, 1fr)); gap: 10px; min-width: 430px; }
.admin-hero-metrics article { display: grid; align-content: center; gap: 5px; padding: 14px 16px; border: 1px solid #eef0f4; border-radius: 12px; background: #fbfcfe; }
.admin-hero-metrics small { color: #8a92a0; font-size: 11px; }
.admin-hero-metrics b { color: #161a22; font-size: 22px; line-height: 1; }
.monitoring-dashboard { max-width: 1480px; gap: 14px; }
.monitoring-console-tabs { display: flex; align-items: center; gap: 0; height: 44px; padding: 0 16px; border: 1px solid #e5e8ef; border-radius: 8px; background: #fff; box-shadow: 0 10px 26px rgba(27, 32, 44, .035); }
.monitoring-console-tabs button { position: relative; height: 100%; padding: 0 18px; color: #566171; font-size: 13px; font-weight: 800; }
.monitoring-console-tabs button.active { color: #2764f6; }
.monitoring-console-tabs button.active:after { content: ""; position: absolute; left: 16px; right: 16px; bottom: -1px; height: 2px; border-radius: 2px; background: #2764f6; }
.monitoring-hero { align-items: stretch; padding: 0; overflow: hidden; border-radius: 8px; box-shadow: 0 12px 32px rgba(27, 32, 44, .04); }
.monitoring-hero>div:first-child { display: grid; align-content: center; min-width: 260px; padding: 22px 22px; border-right: 1px solid #edf0f5; }
.monitoring-hero h2 { margin: 5px 0 7px; font-size: 22px; }
.monitoring-hero p { max-width: 520px; font-size: 13px; line-height: 1.55; }
.monitoring-kpis { grid-template-columns: repeat(5, minmax(112px, 1fr)); gap: 0; min-width: 680px; }
.monitoring-kpis article { min-height: 128px; padding: 20px 22px; border: 0; border-right: 1px solid #edf0f5; border-radius: 0; background: #fff; }
.monitoring-kpis article:last-child { border-right: 0; }
.monitoring-kpis small { display: flex; align-items: center; gap: 5px; color: #4f5968; font-size: 13px; font-weight: 850; }
.monitoring-kpis small:after { content: "?"; display: inline-grid; place-items: center; width: 14px; height: 14px; border: 1px solid #c7ceda; border-radius: 50%; color: #98a1af; font-size: 10px; font-weight: 900; }
.monitoring-kpis b { font-size: 26px; letter-spacing: 0; }
.monitoring-kpis article span { color: #6f7a8a; font-size: 11px; line-height: 1.35; }
.monitoring-kpis .tone-good b { color: #1f883d; }
.monitoring-kpis .tone-warning b { color: #b26a00; }
.monitoring-kpis .tone-danger b { color: #cf3f2e; }
.monitoring-toolbar { display: flex; align-items: end; gap: 10px; justify-content: flex-end; padding: 12px 14px; border: 1px solid #e5e8ef; border-radius: 8px; background: #fff; box-shadow: 0 10px 26px rgba(27, 32, 44, .035); }
.monitoring-toolbar label { display: grid; gap: 6px; color: #7a8391; font-size: 11px; font-weight: 800; }
.monitoring-toolbar input,.monitoring-toolbar select { height: 36px; min-width: 154px; border: 1px solid #dfe3ea; border-radius: 9px; padding: 0 10px; background: #fff; color: #222833; outline: none; }
.monitoring-grid { display: grid; grid-template-columns: repeat(2, minmax(0, 1fr)); gap: 14px; align-items: start; }
.monitoring-panel { min-width: 0; padding: 18px; border: 1px solid #e5e8ef; border-radius: 8px; background: #fff; box-shadow: 0 12px 30px rgba(27, 32, 44, .035); }
.monitoring-panel.wide { grid-column: 1 / -1; }
.monitoring-panel header { display: flex; align-items: baseline; justify-content: space-between; gap: 14px; margin-bottom: 16px; }
.monitoring-panel header span { color: #8e96a6; font-size: 11px; font-weight: 900; letter-spacing: .12em; text-transform: uppercase; }
.monitoring-panel header b { color: #171b24; font-size: 16px; }
.monitoring-table { width: 100%; border-collapse: collapse; font-size: 12px; }
.monitoring-table th { padding: 11px 10px; border-bottom: 1px solid #edf0f4; color: #8a93a1; font-size: 11px; font-weight: 850; text-align: left; background: #fafbfc; }
.monitoring-table td { padding: 12px 10px; border-bottom: 1px solid #f0f2f5; color: #333a46; vertical-align: middle; }
.monitoring-table td b { display: block; color: #1c222d; }
.monitoring-table td small { display: block; margin-top: 4px; color: #8b94a2; }
.metric-pill { display: inline-flex; align-items: center; height: 24px; padding: 0 9px; border-radius: 999px; font-size: 11px; font-weight: 900; }
.metric-pill.good { background: #eaf8ef; color: #28794b; }
.metric-pill.warning { background: #fff4df; color: #9b6618; }
.metric-pill.danger { background: #fff0ee; color: #c74438; }
.metric-pill.neutral { background: #eef1f5; color: #66707f; }
.metric-list { display: grid; gap: 13px; }
.metric-list>div { display: grid; grid-template-columns: minmax(0,1fr) auto; gap: 7px 12px; align-items: center; }
.metric-list b { display: block; overflow: hidden; color: #222833; text-overflow: ellipsis; white-space: nowrap; }
.metric-list small { display: block; margin-top: 3px; color: #8d96a4; }
.metric-list span { color: #222833; font-weight: 900; }
.metric-list i { grid-column: 1 / -1; height: 7px; overflow: hidden; border-radius: 999px; background: #edf0f4; }
.metric-list em { display: block; height: 100%; min-width: 3%; border-radius: inherit; background: #2764f6; }
.queue-list,.incident-list,.profile-slices { display: grid; gap: 10px; }
.queue-list>div,.incident-list>div,.profile-slices section { display: grid; gap: 5px; padding: 12px; border: 1px solid #edf0f4; border-radius: 12px; background: #fbfcfe; }
.queue-list b,.incident-list b,.profile-slices b { color: #202631; }
.queue-list span { justify-self: start; color: #171a22; font-size: 24px; font-weight: 900; line-height: 1; }
.queue-list small,.incident-list small,.incident-list p { margin: 0; color: #87909e; line-height: 1.45; }
.incident-list p { overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.profile-slices section span { display: inline-flex; width: fit-content; max-width: 100%; padding: 5px 8px; border-radius: 999px; background: #f0f2f5; color: #66707f; font-size: 11px; font-weight: 800; }
.monitoring-line-card { position: relative; display: grid; gap: 10px; min-height: 250px; }
.monitoring-line-chart { width: 100%; height: 190px; overflow: visible; }
.monitoring-line-chart line { stroke: #e7ebf2; stroke-width: 1; stroke-dasharray: 5 5; }
.monitoring-line-chart polyline { fill: none; stroke-width: 2.4; stroke-linecap: round; stroke-linejoin: round; vector-effect: non-scaling-stroke; }
.monitoring-line-chart .primary { stroke: #2764f6; }
.monitoring-line-chart .danger { stroke: #e15349; }
.monitoring-line-chart .secondary { stroke: #55b86a; }
.monitoring-line-chart .muted { stroke: #aeb7c5; }
.monitoring-axis { display: grid; grid-template-columns: repeat(auto-fit, minmax(44px, 1fr)); gap: 8px; }
.monitoring-axis span { overflow: hidden; color: #7c8593; font-size: 10px; text-align: center; text-overflow: ellipsis; white-space: nowrap; }
.monitoring-legend { display: flex; justify-content: flex-end; gap: 14px; color: #6d7685; font-size: 11px; font-weight: 850; }
.monitoring-legend span:before { content: ""; display: inline-block; width: 8px; height: 8px; margin-right: 6px; border-radius: 50%; background: #2764f6; }
.monitoring-legend .danger:before { background: #e15349; }
.monitoring-legend .secondary:before { background: #55b86a; }
.monitoring-legend .muted:before { background: #aeb7c5; }
.monitoring-line-card>p,.incident-list>p { margin: 0; color: #8a93a1; }
.donut-layout { display: grid; grid-template-columns: 180px minmax(0,1fr); gap: 18px; align-items: center; min-height: 210px; }
.monitoring-donut { width: 158px; aspect-ratio: 1; display: grid; place-items: center; border-radius: 50%; box-shadow: inset 0 0 0 1px rgba(0,0,0,.04); }
.monitoring-donut span { width: 78px; aspect-ratio: 1; display: grid; place-items: center; align-content: center; border-radius: 50%; background: #fff; color: #6f7886; font-size: 11px; box-shadow: 0 0 0 1px #edf0f4; }
.monitoring-donut b { color: #171b24; font-size: 16px; line-height: 1; }
.monitoring-donut small { color: #7d8795; }
.donut-list { display: grid; gap: 12px; min-width: 0; }
.donut-list>div { display: grid; grid-template-columns: 10px minmax(0,1fr) 58px 58px; gap: 10px; align-items: center; }
.donut-list i { width: 8px; height: 8px; border-radius: 50%; background: var(--swatch); }
.donut-list b { overflow: hidden; color: #222833; text-overflow: ellipsis; white-space: nowrap; }
.donut-list span,.donut-list small { justify-self: end; color: #657080; font-size: 12px; font-weight: 850; }
.admin-table-card { overflow: hidden; border: 1px solid #e7e9ef; border-radius: 16px; background: #fff; box-shadow: 0 14px 36px rgba(28, 32, 44, .05); }
.admin-data-table { width: 100%; border-collapse: collapse; font-size: 12px; }
.admin-data-table th { padding: 14px 16px; background: #f8f9fb; color: #858d9b; font-size: 11px; font-weight: 800; text-align: left; }
.admin-data-table td { padding: 15px 16px; border-top: 1px solid #edf0f4; color: #363c48; vertical-align: middle; }
.admin-data-table td small { display: block; margin-top: 4px; color: #929aa7; }
.admin-data-table code { padding: 4px 7px; border-radius: 7px; background: #f3f5f8; color: #434a57; font-size: 11px; }
.admin-user-cell { display: flex; align-items: center; gap: 11px; }
.admin-user-cell i { width: 34px; height: 34px; display: grid; place-items: center; border-radius: 50%; background: #171a22; color: #fff; font-style: normal; font-weight: 800; }
.admin-user-cell b { color: #1c212c; }
.admin-muted-text { color: #707785; }
.admin-compact-select { min-width: 112px; height: 34px; border: 1px solid #dfe3ea; border-radius: 9px; padding: 0 10px; background: #fff; color: #2f3540; font-size: 12px; }
.admin-compact-select.plan { min-width: 136px; }
.admin-soft-button,.admin-save-button,.admin-text-button { display: inline-flex; align-items: center; justify-content: center; border-radius: 9px; font-weight: 800; cursor: pointer; }
.admin-soft-button { height: 34px; padding: 0 14px; border: 1px solid #dfe3ea!important; background: #fff!important; color: #202631!important; }
.admin-soft-button:hover { background: #f7f8fa!important; }
.admin-plan-board { display: grid; grid-template-columns: repeat(3, minmax(0, 1fr)); gap: 20px; align-items: start; max-width: 1360px; }
.admin-plan-card { display: grid; gap: 13px; min-width: 0; overflow: hidden; padding: 18px; border: 1px solid #e6e8ef; border-radius: 18px; background: #fff; box-shadow: 0 18px 42px rgba(28, 32, 44, .055); }
.admin-plan-card.tone-free { order: 1; }
.admin-plan-card.tone-standard { order: 2; }
.admin-plan-card.tone-advanced { order: 3; border-color: #d9d4ec; }
.admin-plan-card.tone-enterprise { order: 4; border-color: #d9c9aa; box-shadow: 0 18px 42px rgba(93, 72, 38, .075); }
.admin-plan-card.tone-internal { order: 5; border-color: #d8dde8; background: #fbfcfe; }
.admin-plan-card-head { display: grid; gap: 10px; min-width: 0; padding-bottom: 13px; border-bottom: 1px solid #edf0f4; }
.admin-plan-kicker { display: flex; align-items: center; gap: 8px; min-height: 24px; }
.admin-plan-kicker span { color: #8b93a1; font-size: 11px; font-weight: 900; letter-spacing: .12em; text-transform: uppercase; }
.admin-plan-kicker em { font-style: normal; padding: 4px 7px; border-radius: 999px; background: #f0f2f5; color: #646c79; font-size: 10px; font-weight: 800; }
.tone-enterprise .admin-plan-kicker em { background: #f5eee2; color: #8a6435; }
.admin-plan-name-input { width: 100%; min-width: 0; border: 0; border-radius: 8px; padding: 0; background: transparent; color: #151922; font-size: 22px; font-weight: 900; outline: none; text-overflow: ellipsis; }
.admin-plan-name-input:focus { box-shadow: 0 0 0 2px #e6e9f0; padding: 3px 6px; }
.admin-plan-card-head p { display: -webkit-box; min-height: 44px; margin: 0; overflow: hidden; color: #727986; line-height: 1.55; -webkit-line-clamp: 2; -webkit-box-orient: vertical; }
.admin-plan-price-row { display: flex; align-items: flex-end; justify-content: space-between; gap: 10px; min-width: 0; padding: 12px; border-radius: 12px; background: #f7f8fa; }
.admin-plan-price-row strong { min-width: 0; color: #151922; font-size: 24px; line-height: 1; white-space: nowrap; }
.admin-plan-price-row small { margin-left: 4px; color: #747b88; font-size: 12px; font-weight: 700; }
.admin-plan-price-row span { min-width: 0; overflow: hidden; color: #717986; font-size: 12px; font-weight: 800; white-space: nowrap; text-overflow: ellipsis; }
.admin-plan-flags { display: flex; align-items: center; gap: 14px; flex-wrap: wrap; }
.admin-switch,.admin-mini-switch,.admin-toggle-row { display: inline-flex; align-items: center; gap: 8px; color: #3b424e; font-size: 12px; font-weight: 800; }
.admin-switch input,.admin-mini-switch input { position: absolute; opacity: 0; pointer-events: none; }
.admin-switch span,.admin-mini-switch span { width: 34px; height: 20px; border-radius: 999px; background: #d8dde5; position: relative; transition: background .16s ease; }
.admin-switch span:after,.admin-mini-switch span:after { content: ""; position: absolute; top: 2px; left: 2px; width: 16px; height: 16px; border-radius: 50%; background: #fff; box-shadow: 0 1px 4px rgba(0,0,0,.18); transition: transform .16s ease; }
.admin-switch input:checked+span,.admin-mini-switch input:checked+span { background: #171a22; }
.admin-switch input:checked+span:after,.admin-mini-switch input:checked+span:after { transform: translateX(14px); }
.admin-plan-fields { display: grid; gap: 10px; min-width: 0; }
.admin-plan-fields label,.admin-field-grid label,.admin-composer-panel label,.admin-quota-row label { display: grid; gap: 6px; min-width: 0; color: #707987; font-size: 11px; font-weight: 800; }
.admin-plan-fields>div { display: grid; grid-template-columns: 1fr 1fr; gap: 10px; }
.admin-plan-fields input,.admin-plan-fields textarea,.admin-field-grid input,.admin-composer-panel input,.admin-composer-panel textarea,.admin-quota-row input { width: 100%; min-width: 0; border: 1px solid #dfe3ea; border-radius: 9px; background: #fff; color: #242a35; outline: none; }
.admin-plan-fields input,.admin-field-grid input,.admin-composer-panel input { height: 36px; padding: 0 10px; }
.admin-plan-fields textarea,.admin-composer-panel textarea { resize: vertical; padding: 10px; line-height: 1.55; }
.admin-plan-fields input:focus,.admin-plan-fields textarea:focus,.admin-field-grid input:focus,.admin-composer-panel input:focus,.admin-composer-panel textarea:focus,.admin-quota-row input:focus,.admin-compact-select:focus { border-color: #171a22; box-shadow: 0 0 0 3px rgba(23, 26, 34, .08); }
.admin-feature-row { display: flex; flex-wrap: wrap; gap: 6px; }
.admin-feature-row span { max-width: 100%; overflow: hidden; padding: 5px 8px; border-radius: 999px; background: #f3f4f6; color: #68717f; font-size: 11px; font-weight: 750; text-overflow: ellipsis; white-space: nowrap; }
.admin-save-button { height: 38px; border: 0!important; background: #171a22!important; color: #fff!important; }
.admin-quota-stack { display: grid; gap: 9px; min-width: 0; padding-top: 4px; }
.admin-quota-stack>header { display: flex; align-items: center; justify-content: space-between; gap: 10px; }
.admin-quota-stack>header b { color: #171b24; font-size: 14px; }
.admin-quota-stack>header small { color: #87909e; }
.admin-quota-row { display: grid; gap: 10px; min-width: 0; padding: 11px; border: 1px solid #edf0f4; border-radius: 13px; background: #fcfdff; }
.admin-quota-row.off { opacity: .58; }
.admin-quota-row-head { display: flex; align-items: center; justify-content: space-between; gap: 10px; min-width: 0; }
.admin-quota-actions { display: inline-flex; align-items: center; gap: 8px; flex: 0 0 auto; }
.admin-quota-controls { display: grid; grid-template-columns: repeat(3, minmax(0, 1fr)); gap: 8px; min-width: 0; }
.admin-quota-title { min-width: 0; }
.admin-quota-title b { display: block; color: #252b36; font-size: 12px; }
.admin-quota-title small { display: block; margin-top: 4px; color: #8b93a1; font-size: 10px; white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
.admin-quota-row label span { color: #8c95a3; font-size: 10px; }
.admin-quota-row input { height: 32px; min-width: 0; padding: 0 8px; font-size: 12px; }
.admin-mini-switch { align-self: center; justify-self: center; }
.admin-mini-switch span { width: 30px; height: 18px; }
.admin-mini-switch span:after { width: 14px; height: 14px; }
.admin-mini-switch input:checked+span:after { transform: translateX(12px); }
.admin-text-button { height: 28px; padding: 0 2px; border: 0!important; background: transparent!important; color: #202631!important; font-size: 12px; white-space: nowrap; }
.admin-status-pill { display: inline-flex; align-items: center; height: 24px; padding: 0 9px; border-radius: 999px; font-size: 11px; font-weight: 900; }
.order-paid { background: #e9f8ef; color: #27824c; }
.order-pending { background: #fff5e6; color: #b36b12; }
.order-cancelled,.order-expired,.order-default { background: #f0f2f5; color: #697281; }
.admin-service-state { display: flex; align-items: center; gap: 9px; align-self: center; padding: 10px 14px; border: 1px solid #eceff4; border-radius: 999px; background: #f8f9fb; color: #77808e; font-weight: 900; }
.admin-service-state i { width: 8px; height: 8px; border-radius: 50%; background: #9aa3b1; }
.admin-service-state.on { color: #236d42; background: #edf8f1; border-color: #d8efdf; }
.admin-service-state.on i { background: #2d9a57; }
.admin-sms-guide { display: grid; grid-template-columns: repeat(4, minmax(0, 1fr)); gap: 12px; }
.admin-sms-guide article { display: grid; gap: 7px; padding: 15px; border: 1px solid #e7e9ef; border-radius: 14px; background: #fff; box-shadow: 0 12px 30px rgba(28, 32, 44, .045); }
.admin-sms-guide b { color: #181d26; font-size: 13px; }
.admin-sms-guide p { margin: 0; color: #757e8c; font-size: 12px; line-height: 1.65; }
.admin-sms-guide code { padding: 2px 5px; border-radius: 6px; background: #f0f2f5; color: #2e3541; font-size: 11px; }
.admin-settings-grid { display: grid; grid-template-columns: minmax(260px, .75fr) minmax(360px, 1.15fr); gap: 16px; }
.admin-settings-panel,.admin-composer-panel,.admin-preview-panel { display: grid; gap: 14px; padding: 18px; border: 1px solid #e7e9ef; border-radius: 16px; background: #fff; box-shadow: 0 14px 36px rgba(28, 32, 44, .05); }
.admin-settings-panel.wide { grid-column: 1 / -1; }
.admin-settings-panel header,.admin-composer-panel header { display: grid; gap: 5px; }
.admin-settings-panel header b,.admin-composer-panel header b { color: #171b24; font-size: 16px; }
.admin-toggle-row { justify-content: flex-start; padding: 14px; border: 1px solid #edf0f4; border-radius: 12px; background: #fbfcfe; }
.admin-toggle-row input { width: 18px; height: 18px; accent-color: #171a22; }
.admin-toggle-row small { display: block; margin-top: 3px; color: #8d95a3; font-weight: 600; }
.admin-provider-select { display: grid; gap: 7px; padding: 14px; border: 1px solid #edf0f4; border-radius: 12px; background: #fbfcfe; color: #3b424e; font-size: 12px; font-weight: 800; }
.admin-provider-select select { height: 38px; border: 1px solid #dfe3ea; border-radius: 9px; padding: 0 10px; background: #fff; color: #242a35; }
.admin-provider-select small { color: #8d95a3; font-weight: 600; line-height: 1.45; }
.admin-field-grid { display: grid; grid-template-columns: repeat(2, minmax(0, 1fr)); gap: 11px; }
.admin-field-grid small { color: #8f98a6; font-weight: 600; line-height: 1.45; }
.admin-field-grid.four { grid-template-columns: repeat(4, minmax(0, 1fr)); }
.admin-sms-test-panel { display: grid; gap: 14px; padding: 18px; border: 1px solid #dfe5ef; border-radius: 16px; background: #fff; box-shadow: 0 14px 36px rgba(28, 32, 44, .05); }
.admin-sms-test-panel header { display: grid; gap: 5px; }
.admin-sms-test-panel header span { color: #8e96a6; font-size: 11px; font-weight: 800; letter-spacing: .12em; text-transform: uppercase; }
.admin-sms-test-panel header b { color: #171b24; font-size: 16px; }
.admin-sms-test-panel header small { color: #778190; line-height: 1.55; }
.admin-sms-test-form { display: grid; grid-template-columns: minmax(180px, 1fr) minmax(160px, .7fr) auto; gap: 11px; align-items: end; }
.admin-sms-test-form label { display: grid; gap: 6px; min-width: 0; color: #707987; font-size: 11px; font-weight: 800; }
.admin-sms-test-form input,.admin-sms-test-form select { width: 100%; height: 38px; min-width: 0; border: 1px solid #dfe3ea; border-radius: 9px; padding: 0 10px; background: #fff; color: #242a35; outline: none; }
.admin-sms-test-form input:focus,.admin-sms-test-form select:focus { border-color: #171a22; box-shadow: 0 0 0 3px rgba(23, 26, 34, .08); }
.admin-sms-test-form button { height: 38px; white-space: nowrap; }
.admin-sms-test-panel>p { margin: 0; padding: 10px 12px; border-radius: 10px; background: #edf8f1; color: #236d42; font-weight: 800; }
.admin-sms-test-panel>p.error { background: #fff2f0; color: #cf3f2e; }
.admin-footer-actions { display: flex; justify-content: flex-end; }
.admin-broadcast-layout { display: grid; grid-template-columns: minmax(420px, 1fr) 360px; gap: 16px; align-items: start; }
.admin-composer-panel .admin-primary { justify-self: end; min-width: 128px; }
.admin-preview-panel { min-height: 240px; align-content: start; background: #171a22; border-color: #171a22; color: #fff; }
.admin-preview-panel>span { color: #9aa3b5; }
.admin-preview-panel h3 { margin: 2px 0 0; color: #fff; font-size: 20px; line-height: 1.35; }
.admin-preview-panel p { min-height: 88px; margin: 0; color: #d5dae5; line-height: 1.7; white-space: pre-wrap; }
.admin-preview-panel dl { display: grid; gap: 8px; margin: 8px 0 0; }
.admin-preview-panel dl div { display: flex; align-items: center; justify-content: space-between; gap: 12px; padding-top: 8px; border-top: 1px solid rgba(255,255,255,.12); }
.admin-preview-panel dt { color: #98a1b2; }
.admin-preview-panel dd { margin: 0; color: #fff; font-weight: 800; }
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
.runtime-settings-card input, .runtime-settings-card select { height: 40px; border: 1px solid #dfe1e6; border-radius: 8px; padding: 0 12px; background: #fff; }
.runtime-settings-card footer { display: flex; justify-content: flex-end; margin-top: 18px; }
.ocr-settings-card { max-width: 960px; }
.ocr-cache-pill { flex: 0 0 auto; border: 1px solid #e5e7ee; border-radius: 999px; padding: 7px 12px; color: #596170; font-weight: 700; background: #fafbff; }
.ocr-form-grid { display: grid; grid-template-columns: repeat(2, minmax(0, 1fr)); column-gap: 18px; }
.ocr-switches { display: grid; gap: 10px; margin-top: 16px; }
.ocr-switches label { flex-direction: row; align-items: center; margin: 0; color: #343a46; }
.ocr-switches input { width: 16px; height: 16px; }
.ocr-prewarm-state { display: flex; align-items: flex-start; justify-content: space-between; gap: 16px; margin-top: 20px; padding: 13px 14px; border: 1px solid #e7e9f0; border-radius: 8px; background: #fbfcff; color: #596170; }
.ocr-prewarm-state b { color: #242a35; white-space: nowrap; }
.ocr-prewarm-state span { text-align: right; line-height: 1.6; }
.ocr-actions { gap: 10px; flex-wrap: wrap; }
.ocr-actions button { display: inline-flex; align-items: center; justify-content: center; gap: 7px; min-height: 38px; border: 1px solid #dfe1e6; border-radius: 8px; padding: 0 14px; color: #343a46; background: #fff; font-weight: 700; }
.ocr-actions button:disabled { opacity: .7; cursor: not-allowed; }
.workflow-toolbar > div { display: flex; align-items: center; gap: 12px; }
.workflow-selector { height: 34px; min-width: 176px; border: 1px solid #dfe1e6; border-radius: 8px; padding: 0 10px; background: #fff; color: #2f343d; font-weight: 650; }
.workflow-active-state { color: #596170; white-space: nowrap; }
@media (max-width: 1280px) {
  .admin-plan-board { grid-template-columns: repeat(2, minmax(0, 1fr)); }
  .monitoring-kpis { min-width: 0; grid-template-columns: repeat(3, minmax(0, 1fr)); }
  .monitoring-grid { grid-template-columns: 1fr; }
}
@media (max-width: 900px) {
  .admin-top { padding: 0 12px; }
  .admin-divider, .admin-top>strong { display: none; }
  .admin-top>button { white-space: nowrap; font-size: 11px; }
  .admin-nav>p { font-size: 0; }
  .admin-nav>button { font-size: 0 !important; justify-content: center; }
  .admin-nav>button>.anticon { font-size: 18px; }
  .admin-module-hero { display: grid; padding: 18px; }
  .admin-hero-metrics { min-width: 0; grid-template-columns: repeat(2, minmax(0, 1fr)); }
  .monitoring-toolbar { display: grid; grid-template-columns: 1fr; }
  .monitoring-toolbar input,.monitoring-toolbar select { width: 100%; min-width: 0; }
  .monitoring-panel { overflow-x: auto; }
  .monitoring-table { min-width: 760px; }
  .ops-trend,.business-trend { grid-template-columns: repeat(4, minmax(52px, 1fr)); overflow-x: auto; }
  .admin-table-card { overflow-x: auto; }
  .admin-data-table { min-width: 720px; }
  .admin-plan-board { grid-template-columns: 1fr; }
  .admin-quota-controls { grid-template-columns: 1fr; }
  .admin-mini-switch { justify-self: start; }
  .admin-sms-guide,.admin-settings-grid,.admin-broadcast-layout { grid-template-columns: 1fr; }
  .admin-sms-test-form { grid-template-columns: 1fr; }
  .admin-field-grid,.admin-field-grid.four,.admin-plan-fields>div { grid-template-columns: 1fr; }
  .ocr-form-grid { grid-template-columns: 1fr; }
  .ocr-prewarm-state { display: block; }
  .ocr-prewarm-state span { display: block; text-align: left; margin-top: 6px; }
}
</style>
<style src="./admin.css"/>
<style src="./admin-provider-groups.css"/>
<style src="./admin-prompt-upload.css"/>
