"""变更 018：dryrun 仅跳过外部调用，豆子校验/扣减与非 dryrun 一致。

覆盖要点：
- 计费入口（普通生图）：dryrun 下余额不足仍返回 402，充足则预留 BeanLedger；
- 非计费入口（文案辅助 / A+ plan）：余额不足返回 402，但成功后不产生 BeanLedger；
- admin / internal 仍豁免（不预留、不扣豆）；
- `global_dry_run=True`（测试环境默认）硬性覆盖非 admin 请求 dry_run，任务落库为 dryrun；
  admin 以请求体为准，可显式选 live 覆盖全局（021 角色优先级）。
"""

from __future__ import annotations

import types
from io import BytesIO
from uuid import uuid4

from PIL import Image
from sqlalchemy import select

from backend.app.api.public import _resolve_effective_dry_run
from backend.app.models import BeanLedger, GenerationJob, User
from backend.app.services.subscriptions import BEANS_PER_IMAGE, grant_beans


def _make_png() -> bytes:
    buffer = BytesIO()
    Image.new("RGB", (640, 640), "#f2ede4").save(buffer, format="PNG")
    return buffer.getvalue()


def _random_phone() -> str:
    """生成 11 位纯数字手机号（API 校验 `^+?\\d{5,32}$`，不能含字母）。"""
    return "137" + f"{uuid4().int % 10 ** 8:08d}"


def _login_free_user(client) -> str:
    """用短信 debug_code 登录一个全新免费用户（role=user / free 套餐），返回 user_id。"""
    phone = _random_phone()
    sent = client.post("/api/v1/auth/sms/send", json={"phone": phone, "purpose": "register"})
    assert sent.status_code == 200, sent.text
    login = client.post(
        "/api/v1/auth/sms/login",
        json={"phone": phone, "mode": "register", "code": sent.json()["debug_code"]},
    )
    assert login.status_code == 200, login.text
    with client.app.state.session_factory() as session:
        user = session.scalar(select(User).where(User.phone == phone))
        assert user is not None
        assert user.role == "user"
        return user.id


def _upload_asset(client) -> str:
    response = client.post(
        "/api/v1/assets",
        files={"file": ("product.png", _make_png(), "image/png")},
    )
    assert response.status_code == 201, response.text
    return response.json()["id"]


def _grant(client, user_id: str, amount: int) -> None:
    """发放豆子：grant_beans 第二参为 user_id 字符串。"""
    with client.app.state.session_factory() as session:
        grant_beans(
            session,
            user_id,
            amount=amount,
            expires_at=None,
            source_type="test_grant",
            source_id=None,
            source_key=f"test-{user_id}-{uuid4().hex[:8]}",
            description="018 test grant",
        )
        session.commit()


def _generation_payload(asset_id: str, *, dry_run: bool) -> dict[str, object]:
    return {
        "asset_ids": [asset_id],
        "platform": "京东",
        "market": "中国",
        "language": "中文",
        "aspect_ratio": "1:1",
        "selling_points": "通勤保温，防滑握持",
        "mode": "smart",
        "count": 7,
        "dry_run": dry_run,
    }


def test_dryrun_generation_rejects_insufficient_beans(client) -> None:
    """核心验收：豆子检测不再被 dry_run 跳过——余额不足的 dryrun 生图返回 402。"""
    _login_free_user(client)
    asset_id = _upload_asset(client)

    response = client.post("/api/v1/generation-jobs", json=_generation_payload(asset_id, dry_run=True))
    assert response.status_code == 402, response.text
    detail = response.json()["detail"]
    assert detail["code"] == "INSUFFICIENT_BEANS"
    # 7 张图 × 12 豆/张
    assert detail["required_beans"] == 7 * BEANS_PER_IMAGE


def test_dryrun_generation_reserves_beans_when_sufficient(client) -> None:
    """余额充足的 dryrun 生图：创建成功并写入 reserved 状态的 BeanLedger。"""
    user_id = _login_free_user(client)
    asset_id = _upload_asset(client)
    _grant(client, user_id, 500)

    response = client.post("/api/v1/generation-jobs", json=_generation_payload(asset_id, dry_run=True))
    assert response.status_code == 201, response.text
    job_id = response.json()["id"]

    with client.app.state.session_factory() as session:
        ledgers = session.scalars(
            select(BeanLedger).where(
                BeanLedger.ref_type == "generation_job",
                BeanLedger.ref_id == job_id,
            )
        ).all()
        assert len(ledgers) == 1
        assert ledgers[0].status == "reserved"
        assert ledgers[0].amount == 7 * BEANS_PER_IMAGE


def test_admin_is_still_exempt_from_bean_reserve(client) -> None:
    """admin / internal 仍豁免：0 豆也能创建 dryrun 任务且不产生 BeanLedger。"""
    client.cookies.clear()  # 回退到测试态 admin 用户
    asset_id = _upload_asset(client)

    response = client.post("/api/v1/generation-jobs", json=_generation_payload(asset_id, dry_run=True))
    assert response.status_code == 201, response.text
    job_id = response.json()["id"]

    with client.app.state.session_factory() as session:
        count = session.scalar(
            select(BeanLedger).where(
                BeanLedger.ref_type == "generation_job",
                BeanLedger.ref_id == job_id,
            ).limit(1)
        )
        assert count is None


