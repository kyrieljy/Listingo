from __future__ import annotations

import hashlib
import json
import logging
import re
import threading
import unicodedata
from dataclasses import dataclass
from datetime import datetime
from time import perf_counter
from typing import Any, Iterable

import ahocorasick
from pypinyin import Style, lazy_pinyin
from sqlalchemy import select
from sqlalchemy.orm import Session

from backend.app.core.runtime import RuntimeStateService
from backend.app.core.storage.base import StorageUnavailableError
from backend.app.core.storage.keys import sensitive_word_meta_key, sensitive_word_snapshot_key
from backend.app.models import SensitiveWord, SensitiveWordConfig, SensitiveWordSnapshot, utcnow


logger = logging.getLogger(__name__)
SCHEMA_VERSION = "1.0"
DEFAULT_WORD_LIMITS = (256, 100_000, 10_485_760)
_CJK_RE = re.compile(r"[\u3400-\u9fff]")
_SEPARATOR_RE = re.compile(r"[\s\-_.*/|、·•·]+")
_ZERO_WIDTH_RE = re.compile(r"[\u200b-\u200f\u202a-\u202e\u2060\ufeff]")
_OPENCC_T2S = None
_OPENCC_LOCK = threading.Lock()
_MATCHER_LOCK = threading.Lock()
_MATCHER_CACHE: dict[str, "SensitiveWordMatcher"] = {}
_MATCHER_CACHE_MAX = 4


class SensitiveWordError(ValueError):
    """Raised for invalid administrator input or an over-limit snapshot."""


def _t2s_converter():
    global _OPENCC_T2S
    with _OPENCC_LOCK:
        if _OPENCC_T2S is None:
            from opencc import OpenCC

            _OPENCC_T2S = OpenCC("t2s")
        return _OPENCC_T2S


def normalize_sensitive_text(value: str, *, compact: bool = False) -> str:
    text = unicodedata.normalize("NFKC", value or "").casefold()
    text = "".join(
        char
        for char in text
        if not (unicodedata.category(char) in {"Cc", "Cf"} and char not in "\n\r\t")
    )
    text = _ZERO_WIDTH_RE.sub("", text)
    text = "".join(
        char
        for char in unicodedata.normalize("NFKD", text)
        if unicodedata.category(char) != "Mn"
    )
    replacements = {
        "4": "a",
        "0": "o",
        "3": "e",
        "1": "i",
        "!": "i",
        "$": "s",
        "5": "s",
        "7": "t",
        "＋": "+",
        "加": "+",
        "plus": "+",
    }
    for source, target in replacements.items():
        text = text.replace(source, target)
    text = _t2s_converter().convert(text)
    if compact:
        text = _SEPARATOR_RE.sub("", text)
    return text.strip()


def _pinyin_text(value: str) -> str:
    normalized = normalize_sensitive_text(value)
    return "".join(lazy_pinyin(normalized, style=Style.NORMAL, errors="default"))


def _uses_word_boundary(variant: str) -> bool:
    # Pinyin/Latin literals must not match inside unrelated Latin words;
    # symbols such as `+` and CJK variants intentionally use the loose mode.
    return bool(variant) and all(char.isascii() and char.isalnum() for char in variant)


def _candidate_variants(source: str) -> list[str]:
    compact = normalize_sensitive_text(source, compact=True)
    if not compact:
        return []
    variants = [compact, _pinyin_text(source)]
    cjk_count = len(_CJK_RE.findall(normalize_sensitive_text(source)))
    if cjk_count >= 4:
        initials = "".join(lazy_pinyin(normalize_sensitive_text(source), style=Style.FIRST_LETTER, errors="default"))
        variants.append(initials)
    # `+` and its audible spelling must both be searchable in compact text.
    if "+" in compact:
        variants.append(compact.replace("+", "plus"))
    return list(dict.fromkeys(variants))


@dataclass(frozen=True)
class SensitiveVariantPreview:
    source: str
    variants: tuple[str, ...]
    boundary: str


