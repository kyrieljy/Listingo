from __future__ import annotations

import json
import math
from collections import Counter, defaultdict
from datetime import datetime, timedelta, timezone
from typing import Any, Iterable

from fastapi import Request
from sqlalchemy import select
from sqlalchemy.orm import Session, selectinload

from backend.app.models import (
    AnalyticsEvent,
    AplusJob,
    BatchJob,
    ExecutionLog,
    GenerationJob,
    LoginEvent,
    PaymentOrder,
    Provider,
    QuotaLedger,
    User,
    VideoJob,
    utcnow,
)
from backend.app.services.provider_routing import provider_config
from backend.app.services.redaction import safe_json
from backend.app.services.sms import client_ip


FINAL_STATUSES = {"succeeded", "partial_failed", "failed", "cancelled", "partial_cancelled"}
FAILED_STATUSES = {"failed", "partial_failed"}
OPEN_STATUSES = {"queued", "running", "cancelling"}

BUSINESS_LABELS = {
    "suite": "商品套图",
    "aplus": "A+ 详情",
    "aplus_plan": "A+ 规划",
    "video": "视频",
    "batch_suite": "批量套图",
    "batch_aplus": "批量 A+",
    "aplus_preferences": "A+ 偏好",
}

FEATURE_LABELS = {
    "suite": "商品套图",
    "batch_suite": "批量套图",
    "batch_aplus": "批量 A+",
    "aplus": "A+ 详情",
    "video": "视频",
    "ai_copywriting": "套图 AI 帮写",
    "ai_video_copywriting": "视频 AI 转写",
    "edit": "二次编辑",
    "text_edit": "OCR 改字",
    "download": "下载",
    "history": "历史记录",
    "output_spec": "输出规格",
    "module": "A+ 模块",
    "video_type": "视频类型",
}

NODE_DEFINITIONS = {
    "meta_prompt": {"label": "卖点解析/提示词规划", "description": "读取商品图和卖点，规划套图提示词与画面职责。"},
    "image_generate": {"label": "图片生成", "description": "调用图片模型生成商品套图、A+ 或批量图片。"},
    "image_edit": {"label": "图片二次编辑", "description": "基于当前结果图和修改要求调用改图链路。"},
    "text_ocr": {"label": "OCR 文本识别", "description": "识别图片中的可编辑文字区域和置信度。"},
    "text_edit": {"label": "OCR 改字生成", "description": "按用户改字结果重新生成含文字图片。"},
    "video_meta_prompt": {"label": "视频脚本规划", "description": "根据商品和视频类型规划脚本、镜头和提示词。"},
    "video_submit": {"label": "视频任务提交", "description": "向视频模型提交生成任务并记录远程任务号。"},
    "video_generate": {"label": "视频生成/轮询落地", "description": "轮询视频模型状态并落地最终视频结果。"},
    "aplus_plan": {"label": "A+ 模块规划", "description": "生成 A+ 模块结构、文案要求和图片提示词。"},
    "aplus_generate": {"label": "A+ 图片生成", "description": "按 A+ 模块和输出规格调用图片模型。"},
    "batch_scheduler": {"label": "批量任务调度", "description": "调度批量商品任务并控制并发执行。"},
    "content_safety": {"label": "内容安全检查", "description": "检查输入、规划文本和生成结果中的安全风险。"},
}

METRIC_DEFINITIONS = {
    "total_calls": {
        "label": "总调用数",
        "formula": "ExecutionLog 真实任务调用数",
        "source": "execution_log",
        "numerator": "窗口内 dry_run=false 的调用记录",
        "denominator": "无",
        "unit": "次",
        "notes": "默认排除后台测试和安全演示模式；时间窗口为 [start_at, end_at]。",
    },
    "success_rate": {
        "label": "成功率",
        "formula": "成功次数 / 总调用数",
        "source": "execution_log.status",
        "numerator": "status = succeeded",
        "denominator": "窗口内总调用数",
        "unit": "%",
        "notes": "没有样本时显示 0%，避免把无数据误判为 100%。",
    },
    "failure_rate": {
        "label": "失败率",
        "formula": "失败次数 / 总调用数",
        "source": "execution_log.status + execution_log.error",
        "numerator": "status in failed/partial_failed 或 error 非空",
        "denominator": "窗口内总调用数",
        "unit": "%",
        "notes": "部分失败计入失败，便于排查链路质量。",
    },
    "p95_latency": {
        "label": "P95耗时",
        "formula": "窗口内 duration_ms 的 95 分位",
        "source": "execution_log.duration_ms",
        "numerator": "非空耗时样本",
        "denominator": "无",
        "unit": "ms/s/min",
        "notes": "用于观察尾部延迟；平均值会同时在表格展示。",
    },
    "timeout_rate": {
        "label": "超时率",
        "formula": "超时调用数 / 总调用数",
        "source": "execution_log.error + provider.config.timeout_seconds",
        "numerator": "错误含 timeout/超时，或耗时超过模型配置超时阈值",
        "denominator": "窗口内总调用数",
        "unit": "%",
        "notes": "没有配置超时时，只按错误文本判断。",
    },
    "queue": {
        "label": "进行中",
        "formula": "queued + running + cancelling",
        "source": "generation/aplus/video/batch job status",
        "numerator": "未进入最终态的任务",
        "denominator": "无",
        "unit": "个",
        "notes": "用于判断积压和卡住的任务。",
    },
    "provider_health": {
        "label": "中转站健康",
        "formula": "健康中转站数 / 全部中转站模型数",
        "source": "provider + execution_log + provider health config",
        "numerator": "未触发成功率、P95、健康检查异常阈值的模型",
        "denominator": "全部配置模型",
        "unit": "个",
        "notes": "同时参考启用状态、密钥状态和最近健康检查。",
    },
    "active_users": {
        "label": "活跃用户",
        "formula": "窗口内有登录、埋点或任务行为的去重用户数",
        "source": "analytics_event + login_event + jobs",
        "numerator": "去重 user_id",
        "denominator": "无",
        "unit": "人",
        "notes": "匿名事件不计入用户数，但仍进入功能事件统计。",
    },
    "new_users": {
        "label": "新增用户",
        "formula": "窗口内创建的用户数",
        "source": "app_user.created_at",
        "numerator": "created_at 在窗口内的用户",
        "denominator": "无",
        "unit": "人",
        "notes": "按账号创建时间统计。",
    },
    "returning_users": {
        "label": "回访用户",
        "formula": "活跃用户中 created_at 早于窗口开始的用户数",
        "source": "app_user + activity sources",
        "numerator": "老用户且窗口内活跃",
        "denominator": "窗口内活跃用户",
        "unit": "人",
        "notes": "用于区分新客增长和老客回访。",
    },
    "feature_ctr": {
        "label": "点击率",
        "formula": "点击数 / 曝光数",
        "source": "analytics_event.event_type",
        "numerator": "event_type = click",
        "denominator": "event_type = view",
        "unit": "%",
        "notes": "按 feature_key 聚合；没有曝光时点击率为 0%。",
    },
    "submit_rate": {
        "label": "提交率",
        "formula": "提交数 / 点击数",
        "source": "analytics_event + jobs",
        "numerator": "event_type = submit，加上任务创建数",
        "denominator": "event_type = click",
        "unit": "%",
        "notes": "用于判断点击后的真实使用意图。",
    },
    "download_rate": {
        "label": "下载率",
        "formula": "下载数 / 成功数",
        "source": "analytics_event + jobs",
        "numerator": "event_type = download 或 feature_key=download",
        "denominator": "成功任务数",
        "unit": "%",
        "notes": "反映生成结果是否被使用。",
    },
    "paid_conversion_rate": {
        "label": "支付转化率",
        "formula": "已支付订单数 / 订单创建数",
        "source": "payment_order.status",
        "numerator": "status = paid",
        "denominator": "窗口内订单数",
        "unit": "%",
        "notes": "第一版不含外部支付渠道归因。",
    },
    "quota_usage_rate": {
        "label": "额度使用率",
        "formula": "已预留或确认额度 / 月额度",
        "source": "quota_ledger + plan_quota_rule",
        "numerator": "quota_ledger status in reserved/confirmed 的 amount",
        "denominator": "用户当前套餐月额度",
        "unit": "%",
        "notes": "无限额度套餐不计入总体使用率分母。",
    },
}


