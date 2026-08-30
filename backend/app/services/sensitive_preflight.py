from __future__ import annotations

import asyncio
import logging
from pathlib import Path

from sqlalchemy import or_, select
from sqlalchemy.orm import Session

from backend.app.config import Settings
from backend.app.core.runtime import RuntimeStateService
from backend.app.models import Asset
from backend.app.services.image_text_edit import detect_text_lines_with_status
from backend.app.services.sensitive_words import load_sensitive_word_snapshot, sensitive_word_match


logger = logging.getLogger(__name__)


class SensitiveInformationBlocked(Exception):
    """The unified public error for a configured sensitive-word hit."""


def asset_paths_for_sensitive_scan(
    session: Session,
    asset_ids: list[str],
    *,
    user_id: str | None = None,
) -> list[str]:
    unique_ids = list(dict.fromkeys(asset_ids))
    if not unique_ids:
        return []
    query = select(Asset).where(Asset.id.in_(unique_ids))
    if user_id:
        query = query.where(or_(Asset.user_id == user_id, Asset.user_id.is_(None)))
    assets = session.scalars(query).all()
    by_id = {asset.id: asset.file_path for asset in assets}
    paths = [by_id[asset_id] for asset_id in unique_ids if asset_id in by_id]
    return [path for path in paths if path and Path(path).exists()]


async def ensure_sensitive_information_safe(
    session: Session,
    runtime: RuntimeStateService | None,
    settings: Settings,
    texts: list[str],
    *,
    asset_ids: list[str] | None = None,
    user_id: str | None = None,
) -> None:
    payload = load_sensitive_word_snapshot(session, runtime)
    if payload is None or not payload.get("enabled"):
        return

    for text in texts:
        match = sensitive_word_match(text, payload)
        if match and match.matched:
            raise SensitiveInformationBlocked()

    paths = asset_paths_for_sensitive_scan(session, asset_ids or [], user_id=user_id)
    if not paths:
        return

    semaphore = asyncio.Semaphore(min(len(paths), 3))

    async def scan(path: str):
        async with semaphore:
            return await asyncio.to_thread(
                detect_text_lines_with_status,
                path,
                settings,
                "zh",
            )

    tasks = [asyncio.create_task(scan(path)) for path in paths]
    try:
        for pending in asyncio.as_completed(tasks):
            try:
                result = await pending
            except Exception:
                logger.warning("敏感词 OCR 预检跳过一张不可识别图片", exc_info=True)
                continue
            if result.warning:
                continue
            ocr_text = "\n".join(line.text for line in result.lines)
            match = sensitive_word_match(ocr_text, payload)
            if match and match.matched:
                raise SensitiveInformationBlocked()
    except BaseException:
        for task in tasks:
            if not task.done():
                task.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)
        raise


def prewarm_uploaded_asset_ocr(file_path: str, settings: Settings) -> None:
    """Populate the shared OCR cache after an upload response is committed."""
    if settings.testing:
        return
    try:
        detect_text_lines_with_status(file_path, settings, "zh")
    except Exception:
        logger.warning("上传图片 OCR 预热失败", exc_info=True)