def preview_sensitive_variants(
    term: str,
    aliases: Iterable[str],
    *,
    max_variants_per_word: int = DEFAULT_WORD_LIMITS[0],
) -> list[SensitiveVariantPreview]:
    result: list[SensitiveVariantPreview] = []
    seen_sources: set[str] = set()
    for source in (term, *aliases):
        normalized_source = normalize_sensitive_text(source)
        if not normalized_source or normalized_source in seen_sources:
            continue
        seen_sources.add(normalized_source)
        variants: list[str] = []
        for variant in _candidate_variants(source):
            if variant and variant not in variants:
                variants.append(variant)
        if not variants:
            continue
        result.append(
            SensitiveVariantPreview(
                source=source,
                variants=tuple(variants),
                boundary="word" if all(_uses_word_boundary(variant) for variant in variants) else "none",
            )
        )
    variant_count = sum(len(item.variants) for item in result)
    if variant_count > max_variants_per_word:
        raise SensitiveWordError(f"单个敏感词最多生成 {max_variants_per_word} 个变体，当前 {variant_count} 个")
    return result


def _word_payload(word: SensitiveWord, max_variants_per_word: int) -> dict[str, Any]:
    aliases = json.loads(word.aliases_json or "[]")
    previews = preview_sensitive_variants(word.term, aliases, max_variants_per_word=max_variants_per_word)
    variants: list[str] = []
    for preview in previews:
        for variant in preview.variants:
            if variant not in variants:
                variants.append(variant)
    boundaries = [item.boundary for item in previews]
    return {
        "id": word.id,
        "term": word.term,
        "aliases": aliases,
        "boundary": "word" if boundaries and set(boundaries) == {"word"} else "none",
        "boundaries": {variant: _uses_word_boundary(variant) for variant in variants},
        "variants": variants,
    }


def _canonical_source(
    config: SensitiveWordConfig,
    words: list[SensitiveWord],
) -> dict[str, Any]:
    enabled_words = [word for word in words if word.enabled]
    return {
        "schema_version": SCHEMA_VERSION,
        "enabled": bool(config.enabled),
        "limits": {
            "per_word": config.max_variants_per_word,
            "total": config.max_total_variants,
            "bytes": config.max_snapshot_bytes,
        },
        "words": [
            {
                "id": word.id,
                "term": word.term,
                "normalized_term": word.normalized_term,
                "aliases": json.loads(word.aliases_json or "[]"),
            }
            for word in sorted(enabled_words, key=lambda item: (item.normalized_term, item.id))
        ],
    }