def resolve_window(start_at: datetime | None, end_at: datetime | None) -> tuple[datetime, datetime]:
    end = _as_utc(end_at) or utcnow()
    start = _as_utc(start_at) or end - timedelta(days=7)
    if start > end:
        raise ValueError("start_at must be earlier than end_at")
    return start, end


def record_analytics_event(
    session: Session,
    request: Request,
    payload: Any,
    *,
    user_id: str | None = None,
) -> AnalyticsEvent:
    metadata = payload.metadata if isinstance(payload.metadata, dict) else {}
    event = AnalyticsEvent(
        user_id=user_id,
        session_id=_truncate(payload.session_id, 80),
        event_name=_truncate(payload.event_name, 120),
        event_type=_truncate(payload.event_type or "click", 40),
        surface=_truncate(payload.surface, 80),
        business_type=_truncate(payload.business_type, 40),
        feature_key=_truncate(payload.feature_key, 80),
        platform=_truncate(payload.platform, 80),
        market=_truncate(payload.market, 80),
        language=_truncate(payload.language, 80),
        metadata_json=safe_json(metadata),
        ip_address=client_ip(request),
        user_agent=request.headers.get("user-agent", "")[:1000],
    )
    session.add(event)
    session.flush()
    return event


def analytics_event_dict(event: AnalyticsEvent) -> dict[str, Any]:
    return {
        "id": event.id,
        "user_id": event.user_id,
        "session_id": event.session_id,
        "event_name": event.event_name,
        "event_type": event.event_type,
        "surface": event.surface,
        "business_type": event.business_type,
        "feature_key": event.feature_key,
        "platform": event.platform,
        "market": event.market,
        "language": event.language,
        "metadata": _loads(event.metadata_json, {}),
        "created_at": event.created_at,
    }


def build_ops_monitoring(
    session: Session,
    *,
    start_at: datetime,
    end_at: datetime,
    granularity: str = "day",
) -> dict[str, Any]:
    logs = session.scalars(
        select(ExecutionLog)
        .where(ExecutionLog.created_at >= start_at, ExecutionLog.created_at <= end_at)
        .where(ExecutionLog.dry_run.is_(False))
        .order_by(ExecutionLog.created_at.asc())
    ).all()
    providers = session.scalars(select(Provider)).all()
    provider_by_id = {provider.id: provider for provider in providers}
    jobs = _ops_job_records(session, start_at, end_at)

    total_logs = len(logs)
    failed_logs = sum(1 for log in logs if log.status in FAILED_STATUSES or log.error)
    succeeded_logs = sum(1 for log in logs if log.status == "succeeded")
    timeout_logs = sum(1 for log in logs if _is_timeout_log(log, provider_by_id))
    durations = [int(log.duration_ms) for log in logs if log.duration_ms is not None]
    open_count = sum(row["count"] for row in _queue_rows(session))

    provider_rows = _provider_rows(providers, logs)
    node_rows = _counter_rows(
        logs,
        key_fn=lambda log: log.node or "unknown",
        label_fn=lambda key: _node_label(key),
        duration_fn=lambda log: log.duration_ms,
        timeout_fn=lambda log: _is_timeout_log(log, provider_by_id),
    )
    for row in node_rows:
        row["system_name"] = row["key"]
        row["description"] = _node_description(row["key"])
    business_rows = _business_rows(jobs)
    timeseries = _ops_timeseries(logs, jobs, granularity, provider_by_id)

    success_rate = _pct(succeeded_logs, total_logs)
    failure_rate = _pct(failed_logs, total_logs)
    timeout_rate = _pct(timeout_logs, total_logs)
    p95 = _p95(durations)
    critical_providers = sum(1 for row in provider_rows if row["tone"] == "danger")
    warning_providers = sum(1 for row in provider_rows if row["tone"] == "warning")

    return {
        "window": _window_dict(start_at, end_at, granularity),
        "metric_definitions": _metric_definitions(
            [
                "total_calls",
                "success_rate",
                "failure_rate",
                "p95_latency",
                "timeout_rate",
                "queue",
                "provider_health",
            ]
        ),
        "node_definitions": NODE_DEFINITIONS,
        "summary_cards": [
            {
                "key": "total_calls",
                "definition_key": "total_calls",
                "label": "总调用数",
                "value": str(total_logs),
                "numeric": total_logs,
                "tone": "neutral",
                "helper": f"{len(durations)} 条耗时样本",
            },
            {
                "key": "success_rate",
                "definition_key": "success_rate",
                "label": "成功率",
                "value": f"{success_rate:.1f}%",
                "numeric": success_rate,
                "tone": _rate_tone(success_rate, total_logs),
                "helper": f"{succeeded_logs}/{total_logs} 次节点成功",
            },
            {
                "key": "failure_rate",
                "definition_key": "failure_rate",
                "label": "失败率",
                "value": f"{failure_rate:.1f}%",
                "numeric": failure_rate,
                "tone": "danger" if failure_rate >= 10 else "warning" if failure_rate >= 5 else "good",
                "helper": f"{failed_logs} 次异常",
            },
            {
                "key": "p95_latency",
                "definition_key": "p95_latency",
                "label": "P95耗时",
                "value": _duration_label(p95),
                "numeric": p95,
                "tone": _latency_tone(p95),
                "helper": f"{len(durations)} 条耗时样本",
            },
            {
                "key": "timeout_rate",
                "definition_key": "timeout_rate",
                "label": "超时率",
                "value": f"{timeout_rate:.1f}%",
                "numeric": timeout_rate,
                "tone": "danger" if timeout_rate >= 5 else "warning" if timeout_rate >= 2 else "good",
                "helper": f"{timeout_logs} 次超时",
            },
            {
                "key": "queue",
                "definition_key": "queue",
                "label": "进行中",
                "value": str(open_count),
                "numeric": open_count,
                "tone": "danger" if open_count >= 20 else "warning" if open_count >= 8 else "good",
                "helper": "queued / running / cancelling",
            },
            {
                "key": "provider_health",
                "definition_key": "provider_health",
                "label": "中转站健康",
                "value": f"{max(0, len(provider_rows) - critical_providers)}/{len(provider_rows)}",
                "numeric": len(provider_rows) - critical_providers,
                "tone": "danger" if critical_providers else "warning" if warning_providers else "good",
                "helper": f"{warning_providers} 预警，{critical_providers} 异常",
            },
        ],
        "provider_rows": provider_rows,
        "node_rows": node_rows,
        "business_rows": business_rows,
        "queue_rows": _queue_rows(session),
        "timeseries": timeseries,
        "series": {
            "link_trend": timeseries,
            "providers": _provider_series(provider_rows),
            "nodes": _comparison_series(node_rows, "key"),
            "businesses": _comparison_series(business_rows, "business_type"),
        },
        "comparison_rows": {
            "providers": provider_rows,
            "nodes": node_rows,
            "businesses": business_rows,
            "queues": _queue_rows(session),
        },
        "incident_rows": _incident_rows(logs, provider_by_id),
        "available_filters": {
            "granularity": ["hour", "day", "week"],
            "providers": [
                {"key": provider.id, "label": provider.label, "group": provider_config(provider).get("provider_group_label") or "中转站"}
                for provider in providers
            ],
            "nodes": [{"key": key, "label": value["label"], "description": value["description"]} for key, value in NODE_DEFINITIONS.items()],
            "business_types": [{"key": key, "label": label} for key, label in BUSINESS_LABELS.items()],
        },
        "thresholds": {
            "success_rate_warning": 95,
            "success_rate_danger": 90,
            "p95_latency_warning_ms": 60_000,
            "p95_latency_danger_ms": 120_000,
            "timeout_rate_warning": 2,
            "timeout_rate_danger": 5,
            "queue_warning": 8,
            "queue_danger": 20,
        },
    }


