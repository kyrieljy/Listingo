from __future__ import annotations

from time import perf_counter
from types import SimpleNamespace

import pytest

from backend.app.core.storage.base import StorageUnavailableError
from backend.app.models import SensitiveWord, SensitiveWordConfig
from backend.app.services.sensitive_words import (
    DEFAULT_WORD_LIMITS,
    SensitiveWordError,
    SensitiveWordMatcher,
    build_sensitive_word_snapshot,
    contains_sensitive_word,
    load_sensitive_word_snapshot,
    preview_sensitive_variants,
    sensitive_word_match,
    snapshot_meta,
)


def config(**overrides):
    values = {
        "enabled": True,
        "max_variants_per_word": DEFAULT_WORD_LIMITS[0],
        "max_total_variants": DEFAULT_WORD_LIMITS[1],
        "max_snapshot_bytes": DEFAULT_WORD_LIMITS[2],
    }
    values.update(overrides)
    return SensitiveWordConfig(**values)


def word(term: str, aliases: list[str] | None = None, enabled: bool = True) -> SensitiveWord:
    import json

    return SensitiveWord(
        term=term,
        normalized_term=term,
        aliases_json=json.dumps(aliases or [], ensure_ascii=False),
        enabled=enabled,
        note="",
    )


def payload_for(words, **overrides):
    return build_sensitive_word_snapshot(config(**overrides), words)


def test_variant_generation_and_matching_cover_confusable_forms() -> None:
    payload = payload_for([word("套图"), word("A+"), word("视频"), word("敏感信息检测")])

    assert contains_sensitive_word("套 图", payload)
    assert contains_sensitive_word("套-图", payload)
    assert contains_sensitive_word("套圖", payload)
    assert contains_sensitive_word("taotu", payload)
    assert contains_sensitive_word("tao图", payload)
    assert contains_sensitive_word("套tu", payload)
    assert contains_sensitive_word("Ａ＋", payload)
    assert contains_sensitive_word("A +", payload)
    assert contains_sensitive_word("A加", payload)
    assert contains_sensitive_word("a plus", payload)
    assert contains_sensitive_word("视 频", payload)
    assert contains_sensitive_word("視頻", payload)
    assert contains_sensitive_word("shipin", payload)
    assert contains_sensitive_word("shi-pin", payload)
    assert contains_sensitive_word("mgxxjc", payload)

    assert not contains_sensitive_word("sp", payload)
    assert not contains_sensitive_word("taoturn", payload)
    assert not contains_sensitive_word("普通商品描述", payload)


def test_variant_generation_normalizes_unicode_zero_width_and_leet() -> None:
    previews = preview_sensitive_variants("Ｓｅｃｒｅｔ", [])
    variants = previews[0].variants

    assert "secret" in variants
    payload = payload_for([word("secret")])
    assert contains_sensitive_word("s​3cr​et", payload)


def test_snapshot_records_digest_limits_and_shared_variant_sources() -> None:
    first = payload_for([word("abc", ["shared"]), word("xyz", ["shared"])])
    second = payload_for([word("abc", ["changed"]), word("xyz", ["shared"])])
    matcher = SensitiveWordMatcher(first)

    assert first["source_digest"] != second["source_digest"]
    assert first["words"][0]["boundaries"]["abc"] is True
    assert len(matcher._records["shared"]) == 2
    assert sensitive_word_match("shared", first).matched is True
    assert snapshot_meta(first)["variant_count"] == 4


@pytest.mark.parametrize(
    ("overrides", "words", "message"),
    [
        ({"max_variants_per_word": 1}, [word("abc", ["xyz"])], "单个敏感词"),
        ({"max_total_variants": 1}, [word("abc"), word("xyz")], "敏感词快照最多"),
        ({"max_snapshot_bytes": 32}, [word("a much longer word")], "字节上限"),
    ],
)
def test_snapshot_limits_fail_closed_without_truncation(overrides, words, message) -> None:
    with pytest.raises(SensitiveWordError, match=message):
        payload_for(words, **overrides)


def test_disabled_redis_meta_skips_detection_even_with_postgres_fallback(monkeypatch: pytest.MonkeyPatch) -> None:
    payload = payload_for([word("套图")])
    runtime = SimpleNamespace(
        storage=SimpleNamespace(),
        get_json_best_effort=lambda key: {"enabled": False, "source_digest": payload["source_digest"]},
    )

    assert load_sensitive_word_snapshot(object(), runtime) is None  # type: ignore[arg-type]


def test_snapshot_load_uses_postgres_fallback_and_repairs_redis(monkeypatch: pytest.MonkeyPatch) -> None:
    payload = payload_for([word("套图")])
    written: dict[str, str] = {}
    runtime = SimpleNamespace(
        storage=SimpleNamespace(set_persistent_many=written.update),
        get_json_best_effort=lambda key: None,
    )
    monkeypatch.setattr(
        "backend.app.services.sensitive_words.latest_sensitive_word_snapshot",
        lambda _session: payload,
    )

    assert load_sensitive_word_snapshot(object(), runtime) == payload  # type: ignore[arg-type]
    assert written["sensitive:words:snapshot"]


def test_double_storage_miss_fails_open(monkeypatch: pytest.MonkeyPatch) -> None:
    runtime = SimpleNamespace(storage=SimpleNamespace(), get_json_best_effort=lambda key: None)
    monkeypatch.setattr("backend.app.services.sensitive_words.latest_sensitive_word_snapshot", lambda _session: None)

    assert load_sensitive_word_snapshot(object(), runtime) is None  # type: ignore[arg-type]


def test_large_snapshot_scan_stays_under_50_ms() -> None:
    def literal(index: int) -> str:
        digits = []
        while index:
            index, remainder = divmod(index, 26)
            digits.append(chr(ord("a") + remainder))
        return "term" + "a" * (6 - len(digits)) + "".join(reversed(digits))

    payload = {
        "schema_version": "1.0",
        "enabled": True,
        "source_digest": "1" * 64,
        "words": [
            {
                "id": str(index),
                "term": literal(index),
                "variants": [literal(index)],
                "boundaries": {literal(index): True},
            }
            for index in range(100_000)
        ],
    }
    text = ("ordinary product copy " * 300) + f" {literal(99_999)} "

    matcher = SensitiveWordMatcher(payload)
    started = perf_counter()
    assert matcher.contains(text)
    assert perf_counter() - started < 0.05
