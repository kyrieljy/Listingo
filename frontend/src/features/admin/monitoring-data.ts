import type { MonitoringGranularity } from '../../api/client'

export type MetricDefinition = {
  key: string
  label: string
  formula: string
  source: string
  numerator: string
  denominator: string
  unit: string
  notes: string
}

export type MetricCard = {
  key: string
  definition_key?: string
  label: string
  value: string
  numeric: number
  tone?: 'good' | 'warning' | 'danger' | 'neutral' | string
  helper?: string
}

export type MetricRow = Record<string, unknown> & {
  key?: string
  label?: string
  count?: number
  total?: number
  success_rate?: number
  failure_rate?: number
  timeout_rate?: number
  p95_duration_ms?: number
}

export type MonitoringPayload = Record<string, unknown> & {
  metric_definitions?: Record<string, MetricDefinition>
  summary_cards?: MetricCard[]
  timeseries?: MetricRow[]
  trend_rows?: MetricRow[]
  provider_rows?: MetricRow[]
  node_rows?: MetricRow[]
  business_rows?: MetricRow[]
  queue_rows?: MetricRow[]
  incident_rows?: MetricRow[]
  feature_rows?: MetricRow[]
  platform_rows?: MetricRow[]
  ratio_rows?: MetricRow[]
  module_rows?: MetricRow[]
  video_type_rows?: MetricRow[]
  profile_rows?: Record<string, MetricRow[]>
  event_relation_rows?: MetricRow[]
  subscription_rows?: MetricRow[]
  user_rows?: MetricRow[]
}

export type MonitoringQueryState = {
  start_at: string
  end_at: string
  granularity: MonitoringGranularity
}

export function inputDateTime(date: Date): string {
  const offset = date.getTimezoneOffset() * 60000
  return new Date(date.getTime() - offset).toISOString().slice(0, 16)
}

export function defaultMonitoringFilters(): MonitoringQueryState {
  const end = new Date()
  const start = new Date()
  start.setDate(start.getDate() - 7)
  return { start_at: inputDateTime(start), end_at: inputDateTime(end), granularity: 'day' }
}

export const prototypeDefinitions: Record<string, MetricDefinition> = {
  total_calls: definition('total_calls', '总调用数', 'ExecutionLog 真实任务调用数', 'execution_log', '窗口内 dry_run=false 的调用记录', '无', '次', '排除后台测试和安全演示模式。'),
  success_rate: definition('success_rate', '成功率', '成功次数 / 总调用数', 'execution_log.status', 'status = succeeded', '窗口内总调用数', '%', '没有样本时显示 0%。'),
  failure_rate: definition('failure_rate', '失败率', '失败次数 / 总调用数', 'execution_log.status + error', 'failed/partial_failed 或 error 非空', '窗口内总调用数', '%', '部分失败计入失败。'),
  p95_latency: definition('p95_latency', 'P95耗时', 'duration_ms 的 95 分位', 'execution_log.duration_ms', '非空耗时样本', '无', 'ms/s/min', '用于观察尾部延迟。'),
  timeout_rate: definition('timeout_rate', '超时率', '超时调用数 / 总调用数', 'execution_log + provider timeout', '错误含 timeout/超时或耗时超阈值', '窗口内总调用数', '%', '没有配置超时时按错误文本判断。'),
  queue: definition('queue', '进行中', 'queued + running + cancelling', 'job status', '未进入最终态的任务', '无', '个', '用于判断积压和卡住的任务。'),
  provider_health: definition('provider_health', '中转站健康', '健康模型数 / 全部模型数', 'provider + execution_log', '未触发异常阈值的模型', '全部配置模型', '个', '参考启用状态、密钥状态和最近健康检查。'),
  active_users: definition('active_users', '活跃用户', '窗口内有登录、埋点或任务行为的去重用户数', 'analytics_event + login_event + jobs', '去重 user_id', '无', '人', '匿名事件不计入用户数。'),
  new_users: definition('new_users', '新增用户', '窗口内创建用户数', 'app_user.created_at', 'created_at 在窗口内', '无', '人', '按账号创建时间统计。'),
  returning_users: definition('returning_users', '回访用户', '活跃用户中老用户数', 'app_user + activity', '老用户且窗口内活跃', '窗口活跃用户', '人', '区分新客增长和老客回访。'),
  feature_ctr: definition('feature_ctr', '点击率', '点击数 / 曝光数', 'analytics_event.event_type', 'click', 'view', '%', '按 feature_key 聚合。'),
  submit_rate: definition('submit_rate', '提交率', '提交数 / 点击数', 'analytics_event + jobs', 'submit + 任务创建', 'click', '%', '衡量点击后的真实使用意图。'),
  download_rate: definition('download_rate', '下载率', '下载数 / 成功数', 'analytics_event + jobs', 'download', '成功任务数', '%', '反映生成结果是否被使用。'),
  paid_conversion_rate: definition('paid_conversion_rate', '支付转化率', '已支付订单数 / 订单创建数', 'payment_order.status', 'paid', '订单创建数', '%', '第一版不含外部支付渠道归因。'),
  quota_usage_rate: definition('quota_usage_rate', '额度使用率', '已预留或确认额度 / 月额度', 'quota_ledger', 'reserved/confirmed amount', '套餐月额度', '%', '无限额度套餐不计分母。'),
}