def build_business_metrics(
    session: Session,
    *,
    start_at: datetime,
    end_at: datetime,
    granularity: str = "day",
) -> dict[str, Any]:
    events = session.scalars(
        select(AnalyticsEvent)
        .where(AnalyticsEvent.created_at >= start_at, AnalyticsEvent.created_at <= end_at)
        .order_by(AnalyticsEvent.created_at.asc())
    ).all()
    users = session.scalars(select(User)).all()
    login_events = session.scalars(
        select(LoginEvent).where(LoginEvent.created_at >= start_at, LoginEvent.created_at <= end_at)
    ).all()
    orders = session.scalars(
        select(PaymentOrder).where(PaymentOrder.created_at >= start_at, PaymentOrder.created_at <= end_at)
    ).all()
    quota_ledgers = session.scalars(
        select(QuotaLedger).where(QuotaLedger.created_at >= start_at, QuotaLedger.created_at <= end_at)
    ).all()
    jobs = _business_job_records(session, start_at, end_at)
    users_by_id = {user.id: user for user in users}

    active_users = {
        value
        for value in (
            [event.user_id for event in events]
            + [event.user_id for event in login_events]
            + [job["user_id"] for job in jobs]
        )
        if value
    }
    new_users = [user for user in users if _between(user.created_at, start_at, end_at)]
    returning_users = [
        user
        for user_id in active_users
        if (user := users_by_id.get(user_id)) and not _between(user.created_at, start_at, end_at)
    ]
    core_jobs = [job for job in jobs if job["business_type"] in {"suite", "aplus", "video", "batch_suite", "batch_aplus"}]
    successful_jobs = [job for job in core_jobs if job["status"] == "succeeded"]
    download_events = [event for event in events if event.event_type == "download" or event.feature_key == "download"]
    paid_orders = [order for order in orders if order.status == "paid"]

    feature_rows = _feature_rows(events, core_jobs)
    platform_rows = _platform_rows(jobs, events)
    ratio_rows = _ratio_rows(jobs, events)
    module_rows = _module_rows(jobs, events)
    video_type_rows = _video_type_rows(jobs, events)
    profile_rows = _profile_rows(users, active_users, feature_rows, platform_rows)
    event_relation_rows = _event_relation_rows(events, core_jobs)
    subscription_rows = _subscription_rows(users, orders, quota_ledgers)
    user_rows = _user_summary_rows(users, events, jobs, orders, quota_ledgers)

    top_feature_ctr = max((row["ctr"] for row in feature_rows), default=0)
    return {
        "window": _window_dict(start_at, end_at, granularity),
        "metric_definitions": _metric_definitions(
            [
                "active_users",
                "new_users",
                "returning_users",
                "feature_ctr",
                "submit_rate",
                "download_rate",
                "paid_conversion_rate",
                "quota_usage_rate",
            ]
        ),
        "summary_cards": [
            {
                "key": "active_users",
                "definition_key": "active_users",
                "label": "活跃用户",
                "value": str(len(active_users)),
                "numeric": len(active_users),
                "tone": "neutral",
                "helper": f"新增 {len(new_users)} 人",
            },
            {
                "key": "new_users",
                "definition_key": "new_users",
                "label": "新增用户",
                "value": str(len(new_users)),
                "numeric": len(new_users),
                "tone": "neutral",
                "helper": f"回访 {len(returning_users)} 人",
            },
            {
                "key": "returning_users",
                "definition_key": "returning_users",
                "label": "回访用户",
                "value": str(len(returning_users)),
                "numeric": len(returning_users),
                "tone": "neutral",
                "helper": f"活跃用户占比 {_pct(len(returning_users), len(active_users)):.1f}%",
            },
            {
                "key": "core_jobs",
                "label": "核心任务",
                "value": str(len(core_jobs)),
                "numeric": len(core_jobs),
                "tone": "neutral",
                "helper": f"成功 {len(successful_jobs)} 个",
            },
            {
                "key": "feature_ctr",
                "definition_key": "feature_ctr",
                "label": "最高点击率",
                "value": f"{top_feature_ctr:.1f}%",
                "numeric": top_feature_ctr,
                "tone": "good" if top_feature_ctr else "neutral",
                "helper": "基于曝光/点击事件",
            },
            {
                "key": "downloads",
                "definition_key": "download_rate",
                "label": "下载行为",
                "value": str(len(download_events)),
                "numeric": len(download_events),
                "tone": "neutral",
                "helper": "图片、A+、视频、批量",
            },
            {
                "key": "paid_orders",
                "definition_key": "paid_conversion_rate",
                "label": "已支付订单",
                "value": str(len(paid_orders)),
                "numeric": len(paid_orders),
                "tone": "good" if paid_orders else "neutral",
                "helper": f"订单总数 {len(orders)} / 转化 {_pct(len(paid_orders), len(orders)):.1f}%",
            },
        ],
        "feature_rows": feature_rows,
        "platform_rows": platform_rows,
        "ratio_rows": ratio_rows,
        "module_rows": module_rows,
        "video_type_rows": video_type_rows,
        "profile_rows": profile_rows,
        "trend_rows": _business_timeseries(events, jobs, granularity),
        "event_relation_rows": event_relation_rows,
        "subscription_rows": subscription_rows,
        "user_rows": user_rows,
        "series": {
            "funnel": event_relation_rows,
            "platforms": _dimension_series(platform_rows),
            "ratios": _dimension_series(ratio_rows),
            "modules": _dimension_series(module_rows),
            "video_types": _dimension_series(video_type_rows),
            "trend": _business_timeseries(events, jobs, granularity),
        },
        "comparison_rows": {
            "features": feature_rows,
            "platforms": platform_rows,
            "ratios": ratio_rows,
            "modules": module_rows,
            "video_types": video_type_rows,
            "subscriptions": subscription_rows,
        },
        "available_filters": {
            "granularity": ["hour", "day", "week"],
            "features": [{"key": key, "label": label} for key, label in FEATURE_LABELS.items()],
            "platforms": [{"key": row["key"], "label": row["label"]} for row in platform_rows],
        },
        "event_sample_rows": [analytics_event_dict(event) for event in events[-20:]][::-1],
    }


def build_business_metric_users(
    session: Session,
    *,
    start_at: datetime,
    end_at: datetime,
    limit: int = 50,
) -> dict[str, Any]:
    events = session.scalars(
        select(AnalyticsEvent)
        .where(AnalyticsEvent.created_at >= start_at, AnalyticsEvent.created_at <= end_at)
        .order_by(AnalyticsEvent.created_at.asc())
    ).all()
    users = session.scalars(select(User)).all()
    orders = session.scalars(select(PaymentOrder).where(PaymentOrder.created_at >= start_at, PaymentOrder.created_at <= end_at)).all()
    quota_ledgers = session.scalars(
        select(QuotaLedger).where(QuotaLedger.created_at >= start_at, QuotaLedger.created_at <= end_at)
    ).all()
    jobs = _business_job_records(session, start_at, end_at)
    rows = _user_summary_rows(users, events, jobs, orders, quota_ledgers)
    return {
        "window": _window_dict(start_at, end_at, "day"),
        "metric_definitions": _metric_definitions(["active_users", "quota_usage_rate"]),
        "users": rows[:limit],
    }