def _digest(value: Any) -> str:
    return hashlib.sha256(json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")).hexdigest()


def build_sensitive_word_snapshot(
    config: SensitiveWordConfig,
    words: list[SensitiveWord],
) -> dict[str, Any]:
    source = _canonical_source(config, words)
    digest = _digest(source)
    payload_words: list[dict[str, Any]] = []
    variant_count = 0
    for word in sorted((item for item in words if item.enabled), key=lambda item: (item.normalized_term, item.id)):
        word_payload = _word_payload(word, config.max_variants_per_word)
        variant_count += len(word_payload["variants"])
        if variant_count > config.max_total_variants:
            raise SensitiveWordError(f"敏感词快照最多 {config.max_total_variants} 个变体，当前 {variant_count} 个")
        payload_words.append(word_payload)
    payload = {
        **source,
        "words": payload_words,
        "source_digest": digest,
        "generated_at": utcnow().isoformat(),
    }
    payload_bytes = len(json.dumps(payload, ensure_ascii=False, separators=(",", ":")).encode("utf-8"))
    if payload_bytes > config.max_snapshot_bytes:
        raise SensitiveWordError(f"敏感词快照超过 {config.max_snapshot_bytes} 字节上限，当前 {payload_bytes} 字节")
    return payload


def snapshot_meta(payload: dict[str, Any]) -> dict[str, Any]:
    return {
        "schema_version": payload["schema_version"],
        "enabled": payload["enabled"],
        "source_digest": payload["source_digest"],
        "word_count": len(payload["words"]),
        "variant_count": sum(len(word["variants"]) for word in payload["words"]),
        "payload_bytes": len(json.dumps(payload, ensure_ascii=False, separators=(",", ":")).encode("utf-8")),
    }


def snapshot_payload_json(payload: dict[str, Any]) -> str:
    return json.dumps(payload, ensure_ascii=False, separators=(",", ":"))


def sync_sensitive_word_snapshot(payload: dict[str, Any], runtime: RuntimeStateService | None) -> None:
    if runtime is None:
        raise SensitiveWordError("运行时存储不可用，无法同步敏感词快照")
    payload_json = snapshot_payload_json(payload)
    runtime.storage.set_persistent_many(
        {
            sensitive_word_meta_key(): json.dumps(snapshot_meta(payload), ensure_ascii=False, separators=(",", ":")),
            sensitive_word_snapshot_key(): payload_json,
        }
    )


def persist_sensitive_word_snapshot(session: Session, payload: dict[str, Any]) -> SensitiveWordSnapshot:
    payload_json = snapshot_payload_json(payload)
    meta = snapshot_meta(payload)
    snapshot = session.scalar(
        select(SensitiveWordSnapshot).where(SensitiveWordSnapshot.source_digest == payload["source_digest"])
    )
    if snapshot is None:
        snapshot = SensitiveWordSnapshot(source_digest=payload["source_digest"])
        session.add(snapshot)
    else:
        snapshot.created_at = utcnow()
    snapshot.payload_json = payload_json
    snapshot.word_count = meta["word_count"]
    snapshot.variant_count = meta["variant_count"]
    snapshot.payload_bytes = meta["payload_bytes"]
    session.flush()
    snapshots = session.scalars(
        select(SensitiveWordSnapshot).order_by(SensitiveWordSnapshot.created_at.desc(), SensitiveWordSnapshot.id.desc())
    ).all()
    for old_snapshot in snapshots[20:]:
        session.delete(old_snapshot)
    session.flush()
    return snapshot


def latest_sensitive_word_snapshot(session: Session) -> dict[str, Any] | None:
    snapshot = session.scalar(
        select(SensitiveWordSnapshot).order_by(SensitiveWordSnapshot.created_at.desc(), SensitiveWordSnapshot.id.desc()).limit(1)
    )
    if not snapshot:
        return None
    try:
        payload = json.loads(snapshot.payload_json)
    except (TypeError, ValueError):
        return None
    return payload if _valid_snapshot(payload) else None


def _valid_snapshot(payload: Any) -> bool:
    return (
        isinstance(payload, dict)
        and payload.get("schema_version") == SCHEMA_VERSION
        and isinstance(payload.get("enabled"), bool)
        and isinstance(payload.get("source_digest"), str)
        and len(payload["source_digest"]) == 64
        and isinstance(payload.get("words"), list)
    )


def load_sensitive_word_snapshot(
    session: Session,
    runtime: RuntimeStateService | None,
) -> dict[str, Any] | None:
    if runtime is not None:
        try:
            meta = runtime.get_json_best_effort(sensitive_word_meta_key())
            if isinstance(meta, dict) and meta.get("enabled") is False:
                return None
            if isinstance(meta, dict) and isinstance(meta.get("source_digest"), str):
                payload = runtime.get_json_best_effort(sensitive_word_snapshot_key())
                if _valid_snapshot(payload) and payload.get("source_digest") == meta.get("source_digest"):
                    return payload
        except Exception:
            logger.warning("敏感词 Redis 快照读取失败", exc_info=True)
    payload = latest_sensitive_word_snapshot(session)
    if payload is not None and runtime is not None:
        try:
            sync_sensitive_word_snapshot(payload, runtime)
        except (StorageUnavailableError, SensitiveWordError):
            logger.warning("敏感词 PostgreSQL 快照回写 Redis 失败", exc_info=True)
    return payload


def ensure_sensitive_word_snapshot(
    session: Session,
    runtime: RuntimeStateService | None,
) -> dict[str, Any]:
    config = get_sensitive_word_config(session)
    words = list(session.scalars(select(SensitiveWord).order_by(SensitiveWord.normalized_term)).all())
    payload = build_sensitive_word_snapshot(config, words)
    persist_sensitive_word_snapshot(session, payload)
    sync_sensitive_word_snapshot(payload, runtime)
    session.commit()
    return payload


def get_sensitive_word_config(session: Session) -> SensitiveWordConfig:
    config = session.scalar(select(SensitiveWordConfig).limit(1))
    if config is None:
        config = SensitiveWordConfig(
            enabled=False,
            max_variants_per_word=DEFAULT_WORD_LIMITS[0],
            max_total_variants=DEFAULT_WORD_LIMITS[1],
            max_snapshot_bytes=DEFAULT_WORD_LIMITS[2],
        )
        session.add(config)
        session.flush()
    return config


@dataclass(frozen=True)
class SensitiveWordMatch:
    matched: bool
    source_digest: str
    elapsed_ms: int


class SensitiveWordMatcher:
    def __init__(self, payload: dict[str, Any]) -> None:
        self.payload = payload
        self.source_digest = payload["source_digest"]
        self._automaton = ahocorasick.Automaton()
        self._records: dict[str, list[dict[str, str]]] = {}
        for word in payload["words"]:
            record = {"id": word["id"], "term": word["term"]}
            for variant in word["variants"]:
                records = self._records.setdefault(variant, [])
                if record not in records:
                    records.append(record)
                boundaries = word.get("boundaries")
                use_boundary = boundaries[variant] if isinstance(boundaries, dict) and variant in boundaries else _uses_word_boundary(variant)
                self._automaton.add_word(variant, (variant, use_boundary))
        self._automaton.make_automaton()

    @staticmethod
    def _valid_boundary(text: str, start: int, end: int, use_boundary: bool) -> bool:
        if not use_boundary:
            return True
        left_ok = start == 0 or not text[start - 1].isalnum()
        right_ok = end + 1 >= len(text) or not text[end + 1].isalnum()
        return left_ok and right_ok

    def contains(self, text: str) -> bool:
        if not self.payload["enabled"] or not text:
            return False
        views = [
            normalize_sensitive_text(text),
            normalize_sensitive_text(text, compact=True),
            _pinyin_text(text),
        ]
        for view in views:
            if not view:
                continue
            for end_index, (variant, use_boundary) in self._automaton.iter(view):
                start = end_index - len(variant) + 1
                if self._valid_boundary(view, start, end_index, use_boundary):
                    return True
        return False


def _matcher(payload: dict[str, Any]) -> SensitiveWordMatcher:
    digest = payload["source_digest"]
    with _MATCHER_LOCK:
        matcher = _MATCHER_CACHE.get(digest)
        if matcher is None:
            matcher = SensitiveWordMatcher(payload)
            _MATCHER_CACHE[digest] = matcher
            while len(_MATCHER_CACHE) > _MATCHER_CACHE_MAX:
                _MATCHER_CACHE.pop(next(iter(_MATCHER_CACHE)))
        return matcher


def contains_sensitive_word(text: str, payload: dict[str, Any]) -> bool:
    return _matcher(payload).contains(text)


def sensitive_word_match(text: str, payload: dict[str, Any] | None) -> SensitiveWordMatch | None:
    if payload is None or not payload.get("enabled"):
        return None
    started = perf_counter()
    matched = contains_sensitive_word(text, payload)
    elapsed_ms = int((perf_counter() - started) * 1000)
    return SensitiveWordMatch(matched=matched, source_digest=payload["source_digest"], elapsed_ms=elapsed_ms)


def sensitive_word_status(session: Session, runtime: RuntimeStateService | None) -> dict[str, Any]:
    redis_meta = runtime.get_json_best_effort(sensitive_word_meta_key()) if runtime is not None else None
    snapshot = latest_sensitive_word_snapshot(session)
    return {
        "redis": redis_meta if isinstance(redis_meta, dict) else None,
        "postgres": snapshot_meta(snapshot) if snapshot else None,
        "in_sync": bool(
            isinstance(redis_meta, dict)
            and snapshot
            and redis_meta.get("source_digest") == snapshot.get("source_digest")
        ),
    }
