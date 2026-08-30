from __future__ import annotations

import backend.app.services.aplus_jobs as aplus_jobs
import backend.app.services.jobs as jobs
import backend.app.services.video_jobs as video_jobs
from backend.app.services.prompt_contract import (
    ProductFacts,
    parse_product_facts,
    sensitive_image_categories,
)


def _base_facts() -> dict:
    return {
        "schema_version": "1.0",
        "product_name": "保温杯",
        "category": "家居",
        "sku_count": 1,
    }


def test_product_facts_defaults_missing_safety_fields_to_false() -> None:
    # 旧 Prompt 输出不包含三个安全字段，应全部视为不涉及。
    facts = parse_product_facts({**_base_facts(), "visible_features": ["不锈钢"]})
    assert isinstance(facts, ProductFacts)
    assert facts.is_pornography is False
    assert facts.is_violence is False
    assert facts.is_politics is False


def test_product_facts_accepts_zero_and_one_variants() -> None:
    for raw in (
        {**_base_facts(), "is_pornography": 0, "is_violence": "0", "is_politics": False},
        {**_base_facts(), "is_pornography": 1, "is_violence": "1", "is_politics": True},
    ):
        facts = parse_product_facts(raw)
        if facts.is_pornography:
            assert facts.is_pornography is True
            assert facts.is_violence is True
            assert facts.is_politics is True
        else:
            assert facts.is_pornography is False
            assert facts.is_violence is False
            assert facts.is_politics is False


def test_sensitive_image_categories_reports_only_positive_fields() -> None:
    facts = ProductFacts(**_base_facts(), is_pornography=True, is_violence=False, is_politics=True)
    assert sensitive_image_categories(facts) == ["pornography", "politics"]

    clean = ProductFacts(**_base_facts())
    assert sensitive_image_categories(clean) == []


def test_suite_and_aplus_wire_image_safety_but_video_does_not() -> None:
    # 套图与 A+ 接入图片安全布尔字段阻断；视频按设计不接入图片安全分类。
    assert "sensitive_image_categories" in dir(jobs)
    assert "sensitive_image_categories" in dir(aplus_jobs)
    assert "sensitive_image_categories" not in dir(video_jobs)
    assert "is_pornography" not in dir(video_jobs)