def build_business_user_metrics(
    session: Session,
    user_id: str,
    *,
    start_at: datetime,
    end_at: datetime,
    granularity: str = "day",
) -> dict[str, Any] | None:
    user = session.get(User, user_id)
    if not user:
        return None
    events = session.scalars(
        select(AnalyticsEvent)
        .where(
            AnalyticsEvent.user_id == user_id,
            AnalyticsEvent.created_at >= start_at,
            AnalyticsEvent.created_at <= end_at,
        )
        .order_by(AnalyticsEvent.created_at.asc())
    ).all()
    orders = session.scalars(
        select(PaymentOrder).where(
            PaymentOrder.user_id == user_id,
            PaymentOrder.created_at >= start_at,
            PaymentOrder.created_at <= end_at,
        )
    ).all()
    quota_ledgers = session.scalars(
        select(QuotaLedger).where(
            QuotaLedger.user_id == user_id,
            QuotaLedger.created_at >= start_at,
            QuotaLedger.created_at <= end_at,
        )
    ).all()
    jobs = [job for job in _business_job_records(session, start_at, end_at) if job.get("user_id") == user_id]
    core_jobs = [job for job in jobs if job["business_type"] in {"suite", "aplus", "video", "batch_suite", "batch_aplus"}]
    feature_rows = _feature_rows(events, core_jobs)
    downloads = [event for event in events if event.event_type == "download" or event.feature_key == "download"]
    successful_jobs = [job for job in core_jobs if job["status"] == "succeeded"]
    paid_orders = [order for order in orders if order.status == "paid"]
    timeline = _user_timeline(events, jobs)
    return {
        "window": _window_dict(start_at, end_at, granularity),
        "metric_definitions": _metric_definitions(
            ["feature_ctr", "submit_rate", "download_rate", "paid_conversion_rate", "quota_usage_rate"]
        ),
        "user": _user_identity(user),
        "summary_cards": [
            {
                "key": "events",
                "label": "行为事件",
                "value": str(len(events)),
                "numeric": len(events),
                "tone": "neutral",
                "helper": f"{len(set(event.session_id for event in events if event.session_id))} 个会话",
            },
            {
                "key": "core_jobs",
                "label": "核心任务",
                "value": str(len(core_jobs)),
                "numeric": len(core_jobs),
                "tone": "neutral",
                "helper": f"成功 {len(successful_jobs)} 个",
            },
            {
                "key": "downloads",
                "definition_key": "download_rate",
                "label": "下载行为",
                "value": str(len(downloads)),
                "numeric": len(downloads),
                "tone": "neutral",
                "helper": f"下载率 {_pct(len(downloads), len(successful_jobs)):.1f}%",
            },
            {
                "key": "paid_orders",
                "definition_key": "paid_conversion_rate",
                "label": "支付订单",
                "value": str(len(paid_orders)),
                "numeric": len(paid_orders),
                "tone": "good" if paid_orders else "neutral",
                "helper": f"订单 {len(orders)} 个",
            },
        ],
        "feature_rows": feature_rows,
        "platform_rows": _platform_rows(jobs, events),
        "ratio_rows": _ratio_rows(jobs, events),
        "module_rows": _module_rows(jobs, events),
        "video_type_rows": _video_type_rows(jobs, events),
        "trend_rows": _business_timeseries(events, jobs, granularity),
        "timeline_rows": timeline,
        "subscription_rows": _subscription_rows([user], orders, quota_ledgers),
        "plan_behavior": {
            "current_plan": user.current_plan_code,
            "orders": len(orders),
            "paid_orders": len(paid_orders),
            "quota_reserved_or_confirmed": sum(
                ledger.amount for ledger in quota_ledgers if ledger.status in {"reserved", "confirmed"}
            ),
        },
    }


def _ops_job_records(session: Session, start_at: datetime, end_at: datetime) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for job in session.scalars(
        select(GenerationJob).where(
            GenerationJob.created_at >= start_at,
            GenerationJob.created_at <= end_at,
            GenerationJob.is_admin_test.is_(False),
            GenerationJob.dry_run.is_(False),
        )
    ).all():
        rows.append(_job_row("suite", job))
    for job in session.scalars(
        select(AplusJob).where(
            AplusJob.created_at >= start_at,
            AplusJob.created_at <= end_at,
            AplusJob.is_admin_test.is_(False),
            AplusJob.dry_run.is_(False),
        )
    ).all():
        rows.append(_job_row("aplus" if job.job_type == "generation" else "aplus_plan", job))
    for job in session.scalars(
        select(VideoJob).where(
            VideoJob.created_at >= start_at,
            VideoJob.created_at <= end_at,
            VideoJob.is_admin_test.is_(False),
            VideoJob.dry_run.is_(False),
        )
    ).all():
        rows.append(_job_row("video", job))
    for job in session.scalars(
        select(BatchJob).where(BatchJob.created_at >= start_at, BatchJob.created_at <= end_at)
    ).all():
        rows.append(_job_row(f"batch_{job.business_type}", job))
    return rows


def _business_job_records(session: Session, start_at: datetime, end_at: datetime) -> list[dict[str, Any]]:
    rows = _ops_job_records(session, start_at, end_at)
    aplus_jobs = session.scalars(
        select(AplusJob)
        .where(
            AplusJob.created_at >= start_at,
            AplusJob.created_at <= end_at,
            AplusJob.is_admin_test.is_(False),
            AplusJob.dry_run.is_(False),
        )
        .options(selectinload(AplusJob.items))
    ).all()
    rows.extend(_aplus_preference_rows(job) for job in aplus_jobs if job.job_type == "plan")
    return rows


def _aplus_preference_rows(job: AplusJob) -> dict[str, Any]:
    row = _job_row("aplus_preferences", job)
    row["items"] = [
        {
            "module_name": item.module_name,
            "output_mode": item.output_mode,
            "aspect_ratio": item.aspect_ratio,
        }
        for item in job.items
    ]
    return row


def _job_row(business_type: str, job: Any) -> dict[str, Any]:
    params_json = getattr(job, "params_json", None) or getattr(job, "global_params_json", "{}")
    return {
        "id": job.id,
        "user_id": getattr(job, "user_id", None),
        "business_type": business_type,
        "label": BUSINESS_LABELS.get(business_type, business_type),
        "status": job.status,
        "dry_run": bool(getattr(job, "dry_run", False)),
        "params": _loads(params_json, {}),
        "asset_ids": _loads(getattr(job, "asset_ids_json", "[]"), []),
        "count": int(getattr(job, "count", 1) or 0),
        "created_at": job.created_at,
        "started_at": getattr(job, "started_at", None),
        "completed_at": getattr(job, "completed_at", None),
    }