export const opsPrototypeData: MonitoringPayload = {
  metric_definitions: prototypeDefinitions,
  summary_cards: [
    card('total_calls', '总调用数', '18,642', 18642, 'neutral', '真实调用 / 7 天'),
    card('success_rate', '成功率', '97.8%', 97.8, 'good', '18,236/18,642 次成功'),
    card('failure_rate', '失败率', '2.2%', 2.2, 'warning', '406 次异常'),
    card('p95_latency', 'P95耗时', '46.8s', 46800, 'warning', '18,110 条耗时样本'),
    card('timeout_rate', '超时率', '1.4%', 1.4, 'good', '261 次超时'),
    card('queue', '进行中', '27', 27, 'warning', 'queued 18 / running 9'),
    card('provider_health', '中转站健康', '11/13', 11, 'warning', '2 个预警，0 个异常'),
  ],
  timeseries: ['08-07', '08-08', '08-09', '08-10', '08-11', '08-12', '08-13'].map((bucket, index) => ({
    bucket,
    total: [2210, 2440, 2602, 2510, 2790, 2974, 3116][index],
    jobs: [220, 236, 244, 238, 260, 276, 282][index],
    success_rate: [96.9, 97.4, 97.1, 98.2, 97.7, 98.1, 97.8][index],
    failure_rate: [3.1, 2.6, 2.9, 1.8, 2.3, 1.9, 2.2][index],
    timeout_rate: [1.8, 1.4, 1.6, 1.1, 1.5, 1.2, 1.4][index],
    p95_duration_ms: [52000, 48800, 50600, 42100, 46800, 45200, 46800][index],
  })),
  provider_rows: [
    provider('fal', 'fal.ai', 'FLUX.1 Kontext', '图片生成', 5680, 98.7, 1.3, 0.8, 38600, 'ready'),
    provider('runware', 'Runware', 'gpt-image-2', '图片生成', 4310, 97.9, 2.1, 1.1, 44200, 'ready'),
    provider('kie', 'Kie.ai', 'veo3-fast', '视频生成', 1240, 95.8, 4.2, 2.8, 98200, 'warning'),
    provider('openrouter', 'OpenRouter', 'gpt-4.1-mini', '脚本规划', 3860, 99.1, 0.9, 0.2, 12600, 'ready'),
    provider('cometapi', 'CometAPI', 'gpt-image-2', '图片编辑', 2130, 96.4, 3.6, 2.1, 71600, 'warning'),
  ],
  node_rows: [
    node('meta_prompt', '卖点解析/提示词规划', '读取商品图和卖点，规划套图提示词与画面职责。', 3860, 99.1, 0.9, 0.1, 11800),
    node('image_generate', '图片生成', '调用图片模型生成商品套图、A+ 或批量图片。', 9980, 97.8, 2.2, 1.3, 46800),
    node('image_edit', '图片二次编辑', '基于当前结果图和修改要求调用改图链路。', 1480, 96.1, 3.9, 2.2, 61200),
    node('video_generate', '视频生成/轮询落地', '轮询视频模型状态并落地最终视频结果。', 760, 95.3, 4.7, 3.4, 118000),
    node('text_ocr', 'OCR 文本识别', '识别图片中的可编辑文字区域和置信度。', 980, 99.6, 0.4, 0, 4200),
  ],
  business_rows: [
    business('suite', '商品套图', 1820, 98.2, 1.8, 38200, 12740),
    business('batch_suite', '批量套图', 246, 96.7, 3.3, 84100, 1722),
    business('aplus_plan', 'A+ 规划', 720, 99.0, 1.0, 17800, 5040),
    business('aplus', 'A+ 生成', 684, 97.4, 2.6, 56400, 4380),
    business('video', '视频', 312, 95.8, 4.2, 138000, 728),
  ],
  queue_rows: [
    { key: 'suite', label: '商品套图', count: 9, queued: 6, running: 3, cancelling: 0, oldest_wait_seconds: 780 },
    { key: 'aplus', label: 'A+ 详情', count: 7, queued: 4, running: 3, cancelling: 0, oldest_wait_seconds: 620 },
    { key: 'video', label: '视频', count: 8, queued: 6, running: 2, cancelling: 0, oldest_wait_seconds: 1260 },
    { key: 'batch', label: '批量任务', count: 3, queued: 2, running: 1, cancelling: 0, oldest_wait_seconds: 940 },
  ],
  incident_rows: [
    { id: 'i1', node: 'video_generate', provider_label: 'Kie.ai', error_category: '超时', error: 'provider timeout after 120s', created_at: new Date().toISOString(), duration_ms: 120000 },
    { id: 'i2', node: 'image_edit', provider_label: 'CometAPI', error_category: '模型/中转站', error: 'upstream provider returned 502', created_at: new Date().toISOString(), duration_ms: 71200 },
  ],
}

