"""Structure and batch admission checks independent of the integration database."""
from types import SimpleNamespace
from unittest.mock import Mock, patch

import pytest
from pydantic import ValidationError

from backend.app.config import Settings
from backend.app.schemas import BatchJobCreate, GenerationJobCreate
from backend.app.services.batch_jobs import _suite_params, create_batch_job_record, estimate_batch_image_count
from backend.app.services.generation_queue_service import UnifiedGenerationQueueScheduler
from backend.app.services.job_creation import TaskCreationError
from backend.app.services.jobs import build_dryrun_plan
from backend.app.services.prompt_contract import append_runtime_contract, parse_meta_prompt_plan


ONE = dict(white_background=1, scene=0, selling_point=0, other=0)
BASE = dict(asset_ids=['asset'], platform='Amazon', market='US', language='English', aspect_ratio='1:1', selling_points='Durable')


@pytest.mark.parametrize('counts', [ONE, dict(white_background=4, scene=2, selling_point=0, other=0), dict(white_background=1, scene=2, selling_point=2, other=2), dict(white_background=4, scene=4, selling_point=4, other=0)])
def test_custom_plan_preserves_count_and_types(counts):
    payload = GenerationJobCreate(**BASE, mode='custom', count=sum(counts.values()), custom_counts=counts)
    plan = build_dryrun_plan(payload.model_dump(), payload.count)
    assert len(parse_meta_prompt_plan(plan, payload.count).images) == payload.count
    assert f'必须恰好输出 {payload.count} 项' in append_runtime_contract('core', payload.count)
    if payload.count == 1:
        assert '白底' in plan.images[0].image_type


@pytest.mark.parametrize('count,counts', [(0, dict.fromkeys(ONE, 0)), (13, dict(white_background=4, scene=4, selling_point=4, other=1)), (5, {**ONE, 'white_background': 5}), (2, ONE)])
def test_invalid_custom_allocation_rejected(count, counts):
    with pytest.raises(ValidationError):
        GenerationJobCreate(**BASE, mode='custom', count=count, custom_counts=counts)


def test_smart_minimum_unchanged():
    with pytest.raises(ValidationError):
        GenerationJobCreate(**BASE, count=1)
    assert GenerationJobCreate(**BASE).count == 7


def test_atomic_override_and_mixed_billing_count():
    global_params = dict(mode='custom', count=1, custom_counts=ONE)
    items = [dict(asset_ids=['asset'], selling_points='Durable', overrides=overrides) for overrides in [{}, dict(mode='smart', count=7), dict(mode='custom', count=12, custom_counts=dict.fromkeys(ONE, 3))]]
    payload = BatchJobCreate(business_type='suite', global_params=global_params, items=items)
    assert estimate_batch_image_count(payload) == 20
    params = _suite_params(global_params, payload.items[1])
    assert params['mode'] == 'smart' and params['count'] == 7
    assert 'custom_counts' not in params
    assert _suite_params(global_params, payload.items[0])['custom_counts'] == ONE


@pytest.mark.parametrize('business_type', ['suite', 'aplus'])
def test_hundred_products_admitted_and_queued_but_101_rejected(business_type):
    settings = Settings(database_url='postgresql://unused:unused@localhost/unit', _env_file=None)
    items = [dict(asset_ids=['asset'], name=f'Item {i}', selling_points='Durable') for i in range(100)]
    global_params = {key: value for key, value in BASE.items() if key != 'asset_ids'}
    global_params.update(mode='custom', count=1, custom_counts=ONE)
    payload = BatchJobCreate(business_type=business_type, global_params=global_params, items=items)
    session = Mock()
    with patch('backend.app.services.batch_jobs.create_generation_job_record', return_value=SimpleNamespace(id='child')), patch('backend.app.services.batch_jobs.create_aplus_plan_job_record', return_value=SimpleNamespace(id='plan')):
        batch = create_batch_job_record(session, payload, settings)
    assert batch.total_count == 100
    assert session.add.call_count == 101
    scheduler = object.__new__(UnifiedGenerationQueueScheduler)
    scheduler._storage = Mock()
    scheduler.enqueue_batch_items([str(i) for i in range(100)])
    assert scheduler._storage.queue_push.call_count == 100
    with pytest.raises(TaskCreationError) as error:
        create_batch_job_record(Mock(), payload.model_copy(update={'items': [*payload.items, payload.items[0]]}), settings)
    assert error.value.status_code == 422