def _provider_rows(providers: list[Provider], logs: list[ExecutionLog]) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    logs_by_provider: dict[str | None, list[ExecutionLog]] = defaultdict(list)
    for log in logs:
        logs_by_provider[log.provider_id].append(log)
    for provider in providers:
        provider_logs = logs_by_provider.get(provider.id, [])
        durations = [int(log.duration_ms) for log in provider_logs if log.duration_ms is not None]
        total = len(provider_logs)
        failed = sum(1 for log in provider_logs if log.status in FAILED_STATUSES or log.error)
        succeeded = sum(1 for log in provider_logs if log.status == "succeeded")
        timeout_count = sum(1 for log in provider_logs if _is_timeout_log(log, {provider.id: provider}))
        success_rate = _pct(succeeded, total)
        config = provider_config(provider)
        health = config.get("health") if isinstance(config.get("health"), dict) else {}
        p95 = _p95(durations)
        last_error_log = next((log for log in sorted(provider_logs, key=lambda item: item.created_at, reverse=True) if log.error), None)
        node_counts = Counter((log.node or "unknown") for log in provider_logs)
        tone = _provider_tone(total, success_rate, p95, health)
        rows.append(
            {
                "provider_id": provider.id,
                "provider_code": provider.code,
                "provider_label": provider.label,
                "model_name": provider.model_name,
                "provider_group": config.get("provider_group") or "",
                "provider_group_label": config.get("provider_group_label") or "中转站",
                "capability": provider.capability,
                "operation": config.get("operation") or "",
                "enabled": provider.enabled,
                "has_api_key": bool(provider.encrypted_api_key),
                "total": total,
                "succeeded": succeeded,
                "failed": failed,
                "success_rate": success_rate,
                "failure_rate": _pct(failed, total),
                "timeout_count": timeout_count,
                "timeout_rate": _pct(timeout_count, total),
                "avg_duration_ms": _avg(durations),
                "p50_duration_ms": _percentile(durations, 50),
                "p95_duration_ms": p95,
                "p99_duration_ms": _percentile(durations, 99),
                "health_status": health.get("status") or "unknown",
                "health_latency_ms": int(health.get("latency_ms") or 0),
                "health_message": health.get("message") or "",
                "last_error": last_error_log.error if last_error_log else "",
                "node_rows": [
                    {"key": key, "label": _node_label(key), "count": count}
                    for key, count in node_counts.most_common(8)
                ],
                "tone": tone,
            }
        )
    rows.sort(key=lambda row: (row["tone"] != "danger", row["tone"] != "warning", -row["total"], row["provider_label"]))
    return rows


def _counter_rows(
    rows: Iterable[Any],
    *,
    key_fn: Any,
    label_fn: Any,
    duration_fn: Any | None = None,
    timeout_fn: Any | None = None,
) -> list[dict[str, Any]]:
    buckets: dict[str, list[Any]] = defaultdict(list)
    for row in rows:
        buckets[str(key_fn(row))].append(row)
    result: list[dict[str, Any]] = []
    for key, bucket in buckets.items():
        durations = [int(duration_fn(row)) for row in bucket if duration_fn and duration_fn(row) is not None]
        total = len(bucket)
        failed = sum(1 for row in bucket if getattr(row, "status", "") in FAILED_STATUSES or getattr(row, "error", None))
        succeeded = sum(1 for row in bucket if getattr(row, "status", "") == "succeeded")
        timeout_count = sum(1 for row in bucket if timeout_fn and timeout_fn(row))
        result.append(
            {
                "key": key,
                "label": label_fn(key),
                "total": total,
                "succeeded": succeeded,
                "failed": failed,
                "success_rate": _pct(succeeded, total),
                "failure_rate": _pct(failed, total),
                "timeout_count": timeout_count,
                "timeout_rate": _pct(timeout_count, total),
                "avg_duration_ms": _avg(durations),
                "p50_duration_ms": _percentile(durations, 50),
                "p95_duration_ms": _p95(durations),
                "p99_duration_ms": _percentile(durations, 99),
            }
        )
    result.sort(key=lambda row: (-row["total"], row["label"]))
    return result


def _business_rows(jobs: list[dict[str, Any]]) -> list[dict[str, Any]]:
    buckets: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for job in jobs:
        buckets[job["business_type"]].append(job)
    result: list[dict[str, Any]] = []
    for business_type, bucket in buckets.items():
        durations = [
            _elapsed_ms(job.get("started_at") or job.get("created_at"), job.get("completed_at"))
            for job in bucket
            if job.get("completed_at")
        ]
        result.append(
            {
                "business_type": business_type,
                "label": BUSINESS_LABELS.get(business_type, business_type),
                "total": len(bucket),
                "succeeded": sum(1 for job in bucket if job["status"] == "succeeded"),
                "failed": sum(1 for job in bucket if job["status"] in FAILED_STATUSES),
                "partial_failed": sum(1 for job in bucket if job["status"] == "partial_failed"),
                "cancelled": sum(1 for job in bucket if "cancelled" in job["status"]),
                "running": sum(1 for job in bucket if job["status"] in OPEN_STATUSES),
                "success_rate": _pct(sum(1 for job in bucket if job["status"] == "succeeded"), len(bucket)),
                "failure_rate": _pct(sum(1 for job in bucket if job["status"] in FAILED_STATUSES), len(bucket)),
                "avg_duration_ms": _avg([value for value in durations if value is not None]),
                "p95_duration_ms": _p95([value for value in durations if value is not None]),
                "output_count": sum(int(job.get("count") or 0) for job in bucket),
            }
        )
    result.sort(key=lambda row: (-row["total"], row["label"]))
    return result


def _queue_rows(session: Session) -> list[dict[str, Any]]:
    specs = [
        ("suite", "商品套图", GenerationJob),
        ("aplus", "A+ 详情", AplusJob),
        ("video", "视频", VideoJob),
        ("batch", "批量任务", BatchJob),
    ]
    rows: list[dict[str, Any]] = []
    for key, label, model in specs:
        query = select(model).where(model.status.in_(OPEN_STATUSES))
        if hasattr(model, "dry_run"):
            query = query.where(model.dry_run.is_(False))
        records = session.scalars(query).all()
        rows.append(
            {
                "key": key,
                "label": label,
                "count": len(records),
                "queued": sum(1 for item in records if item.status == "queued"),
                "running": sum(1 for item in records if item.status == "running"),
                "cancelling": sum(1 for item in records if item.status == "cancelling"),
                "oldest_created_at": min((_as_utc(item.created_at) for item in records), default=None),
                "oldest_wait_seconds": max(
                    (
                        int((utcnow() - created_at).total_seconds())
                        for created_at in [_as_utc(item.created_at) for item in records]
                        if created_at
                    ),
                    default=0,
                ),
            }
        )
    return rows


def _incident_rows(logs: list[ExecutionLog], provider_by_id: dict[str, Provider]) -> list[dict[str, Any]]:
    rows = [log for log in logs if log.status in FAILED_STATUSES or log.error]
    rows.sort(key=lambda log: log.created_at, reverse=True)
    return [
        {
            "id": log.id,
            "created_at": log.created_at,
            "node": log.node,
            "node_label": _node_label(log.node),
            "status": log.status,
            "provider_label": provider_by_id.get(log.provider_id).label if log.provider_id in provider_by_id else "",
            "job_id": log.job_id,
            "duration_ms": log.duration_ms or 0,
            "error": log.error or "",
            "error_category": _error_category(log.error or log.status),
        }
        for log in rows[:20]
    ]


def _ops_timeseries(
    logs: list[ExecutionLog],
    jobs: list[dict[str, Any]],
    granularity: str,
    provider_by_id: dict[str, Provider],
) -> list[dict[str, Any]]:
    buckets: dict[str, dict[str, Any]] = defaultdict(
        lambda: {"succeeded": 0, "failed": 0, "timeout": 0, "total": 0, "jobs": 0, "durations": []}
    )
    for log in logs:
        key = _bucket_key(log.created_at, granularity)
        bucket = buckets[key]
        bucket["total"] += 1
        if log.status == "succeeded":
            bucket["succeeded"] += 1
        if log.status in FAILED_STATUSES or log.error:
            bucket["failed"] += 1
        if _is_timeout_log(log, provider_by_id):
            bucket["timeout"] += 1
        if log.duration_ms is not None:
            bucket["durations"].append(int(log.duration_ms))
    for job in jobs:
        key = _bucket_key(job["created_at"], granularity)
        buckets[key]["jobs"] += 1
    return [
        {
            "bucket": key,
            "succeeded": value["succeeded"],
            "failed": value["failed"],
            "timeout": value["timeout"],
            "total": value["total"],
            "jobs": value["jobs"],
            "success_rate": _pct(value["succeeded"], value["total"]),
            "failure_rate": _pct(value["failed"], value["total"]),
            "timeout_rate": _pct(value["timeout"], value["total"]),
            "avg_duration_ms": _avg(value["durations"]),
            "p95_duration_ms": _p95(value["durations"]),
            "p99_duration_ms": _percentile(value["durations"], 99),
        }
        for key, value in sorted(buckets.items())
    ]