export const businessPrototypeData: MonitoringPayload = {
  metric_definitions: prototypeDefinitions,
  summary_cards: [
    card('active_users', '活跃用户', '4,286', 4286, 'neutral', '新增 612 人'),
    card('new_users', '新增用户', '612', 612, 'good', '回访 3,674 人'),
    card('returning_users', '回访用户', '3,674', 3674, 'good', '活跃占比 85.7%'),
    card('core_jobs', '核心任务', '3,784', 3784, 'neutral', '成功 3,612 个'),
    card('feature_ctr', '最高点击率', '42.6%', 42.6, 'good', 'A+ 模块点击'),
    card('downloads', '下载行为', '2,910', 2910, 'neutral', '下载率 80.6%'),
    card('paid_orders', '已支付订单', '186', 186, 'good', '订单总数 248 / 转化 75.0%'),
  ],
  feature_rows: [
    feature('suite', '商品套图', 6200, 2140, 880, 850, 710),
    feature('batch_suite', '批量套图', 2460, 620, 246, 238, 182),
    feature('aplus', 'A+ 详情', 3860, 1640, 720, 701, 612),
    feature('batch_aplus', '批量 A+', 980, 260, 112, 104, 86),
    feature('video', '视频', 2480, 910, 312, 299, 236),
    feature('ai_copywriting', '套图 AI 帮写', 1720, 640, 0, 0, 0),
    feature('ai_video_copywriting', '视频 AI 转写', 1280, 520, 0, 0, 0),
    feature('text_edit', 'OCR 改字', 860, 284, 126, 121, 98),
  ],
  event_relation_rows: [
    { key: 'views', label: '曝光', count: 19840, conversion_rate: 100, dropoff: 0 },
    { key: 'clicks', label: '点击', count: 7014, conversion_rate: 35.4, dropoff: 12826 },
    { key: 'submits', label: '提交', count: 3784, conversion_rate: 53.9, dropoff: 3230 },
    { key: 'successes', label: '成功', count: 3612, conversion_rate: 95.5, dropoff: 172 },
    { key: 'downloads', label: '下载', count: 2910, conversion_rate: 80.6, dropoff: 702 },
  ],
  trend_rows: ['08-07', '08-08', '08-09', '08-10', '08-11', '08-12', '08-13'].map((bucket, index) => ({
    bucket,
    views: [2210, 2480, 2640, 2910, 3060, 3180, 3360][index],
    clicks: [720, 840, 910, 1020, 1130, 1190, 1204][index],
    submits: [360, 420, 468, 522, 610, 684, 720][index],
    successes: [344, 399, 452, 501, 582, 654, 680][index],
    downloads: [260, 318, 352, 421, 474, 528, 557][index],
    active_users: [520, 584, 622, 670, 714, 768, 812][index],
  })),
  platform_rows: [
    dimension('亚马逊', 6200, 2140, 1140, 1090, 920, 31.2),
    dimension('TikTok Shop', 3640, 1280, 720, 690, 540, 18.4),
    dimension('淘宝天猫', 2980, 910, 520, 498, 420, 15),
    dimension('小红书', 2210, 880, 486, 465, 386, 11.1),
    dimension('Temu', 1840, 680, 380, 360, 298, 9.3),
  ],
  ratio_rows: [
    dimension('1:1', 0, 0, 1180, 1130, 940, 36),
    dimension('9:16', 0, 0, 910, 864, 704, 27.8),
    dimension('3:4', 0, 0, 680, 652, 520, 20.7),
    dimension('16:9', 0, 0, 326, 308, 252, 10),
    dimension('970:600', 0, 0, 180, 174, 150, 5.5),
  ],
  module_rows: [
    dimension('商品主视觉', 0, 426, 360, 352, 318, 24),
    dimension('卖点拆解', 0, 396, 332, 324, 294, 22),
    dimension('生活场景', 0, 348, 304, 298, 250, 19),
    dimension('规格指南', 0, 214, 180, 174, 146, 11),
  ],
  video_type_rows: [
    dimension('UGC 种草', 0, 420, 180, 172, 136, 32),
    dimension('痛点解决', 0, 360, 148, 142, 118, 26),
    dimension('达人口播', 0, 260, 104, 98, 78, 18),
    dimension('测评对比', 0, 210, 82, 78, 62, 14),
  ],
  profile_rows: {
    plans: share(['free', 1880], ['standard', 1470], ['advanced', 720], ['enterprise', 216]),
    roles: share(['普通用户', 4100], ['管理员', 36]),
    statuses: share(['active', 4188], ['disabled', 98]),
    genders: share(['未填写', 2680], ['女', 910], ['男', 696]),
    activity_levels: share(['活跃用户', 4286], ['沉睡用户', 1320], ['未激活用户', 480]),
  },
  subscription_rows: [
    { key: 'free', label: 'free', users: 1880, share: 43.8, orders: 64, paid_orders: 0, paid_conversion_rate: 0, quota_used: 16820 },
    { key: 'standard', label: 'standard', users: 1470, share: 34.3, orders: 108, paid_orders: 92, paid_conversion_rate: 85.2, quota_used: 48620 },
    { key: 'advanced', label: 'advanced', users: 720, share: 16.8, orders: 62, paid_orders: 56, paid_conversion_rate: 90.3, quota_used: 42380 },
    { key: 'enterprise', label: 'enterprise', users: 216, share: 5, orders: 14, paid_orders: 14, paid_conversion_rate: 100, quota_used: 38800 },
  ],
  user_rows: [
    { user_id: 'u1', display_name: 'U10027891', uid: 'U10027891', plan: 'advanced', events: 186, jobs: 42, successes: 40, downloads: 32, paid_orders: 1, top_feature: 'A+ 详情', top_platform: '亚马逊', activity_score: 389 },
    { user_id: 'u2', display_name: 'U10027890', uid: 'U10027890', plan: 'standard', events: 142, jobs: 31, successes: 29, downloads: 24, paid_orders: 1, top_feature: '视频', top_platform: 'TikTok Shop', activity_score: 288 },
    { user_id: 'u3', display_name: 'U10027889', uid: 'U10027889', plan: 'free', events: 98, jobs: 12, successes: 11, downloads: 8, paid_orders: 0, top_feature: '商品套图', top_platform: '淘宝天猫', activity_score: 150 },
  ],
}