def test_non_billing_copywriting_assist_checks_beans_without_charging(client) -> None:
    """非计费入口：余额不足返回 402；充足则成功，且不写 BeanLedger（不扣豆）。"""
    user_id = _login_free_user(client)
    asset_id = _upload_asset(client)
    payload = {
        "asset_ids": [asset_id],
        "platform": "京东",
        "market": "中国",
        "language": "中文",
        "selling_points": "通勤保温，防滑握持",
        "dry_run": True,
    }

    poor = client.post("/api/v1/copywriting-assist", json=payload)
    assert poor.status_code == 402, poor.text
    assert poor.json()["detail"]["code"] == "INSUFFICIENT_BEANS"

    _grant(client, user_id, 500)
    rich = client.post("/api/v1/copywriting-assist", json=payload)
    assert rich.status_code == 200, rich.text
    assert rich.json()["dry_run"] is True

    with client.app.state.session_factory() as session:
        charged = session.scalars(
            select(BeanLedger).where(BeanLedger.user_id == user_id)
        ).all()
        # 文案辅助不计费：成功执行后不应留下任何 BeanLedger
        assert not charged


def test_non_billing_aplus_plan_checks_beans(client) -> None:
    """非计费入口 A+ plan：余额不足返回 402（required = 模块数 × 12）。"""
    _login_free_user(client)
    asset_id = _upload_asset(client)

    response = client.post(
        "/api/v1/aplus-plan-jobs",
        json={
            "asset_ids": [asset_id],
            "platform": "亚马逊",
            "market": "美国",
            "language": "英文",
            "product_info": "不锈钢保温杯",
            "selected_modules": ["商品主视觉"],
            "output_targets": [{"mode": "detail", "aspect_ratio": "1:1"}],
            "dry_run": True,
        },
    )
    assert response.status_code == 402, response.text
    assert response.json()["detail"]["required_beans"] == 1 * BEANS_PER_IMAGE


def test_global_dry_run_forces_dryrun_on_request(client) -> None:
    """021 角色优先级（集成）：`global_dry_run=True` 下，非 admin 被硬性覆盖为 dryrun；
    admin 以请求体为准取 dryrun。admin 选 live 的覆盖逻辑见 test_resolve_effective_dry_run_role_priority。"""
    # 测试环境 Settings(testing=True) 未覆盖 global_dry_run，配置默认为 True
    assert client.app.state.settings.global_dry_run is True

    # 非 admin：请求 dry_run=False，仍被 global 强制为 dryrun（前台无法选择）
    free_user_id = _login_free_user(client)
    asset_id = _upload_asset(client)  # 资产归当前 free 用户所有
    _grant(client, free_user_id, 500)
    resp_non_admin = client.post("/api/v1/generation-jobs", json=_generation_payload(asset_id, dry_run=False))
    assert resp_non_admin.status_code == 201, resp_non_admin.text
    non_admin_job_id = resp_non_admin.json()["id"]
    with client.app.state.session_factory() as session:
        # global_dry_run=True 覆盖非 admin 的 live 请求 → 落库 dryrun
        assert session.get(GenerationJob, non_admin_job_id).dry_run is True

    # admin：请求 dry_run=True，按选择生效为 dryrun
    client.cookies.clear()  # 回退到测试态 admin 用户
    admin_asset_id = _upload_asset(client)
    resp_admin_dry = client.post("/api/v1/generation-jobs", json=_generation_payload(admin_asset_id, dry_run=True))
    assert resp_admin_dry.status_code == 201, resp_admin_dry.text
    admin_dry_job_id = resp_admin_dry.json()["id"]
    with client.app.state.session_factory() as session:
        assert session.get(GenerationJob, admin_dry_job_id).dry_run is True


def _fake_request(global_dry_run: bool):
    settings = types.SimpleNamespace(global_dry_run=global_dry_run)
    return types.SimpleNamespace(app=types.SimpleNamespace(state=types.SimpleNamespace(settings=settings)))


def _fake_user(role: str):
    return types.SimpleNamespace(role=role)


def test_resolve_effective_dry_run_role_priority() -> None:
    """021 角色优先级（单测）：直接验证 _resolve_effective_dry_run 的组合矩阵。

    - admin：以请求体为准，可覆盖 global_dry_run（含 global=True 调试部署下选 live）。
    - 非 admin：忽略请求体，由 global_dry_run 决定（生产 False→live；调试 True→dryrun）。
    """
    cases = [
        # (role, requested, global_dry_run, expected)
        ("admin", True, True, True),
        ("admin", False, True, False),    # admin 显式选 live 覆盖 global
        ("admin", True, False, True),
        ("admin", False, False, False),
        ("user", True, True, True),        # global 强制
        ("user", False, True, True),       # global 强制
        ("user", True, False, False),      # 非 admin 请求被忽略 → live
        ("user", False, False, False),
    ]
    for role, requested, g, expected in cases:
        request = _fake_request(g)
        result = _resolve_effective_dry_run(request, requested, _fake_user(role))
        assert result is expected, f"(role={role}, requested={requested}, global={g}) -> {result}, expected {expected}"

    # 缺省 role 视为非 admin（防御性）
    assert _resolve_effective_dry_run(_fake_request(False), True, types.SimpleNamespace()) is False