def _feature_rows(events: list[AnalyticsEvent], jobs: list[dict[str, Any]]) -> list[dict[str, Any]]:
    by_feature: dict[str, list[AnalyticsEvent]] = defaultdict(list)
    for event in events:
        key = event.feature_key or event.business_type or event.event_name
        by_feature[key].append(event)
    job_counts = Counter(job["business_type"] for job in jobs)
    success_counts = Counter(job["business_type"] for job in jobs if job["status"] == "succeeded")
    result: list[dict[str, Any]] = []
    for key in sorted(set(FEATURE_LABELS) | set(by_feature) | set(job_counts)):
        bucket = by_feature.get(key, [])
        views = sum(1 for event in bucket if event.event_type == "view")
        clicks = sum(1 for event in bucket if event.event_type == "click")
        submits = sum(1 for event in bucket if event.event_type == "submit") + job_counts.get(key, 0)
        downloads = sum(1 for event in bucket if event.event_type == "download")
        successes = success_counts.get(key, 0)
        result.append(
            {
                "feature_key": key,
                "label": FEATURE_LABELS.get(key) or BUSINESS_LABELS.get(key) or key,
                "views": views,
                "clicks": clicks,
                "ctr": _pct(clicks, views),
                "submits": submits,
                "submit_rate": _pct(submits, clicks),
                "successes": successes,
                "success_rate": _pct(successes, submits),
                "downloads": downloads,
                "download_rate": _pct(downloads, successes),
                "adoption": clicks + submits + downloads,
            }
        )
    result.sort(key=lambda row: (-row["adoption"], row["label"]))
    return result


def _platform_rows(jobs: list[dict[str, Any]], events: list[AnalyticsEvent]) -> list[dict[str, Any]]:
    return _dimension_metric_rows(
        jobs,
        events,
        dimension="platform",
        event_values=lambda event: [event.platform] if event.platform else [],
        job_values=lambda job: [str(_effective_params(job).get("platform") or "").strip()],
    )


def _ratio_rows(jobs: list[dict[str, Any]], events: list[AnalyticsEvent]) -> list[dict[str, Any]]:
    def event_values(event: AnalyticsEvent) -> list[str]:
        metadata = _loads(event.metadata_json, {})
        values = [metadata.get("ratio"), metadata.get("aspect_ratio")]
        values.extend(
            target.get("aspect_ratio")
            for target in metadata.get("output_targets", [])
            if isinstance(target, dict)
        )
        return [str(value).strip() for value in values if value]

    def job_values(job: dict[str, Any]) -> list[str]:
        params = _effective_params(job)
        values = [params.get("aspect_ratio"), params.get("ratio")]
        values.extend(
            target.get("aspect_ratio")
            for target in params.get("output_targets") or []
            if isinstance(target, dict)
        )
        return [str(value).strip() for value in values if value]

    return _dimension_metric_rows(jobs, events, dimension="ratio", event_values=event_values, job_values=job_values)


def _module_rows(jobs: list[dict[str, Any]], events: list[AnalyticsEvent]) -> list[dict[str, Any]]:
    def event_values(event: AnalyticsEvent) -> list[str]:
        metadata = _loads(event.metadata_json, {})
        return [str(metadata.get("module_name") or "").strip()] if metadata.get("module_name") else []

    def job_values(job: dict[str, Any]) -> list[str]:
        params = _effective_params(job)
        values: list[str] = []
        for selection in params.get("module_selections") or []:
            if isinstance(selection, dict) and selection.get("name"):
                values.extend([str(selection["name"])] * max(1, int(selection.get("count") or 1)))
        for item in job.get("items") or []:
            if item.get("module_name"):
                values.append(str(item["module_name"]))
        return values

    return _dimension_metric_rows(jobs, events, dimension="module", event_values=event_values, job_values=job_values)


def _video_type_rows(jobs: list[dict[str, Any]], events: list[AnalyticsEvent]) -> list[dict[str, Any]]:
    def event_values(event: AnalyticsEvent) -> list[str]:
        metadata = _loads(event.metadata_json, {})
        values = []
        if metadata.get("video_type"):
            values.append(metadata["video_type"])
        values.extend(metadata.get("video_types") or [])
        return [str(value).strip() for value in values if value]

    def job_values(job: dict[str, Any]) -> list[str]:
        params = _effective_params(job)
        return [str(value).strip() for value in params.get("video_types") or [] if value]

    return _dimension_metric_rows(jobs, events, dimension="video_type", event_values=event_values, job_values=job_values)


def _profile_rows(
    users: list[User],
    active_users: set[str],
    feature_rows: list[dict[str, Any]],
    platform_rows: list[dict[str, Any]],
) -> dict[str, list[dict[str, Any]]]:
    active = [user for user in users if user.id in active_users]
    source = active or users
    active_scores = []
    for user in users:
        if user.id in active_users:
            active_scores.append("活跃用户")
        elif _as_utc(user.last_login_at):
            active_scores.append("沉睡用户")
        else:
            active_scores.append("未激活用户")
    return {
        "plans": _share_rows(Counter(user.current_plan_code for user in source), len(source)),
        "roles": _share_rows(Counter(user.role for user in source), len(source)),
        "statuses": _share_rows(Counter(user.status for user in source), len(source)),
        "genders": _share_rows(Counter(user.gender or "未填写" for user in source), len(source)),
        "activity_levels": _share_rows(Counter(active_scores), len(users)),
        "features": feature_rows[:8],
        "platforms": platform_rows[:8],
    }


def _business_timeseries(events: list[AnalyticsEvent], jobs: list[dict[str, Any]], granularity: str) -> list[dict[str, Any]]:
    buckets: dict[str, dict[str, Any]] = defaultdict(
        lambda: {"views": 0, "clicks": 0, "submits": 0, "successes": 0, "downloads": 0, "jobs": 0, "active_users": set()}
    )
    for event in events:
        key = _bucket_key(event.created_at, granularity)
        buckets[key][event.event_type + "s"] = int(buckets[key].get(event.event_type + "s", 0)) + 1
        if event.user_id:
            buckets[key]["active_users"].add(event.user_id)
    for job in jobs:
        key = _bucket_key(job["created_at"], granularity)
        buckets[key]["jobs"] += 1
        buckets[key]["submits"] += 1
        if job["status"] == "succeeded":
            buckets[key]["successes"] += 1
        if job.get("user_id"):
            buckets[key]["active_users"].add(job["user_id"])
    result = []
    for key, value in sorted(buckets.items()):
        result.append(
            {
                "bucket": key,
                "views": value.get("views", 0),
                "clicks": value.get("clicks", 0),
                "submits": value.get("submits", 0),
                "successes": value.get("successes", 0),
                "downloads": value.get("downloads", 0),
                "jobs": value.get("jobs", 0),
                "active_users": len(value["active_users"]),
                "ctr": _pct(int(value.get("clicks", 0)), int(value.get("views", 0))),
                "submit_rate": _pct(int(value.get("submits", 0)), int(value.get("clicks", 0))),
                "success_rate": _pct(int(value.get("successes", 0)), int(value.get("submits", 0))),
            }
        )
    return result