export const businessUserPrototypeData: MonitoringPayload = {
  metric_definitions: prototypeDefinitions,
  user: businessPrototypeData.user_rows?.[0],
  summary_cards: [
    card('events', '行为事件', '186', 186, 'neutral', '12 个会话'),
    card('core_jobs', '核心任务', '42', 42, 'neutral', '成功 40 个'),
    card('downloads', '下载行为', '32', 32, 'good', '下载率 80.0%'),
    card('paid_orders', '支付订单', '1', 1, 'good', '订单 1 个'),
  ],
  feature_rows: businessPrototypeData.feature_rows?.slice(0, 5),
  platform_rows: businessPrototypeData.platform_rows?.slice(0, 4),
  ratio_rows: businessPrototypeData.ratio_rows?.slice(0, 4),
  module_rows: businessPrototypeData.module_rows?.slice(0, 4),
  video_type_rows: businessPrototypeData.video_type_rows?.slice(0, 3),
  trend_rows: businessPrototypeData.trend_rows,
  timeline_rows: [
    { id: 't1', kind: 'event', created_at: new Date().toISOString(), title: 'A+ 详情', detail: 'click / aplus_module_click', status: 'click' },
    { id: 't2', kind: 'job', created_at: new Date().toISOString(), title: 'A+ 生成', detail: 'succeeded / 6 个产出', status: 'succeeded' },
    { id: 't3', kind: 'event', created_at: new Date().toISOString(), title: '下载', detail: 'download / aplus_download', status: 'download' },
  ],
  subscription_rows: businessPrototypeData.subscription_rows?.slice(1, 3),
  plan_behavior: { current_plan: 'advanced', orders: 1, paid_orders: 1, quota_reserved_or_confirmed: 980 },
}

