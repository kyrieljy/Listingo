from __future__ import annotations

from collections.abc import Awaitable, Callable
from typing import Any

from backend.app.services.prompt_contract import (
    MetaPromptPlan,
    inject_runtime_aspect_ratio,
    parse_meta_prompt_plan,
    validate_meta_prompt_semantics,
)


RepairCallback = Callable[[str, str], Awaitable[str | dict[str, Any]]]
ImageCallback = Callable[[str], Awaitable[bytes]]
ReplanCallback = Callable[[MetaPromptPlan, list[str]], Awaitable[MetaPromptPlan]]


async def parse_plan_with_one_repair(
    raw: str | dict[str, Any], expected_count: int, repair_callback: RepairCallback
) -> MetaPromptPlan:
    try:
        return parse_meta_prompt_plan(raw, expected_count)
    except Exception as first_error:
        repaired = await repair_callback(str(raw), str(first_error))
        try:
            return parse_meta_prompt_plan(repaired, expected_count)
        except Exception as repaired_error:
            raise ValueError(f"LLM JSON 修复后仍不合法：{repaired_error}") from repaired_error


async def run_image_route(
    provider_codes: list[str],
    generate_callback: ImageCallback,
    provider_display_names: dict[str, str] | None = None,
) -> tuple[bytes, str]:
    errors: list[str] = []
    for provider_code in provider_codes:
        try:
            return await generate_callback(provider_code), provider_code
        except Exception as exc:
            display_name = (provider_display_names or {}).get(provider_code) or provider_code
            message = str(exc)
            if display_name != provider_code:
                message = message.replace(provider_code, display_name)
            errors.append(f"{display_name}: {message}")
    raise RuntimeError("图片模型调用失败：" + "；".join(errors))


async def validate_plan_with_one_replan(
    plan: MetaPromptPlan,
    context: dict[str, Any],
    replan_callback: ReplanCallback,
) -> MetaPromptPlan:
    plan = inject_runtime_aspect_ratio(plan, context)
    errors = validate_meta_prompt_semantics(plan, context)
    if not errors:
        return plan
    replanned = await replan_callback(plan, errors)
    replanned = inject_runtime_aspect_ratio(replanned, context)
    remaining = validate_meta_prompt_semantics(replanned, context)
    if remaining:
        raise ValueError("语义重规划后仍不合格：" + "；".join(remaining))
    return replanned