def _dimension_metric_rows(
    jobs: list[dict[str, Any]],
    events: list[AnalyticsEvent],
    *,
    dimension: str,
    event_values: Any,
    job_values: Any,
) -> list[dict[str, Any]]:
    buckets: dict[str, dict[str, Any]] = defaultdict(
        lambda: {"views": 0, "clicks": 0, "submits": 0, "successes": 0, "downloads": 0, "count": 0}
    )
    for event in events:
        values = [value for value in event_values(event) if value]
        if not values:
            continue
        for value in values:
            row = buckets[str(value)]
            row["count"] += 1
            if event.event_type == "view":
                row["views"] += 1
            elif event.event_type == "click":
                row["clicks"] += 1
            elif event.event_type == "submit":
                row["submits"] += 1
            elif event.event_type == "download":
                row["downloads"] += 1
    for job in jobs:
        values = [value for value in job_values(job) if value]
        if not values:
            continue
        for value in values:
            row = buckets[str(value)]
            row["count"] += 1
            row["submits"] += 1
            if job["status"] == "succeeded":
                row["successes"] += 1
    total = sum(row["count"] for row in buckets.values())
    rows = []
    for key, value in buckets.items():
        rows.append(
            {
                "key": key or "unknown",
                "label": key or "未知",
                "dimension": dimension,
                **value,
                "share": _pct(value["count"], total),
                "ctr": _pct(value["clicks"], value["views"]),
                "submit_rate": _pct(value["submits"], value["clicks"]),
                "success_rate": _pct(value["successes"], value["submits"]),
                "download_rate": _pct(value["downloads"], value["successes"]),
            }
        )
    rows.sort(key=lambda row: (-row["count"], row["label"]))
    return rows[:12]


def _event_relation_rows(events: list[AnalyticsEvent], jobs: list[dict[str, Any]]) -> list[dict[str, Any]]:
    views = sum(1 for event in events if event.event_type == "view")
    clicks = sum(1 for event in events if event.event_type == "click")
    submits = sum(1 for event in events if event.event_type == "submit") + len(jobs)
    successes = sum(1 for job in jobs if job["status"] == "succeeded")
    downloads = sum(1 for event in events if event.event_type == "download" or event.feature_key == "download")
    steps = [
        ("views", "曝光", views, None),
        ("clicks", "点击", clicks, views),
        ("submits", "提交", submits, clicks),
        ("successes", "成功", successes, submits),
        ("downloads", "下载", downloads, successes),
    ]
    rows = []
    for index, (key, label, count, previous) in enumerate(steps):
        rows.append(
            {
                "key": key,
                "label": label,
                "count": count,
                "step_index": index,
                "conversion_rate": 100.0 if previous is None else _pct(count, previous),
                "dropoff": 0 if previous is None else max(0, previous - count),
            }
        )
    return rows


def _subscription_rows(users: list[User], orders: list[PaymentOrder], quota_ledgers: list[QuotaLedger]) -> list[dict[str, Any]]:
    users_by_plan = Counter(user.current_plan_code for user in users)
    orders_by_plan: Counter[str] = Counter()
    paid_by_plan: Counter[str] = Counter()
    for order in orders:
        plan_code = _order_plan_code(order)
        orders_by_plan[plan_code] += 1
        if order.status == "paid":
            paid_by_plan[plan_code] += 1
    quota_by_user: Counter[str] = Counter()
    for ledger in quota_ledgers:
        if ledger.status in {"reserved", "confirmed"}:
            quota_by_user[ledger.user_id] += ledger.amount
    quota_by_plan: Counter[str] = Counter()
    for user in users:
        quota_by_plan[user.current_plan_code] += quota_by_user.get(user.id, 0)
    keys = sorted(set(users_by_plan) | set(orders_by_plan) | set(paid_by_plan) | set(quota_by_plan))
    total_users = sum(users_by_plan.values())
    return [
        {
            "key": key or "unknown",
            "label": key or "未知",
            "users": users_by_plan.get(key, 0),
            "share": _pct(users_by_plan.get(key, 0), total_users),
            "orders": orders_by_plan.get(key, 0),
            "paid_orders": paid_by_plan.get(key, 0),
            "paid_conversion_rate": _pct(paid_by_plan.get(key, 0), orders_by_plan.get(key, 0)),
            "quota_used": quota_by_plan.get(key, 0),
        }
        for key in keys
    ]


def _user_summary_rows(
    users: list[User],
    events: list[AnalyticsEvent],
    jobs: list[dict[str, Any]],
    orders: list[PaymentOrder],
    quota_ledgers: list[QuotaLedger],
) -> list[dict[str, Any]]:
    event_counts = Counter(event.user_id for event in events if event.user_id)
    download_counts = Counter(event.user_id for event in events if event.user_id and (event.event_type == "download" or event.feature_key == "download"))
    job_counts = Counter(job["user_id"] for job in jobs if job.get("user_id"))
    success_counts = Counter(job["user_id"] for job in jobs if job.get("user_id") and job["status"] == "succeeded")
    paid_counts = Counter(order.user_id for order in orders if order.status == "paid")
    quota_counts: Counter[str] = Counter()
    for ledger in quota_ledgers:
        if ledger.status in {"reserved", "confirmed"}:
            quota_counts[ledger.user_id] += max(0, int(ledger.amount or 0))
    feature_by_user: dict[str, Counter[str]] = defaultdict(Counter)
    platform_by_user: dict[str, Counter[str]] = defaultdict(Counter)
    for event in events:
        if not event.user_id:
            continue
        key = event.feature_key or event.business_type or event.event_name
        feature_by_user[event.user_id][FEATURE_LABELS.get(key, key)] += 1
        if event.platform:
            platform_by_user[event.user_id][event.platform] += 1
    for job in jobs:
        user_id = job.get("user_id")
        if not user_id:
            continue
        params = _effective_params(job)
        feature_by_user[user_id][BUSINESS_LABELS.get(job["business_type"], job["business_type"])] += 1
        if params.get("platform"):
            platform_by_user[user_id][str(params["platform"])] += 1
    rows = []
    for user in users:
        activity_score = event_counts[user.id] + job_counts[user.id] * 3 + download_counts[user.id] * 2 + paid_counts[user.id] * 5
        if activity_score <= 0:
            continue
        rows.append(
            {
                **_user_identity(user),
                "events": event_counts[user.id],
                "jobs": job_counts[user.id],
                "successes": success_counts[user.id],
                "downloads": download_counts[user.id],
                "paid_orders": paid_counts[user.id],
                "quota_used": quota_counts[user.id],
                "activity_score": activity_score,
                "top_feature": _counter_top_label(feature_by_user[user.id]),
                "top_platform": _counter_top_label(platform_by_user[user.id]),
            }
        )
    rows.sort(key=lambda row: (-row["activity_score"], row["display_name"]))
    return rows


def _user_timeline(events: list[AnalyticsEvent], jobs: list[dict[str, Any]]) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for event in events:
        rows.append(
            {
                "id": event.id,
                "kind": "event",
                "created_at": event.created_at,
                "title": FEATURE_LABELS.get(event.feature_key) or BUSINESS_LABELS.get(event.business_type) or event.event_name,
                "detail": f"{event.event_type} / {event.event_name}",
                "status": event.event_type,
            }
        )
    for job in jobs:
        rows.append(
            {
                "id": job["id"],
                "kind": "job",
                "created_at": job["created_at"],
                "title": BUSINESS_LABELS.get(job["business_type"], job["business_type"]),
                "detail": f"{job['status']} / {job.get('count', 0)} 个产出",
                "status": job["status"],
            }
        )
    rows.sort(key=lambda row: row["created_at"], reverse=True)
    return rows[:80]


def _metric_definitions(keys: list[str]) -> dict[str, dict[str, Any]]:
    return {key: {"key": key, **METRIC_DEFINITIONS[key]} for key in keys if key in METRIC_DEFINITIONS}