function definition(key: string, label: string, formula: string, source: string, numerator: string, denominator: string, unit: string, notes: string): MetricDefinition {
  return { key, label, formula, source, numerator, denominator, unit, notes }
}

function card(key: string, label: string, value: string, numeric: number, tone: string, helper: string): MetricCard {
  return { key, definition_key: key, label, value, numeric, tone, helper }
}

function provider(key: string, label: string, model: string, operation: string, total: number, success: number, failure: number, timeout: number, p95: number, health: string): MetricRow {
  return {
    key,
    provider_id: key,
    provider_group_label: label,
    provider_label: label,
    model_name: model,
    operation,
    capability: operation,
    total,
    success_rate: success,
    failure_rate: failure,
    timeout_rate: timeout,
    p95_duration_ms: p95,
    health_status: health,
    health_message: health === 'warning' ? 'P95 接近阈值' : '正常',
    tone: health === 'warning' ? 'warning' : 'good',
  }
}

function node(key: string, label: string, description: string, total: number, success: number, failure: number, timeout: number, p95: number): MetricRow {
  return { key, system_name: key, label, description, total, success_rate: success, failure_rate: failure, timeout_rate: timeout, p95_duration_ms: p95 }
}

function business(key: string, label: string, total: number, success: number, failure: number, p95: number, output: number): MetricRow {
  return { key, business_type: key, label, total, success_rate: success, failure_rate: failure, p95_duration_ms: p95, output_count: output, failed: Math.round(total * failure / 100), succeeded: Math.round(total * success / 100) }
}

function feature(key: string, label: string, views: number, clicks: number, submits: number, successes: number, downloads: number): MetricRow {
  return { key, feature_key: key, label, views, clicks, ctr: pct(clicks, views), submits, submit_rate: pct(submits, clicks), successes, success_rate: pct(successes, submits), downloads, download_rate: pct(downloads, successes), adoption: clicks + submits + downloads }
}

function dimension(label: string, views: number, clicks: number, submits: number, successes: number, downloads: number, shareValue: number): MetricRow {
  return { key: label, label, views, clicks, submits, successes, downloads, count: views + clicks + submits + successes + downloads, share: shareValue, ctr: pct(clicks, views), submit_rate: pct(submits, clicks), success_rate: pct(successes, submits), download_rate: pct(downloads, successes) }
}

function share(...items: Array<[string, number]>): MetricRow[] {
  const total = items.reduce((sum, [, value]) => sum + value, 0)
  return items.map(([label, count]) => ({ key: label, label, count, share: pct(count, total) }))
}

function pct(numerator: number, denominator: number): number {
  return denominator ? Math.round((numerator * 1000) / denominator) / 10 : 0
}