def _node_label(key: str) -> str:
    if key in NODE_DEFINITIONS:
        return NODE_DEFINITIONS[key]["label"]
    return f"未命名节点（{key}）"


def _node_description(key: str) -> str:
    if key in NODE_DEFINITIONS:
        return NODE_DEFINITIONS[key]["description"]
    return "系统尚未登记该节点的中文说明，请按执行日志原始 code 排查。"


def _is_timeout_log(log: ExecutionLog, provider_by_id: dict[str, Provider]) -> bool:
    error = (log.error or "").lower()
    if "timeout" in error or "timed out" in error or "超时" in error:
        return True
    if log.duration_ms is None or not log.provider_id:
        return False
    provider = provider_by_id.get(log.provider_id)
    if not provider:
        return False
    config = provider_config(provider)
    timeout_seconds = config.get("timeout_seconds")
    try:
        threshold_ms = int(timeout_seconds) * 1000
    except (TypeError, ValueError):
        return False
    return threshold_ms > 0 and int(log.duration_ms) >= threshold_ms


def _error_category(error: str) -> str:
    value = error.lower()
    if "timeout" in value or "timed out" in value or "超时" in value:
        return "超时"
    if "quota" in value or "额度" in value or "402" in value:
        return "额度"
    if "safety" in value or "安全" in value or "blocked" in value:
        return "内容安全"
    if "429" in value or "rate limit" in value or "限流" in value:
        return "限流"
    if "provider" in value or "upstream" in value or "模型" in value:
        return "模型/中转站"
    return "其他"


def _provider_series(provider_rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [
        {
            "key": row["provider_id"],
            "label": row["provider_group_label"] or row["provider_label"],
            "model_name": row.get("model_name", ""),
            "success_rate": row.get("success_rate", 0),
            "failure_rate": row.get("failure_rate", 0),
            "timeout_rate": row.get("timeout_rate", 0),
            "p95_duration_ms": row.get("p95_duration_ms", 0),
            "total": row.get("total", 0),
        }
        for row in provider_rows
    ]


def _comparison_series(rows: list[dict[str, Any]], key_field: str) -> list[dict[str, Any]]:
    return [
        {
            "key": row.get(key_field) or row.get("key"),
            "label": row.get("label") or row.get("key"),
            "total": row.get("total", 0),
            "success_rate": row.get("success_rate", 0),
            "failure_rate": row.get("failure_rate", 0),
            "timeout_rate": row.get("timeout_rate", 0),
            "avg_duration_ms": row.get("avg_duration_ms", 0),
            "p95_duration_ms": row.get("p95_duration_ms", 0),
        }
        for row in rows
    ]


def _dimension_series(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [
        {
            "key": row.get("key"),
            "label": row.get("label"),
            "views": row.get("views", 0),
            "clicks": row.get("clicks", 0),
            "submits": row.get("submits", 0),
            "successes": row.get("successes", 0),
            "downloads": row.get("downloads", 0),
            "share": row.get("share", 0),
            "success_rate": row.get("success_rate", 0),
        }
        for row in rows
    ]


def _order_plan_code(order: PaymentOrder) -> str:
    snapshot = _loads(order.snapshot_json, {})
    return str(snapshot.get("plan_code") or snapshot.get("code") or order.plan_id or "unknown")


def _user_identity(user: User) -> dict[str, Any]:
    return {
        "user_id": user.id,
        "display_name": user.display_name,
        "username": user.username,
        "uid": user.uid,
        "phone_masked": _mask_phone(user.phone),
        "role": user.role,
        "status": user.status,
        "plan": user.current_plan_code,
        "gender": user.gender or "未填写",
        "created_at": user.created_at,
        "last_login_at": user.last_login_at,
    }


def _mask_phone(phone: str) -> str:
    if len(phone) < 7:
        return phone
    return f"{phone[:3]}****{phone[-4:]}"


def _counter_top_label(counter: Counter[str]) -> str:
    if not counter:
        return "未标注"
    return counter.most_common(1)[0][0]


def _effective_params(job: dict[str, Any]) -> dict[str, Any]:
    params = job.get("params") if isinstance(job.get("params"), dict) else {}
    plan_params = params.get("plan_params")
    if isinstance(plan_params, dict):
        merged = dict(plan_params)
        merged.update(params)
        return merged
    return params


def _share_rows(counts: Counter[str], total: int, limit: int = 12) -> list[dict[str, Any]]:
    rows = [
        {"key": key or "unknown", "label": key or "未知", "count": count, "share": _pct(count, total)}
        for key, count in counts.most_common(limit)
    ]
    return rows


def _provider_tone(total: int, success_rate: float, p95: int, health: dict[str, Any]) -> str:
    if health.get("status") == "failed" or health.get("ok") is False:
        return "danger"
    if total and success_rate < 90:
        return "danger"
    if p95 >= 120_000:
        return "danger"
    if health.get("status") == "unknown":
        return "warning"
    if total and success_rate < 95:
        return "warning"
    if p95 >= 60_000:
        return "warning"
    if not total and not health:
        return "neutral"
    return "good"


def _rate_tone(rate: float, total: int) -> str:
    if not total:
        return "neutral"
    if rate < 90:
        return "danger"
    if rate < 95:
        return "warning"
    return "good"


def _latency_tone(duration_ms: int) -> str:
    if not duration_ms:
        return "neutral"
    if duration_ms >= 120_000:
        return "danger"
    if duration_ms >= 60_000:
        return "warning"
    return "good"


def _duration_label(duration_ms: int) -> str:
    if duration_ms <= 0:
        return "0 ms"
    if duration_ms >= 1000:
        return f"{duration_ms / 1000:.1f}s"
    return f"{duration_ms} ms"


def _avg(values: list[int]) -> int:
    return int(round(sum(values) / len(values))) if values else 0


def _p95(values: list[int]) -> int:
    return _percentile(values, 95)


def _percentile(values: list[int], percentile: int) -> int:
    if not values:
        return 0
    ordered = sorted(values)
    index = max(0, min(len(ordered) - 1, math.ceil(len(ordered) * percentile / 100) - 1))
    return ordered[index]


def _pct(numerator: int | float, denominator: int | float) -> float:
    if not denominator:
        return 0.0
    return round(float(numerator) * 100 / float(denominator), 1)


def _elapsed_ms(start: datetime | None, end: datetime | None) -> int | None:
    start_utc = _as_utc(start)
    end_utc = _as_utc(end)
    if not start_utc or not end_utc:
        return None
    return max(0, int((end_utc - start_utc).total_seconds() * 1000))


def _between(value: datetime | None, start_at: datetime, end_at: datetime) -> bool:
    normalized = _as_utc(value)
    return bool(normalized and start_at <= normalized <= end_at)


def _bucket_key(value: datetime, granularity: str) -> str:
    current = _as_utc(value) or utcnow()
    if granularity == "hour":
        return current.strftime("%m-%d %H:00")
    if granularity == "week":
        start = current - timedelta(days=current.weekday())
        return start.strftime("%Y-%m-%d")
    return current.strftime("%Y-%m-%d")


def _window_dict(start_at: datetime, end_at: datetime, granularity: str) -> dict[str, str]:
    return {"start_at": start_at.isoformat(), "end_at": end_at.isoformat(), "granularity": granularity}


def _loads(value: str | None, fallback: Any) -> Any:
    if not value:
        return fallback
    try:
        return json.loads(value)
    except (TypeError, json.JSONDecodeError):
        return fallback


def _as_utc(value: datetime | None) -> datetime | None:
    if value is None:
        return None
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


def _truncate(value: Any, max_length: int) -> str:
    return str(value or "").strip()[:max_length]
