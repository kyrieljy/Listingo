from time import sleep

from sqlalchemy import func, inspect, select
from sqlalchemy.exc import IntegrityError

from backend.app import api
from backend.app.models import LoginEvent, Notification, SmsConfig, User, UserSession
from backend.app.services.sms import _sms_identity, mask_phone, normalize_phone, sms_code_hash, split_phone


def test_mainland_phone_normalization_stays_backward_compatible() -> None:
    assert normalize_phone("13800138000") == "13800138000"
    assert normalize_phone("+86 13800138000") == "13800138000"
    assert split_phone("13800138000") == ("86", "13800138000")
    assert mask_phone("+86 13800138000") == "138****8000"


def test_hong_kong_phone_keeps_country_code() -> None:
    assert normalize_phone("+852 6123 4567") == "+85261234567"
    assert split_phone("+852 6123 4567") == ("852", "61234567")
    assert mask_phone("+852 6123 4567") == "+852 61****4567"


def test_admin_sms_send_skips_daily_limit_for_admin_phone(client) -> None:
    session_factory = client.app.state.session_factory
    with session_factory() as session:
        config = session.query(SmsConfig).first()
        config.daily_limit_per_phone = 1
        config.cooldown_seconds = 0
        session.commit()

    first = client.post("/api/v1/auth/sms/send", json={"phone": "18928268686", "purpose": "admin"})
    second = client.post("/api/v1/auth/sms/send", json={"phone": "18928268686", "purpose": "admin"})
    normal = client.post("/api/v1/auth/sms/send", json={"phone": "13800138000", "purpose": "login"})
    limited = client.post("/api/v1/auth/sms/send", json={"phone": "13800138000", "purpose": "login"})

    assert first.status_code == 200
    assert second.status_code == 200
    assert normal.status_code == 200
    assert limited.status_code == 429


def test_debug_sms_code_comes_from_settings(client) -> None:
    client.app.state.settings.debug_sms_code = "654321"

    response = client.post("/api/v1/auth/sms/send", json={"phone": "13800138000", "purpose": "login"})

    assert response.status_code == 200
    assert response.json()["debug_code"] == "654321"


def test_sms_login_auto_creates_and_reuses_user(client) -> None:
    _configure_debug_sms(client)
    phone = "13800138006"

    sent = client.post("/api/v1/auth/sms/send", json={"phone": phone, "purpose": "login"})
    first = client.post("/api/v1/auth/sms/login", json={"phone": phone, "code": sent.json()["debug_code"]})
    repeated = client.post("/api/v1/auth/sms/login", json={"phone": phone, "code": sent.json()["debug_code"]})

    assert sent.status_code == 200
    assert first.status_code == 200
    assert repeated.status_code == 422

    session_factory = client.app.state.session_factory
    with session_factory() as session:
        users = list(session.scalars(select(User).where(User.phone == phone)))
        assert len(users) == 1
        user = users[0]
        assert user.id == first.json()["user"]["id"]
        assert user.status == "active"
        assert user.current_plan_code == "free"
        assert user.username == phone
        assert session.scalar(select(func.count()).select_from(UserSession).where(UserSession.user_id == user.id)) == 1
        assert session.scalar(
            select(func.count()).select_from(Notification).where(
                Notification.user_id == user.id,
                Notification.category == "register",
            )
        ) == 1
        assert session.scalar(
            select(func.count()).select_from(LoginEvent).where(
                LoginEvent.user_id == user.id,
                LoginEvent.method == "sms",
                LoginEvent.status == "succeeded",
            )
        ) == 1

    fresh = client.post("/api/v1/auth/sms/send", json={"phone": phone, "purpose": "login"})
    second = client.post("/api/v1/auth/sms/login", json={"phone": phone, "code": fresh.json()["debug_code"]})

    assert fresh.status_code == 200
    assert second.status_code == 200
    assert second.json()["user"]["id"] == first.json()["user"]["id"]
    with session_factory() as session:
        assert session.scalar(select(func.count()).select_from(User).where(User.phone == phone)) == 1
        assert session.scalar(
            select(func.count()).select_from(UserSession).where(UserSession.user_id == first.json()["user"]["id"])
        ) == 2


def test_sms_login_rejects_disabled_existing_user(client) -> None:
    _configure_debug_sms(client)
    phone = "13800138007"

    sent = client.post("/api/v1/auth/sms/send", json={"phone": phone, "purpose": "login"})
    created = client.post("/api/v1/auth/sms/login", json={"phone": phone, "code": sent.json()["debug_code"]})
    session_factory = client.app.state.session_factory
    with session_factory() as session:
        user = session.scalar(select(User).where(User.phone == phone))
        user.status = "disabled"
        session.commit()

    fresh = client.post("/api/v1/auth/sms/send", json={"phone": phone, "purpose": "login"})
    disabled = client.post("/api/v1/auth/sms/login", json={"phone": phone, "code": fresh.json()["debug_code"]})

    assert created.status_code == 200
    assert fresh.status_code == 200
    assert disabled.status_code == 403
    assert disabled.json()["detail"] == "账号已停用，请联系管理员"


def test_concurrent_first_sms_login_reuses_unique_phone_winner(client, monkeypatch) -> None:
    integrity_phone = "13800138008"
    conflict_phone = "13800138009"
    session_factory = client.app.state.session_factory
    original_create_user = api.auth._create_user

    def create_competitor(session, *, phone):
        with session_factory() as other:
            other.add(
                User(
                    phone=phone,
                    username=phone,
                    display_name="Listingo 用户",
                    uid=phone[-8:],
                )
            )
            other.commit()
        if phone == conflict_phone:
            return original_create_user(session, phone=phone)
        raise IntegrityError("INSERT app_user", {}, Exception("duplicate phone"))

    monkeypatch.setattr(api.auth, "_create_user", create_competitor)
    for phone in (integrity_phone, conflict_phone):
        with session_factory() as session:
            user = api.auth._get_or_create_user_by_phone(session, phone)
            assert user.phone == phone
            assert user.uid == phone[-8:]


def _configure_debug_sms(client, *, cooldown_seconds: int = 0, code_ttl_seconds: int = 300) -> None:
    session_factory = client.app.state.session_factory
    with session_factory() as session:
        config = session.query(SmsConfig).first()
        config.enabled = True
        config.debug_mode = True
        config.cooldown_seconds = cooldown_seconds
        config.code_ttl_seconds = code_ttl_seconds
        config.daily_limit_per_phone = 10
        session.commit()
    client.app.state.settings.debug_sms_code = "654321"


def test_sms_code_is_hashed_consumed_once_and_reset_by_resend(client) -> None:
    _configure_debug_sms(client)
    phone = "13800138001"
    identity = _sms_identity(phone, "register")
    storage = client.app.state.rate_limiter.storage

    sent = client.post("/api/v1/auth/sms/send", json={"phone": phone, "purpose": "register"})
    code = sent.json()["debug_code"]
    stored = storage.get(f"sms:code:{identity}")

    assert sent.status_code == 200
    assert stored is not None
    assert stored.value == sms_code_hash(phone, "register", code)
    assert stored.value != code

    for _ in range(4):
        wrong = client.post("/api/v1/auth/sms/login", json={"phone": phone, "mode": "register", "code": "000000"})
        assert wrong.status_code == 422
    assert storage.get(f"sms:attempts:{identity}") is not None

    resent = client.post("/api/v1/auth/sms/send", json={"phone": phone, "purpose": "register"})
    accepted = client.post(
        "/api/v1/auth/sms/login",
        json={"phone": phone, "mode": "register", "code": resent.json()["debug_code"]},
    )
    repeated = client.post(
        "/api/v1/auth/sms/login",
        json={"phone": phone, "mode": "register", "code": resent.json()["debug_code"]},
    )

    assert accepted.status_code == 200
    assert repeated.status_code == 422
    assert storage.get(f"sms:code:{identity}") is None
    assert storage.get(f"sms:attempts:{identity}") is None


def test_sms_code_rejects_after_five_wrong_attempts(client) -> None:
    _configure_debug_sms(client)
    phone = "13800138002"
    sent = client.post("/api/v1/auth/sms/send", json={"phone": phone, "purpose": "register"})
    assert sent.status_code == 200

    statuses = [
        client.post("/api/v1/auth/sms/login", json={"phone": phone, "mode": "register", "code": "000000"}).status_code
        for _ in range(5)
    ]
    blocked = client.post(
        "/api/v1/auth/sms/login",
        json={"phone": phone, "mode": "register", "code": sent.json()["debug_code"]},
    )

    assert statuses == [422, 422, 422, 422, 422]
    assert blocked.status_code == 429


def test_sms_cooldown_is_enforced_between_sends(client) -> None:
    _configure_debug_sms(client, cooldown_seconds=60)
    payload = {"phone": "13800138004", "purpose": "register"}

    first = client.post("/api/v1/auth/sms/send", json=payload)
    second = client.post("/api/v1/auth/sms/send", json=payload)

    assert (first.status_code, second.status_code) == (200, 429)


def test_sms_code_expires_after_configured_ttl(client) -> None:
    _configure_debug_sms(client, code_ttl_seconds=1)
    phone = "13800138005"
    sent = client.post("/api/v1/auth/sms/send", json={"phone": phone, "purpose": "register"})

    sleep(1.1)
    expired = client.post(
        "/api/v1/auth/sms/login",
        json={"phone": phone, "mode": "register", "code": sent.json()["debug_code"]},
    )

    assert sent.status_code == 200
    assert expired.status_code == 422


def test_sms_table_is_removed_from_runtime_database(client) -> None:
    assert not inspect(client.app.state.engine).has_table("sms_verification_code")


def test_failed_sms_send_releases_cooldown_reservation(client) -> None:
    session_factory = client.app.state.session_factory
    with session_factory() as session:
        config = session.query(SmsConfig).first()
        config.enabled = True
        config.debug_mode = False
        config.cooldown_seconds = 60
        config.daily_limit_per_phone = 10
        config.login_template_code = ""
        session.commit()

    phone = "13800138003"
    identity = _sms_identity(phone, "login")
    response = client.post("/api/v1/auth/sms/send", json={"phone": phone, "purpose": "login"})

    assert response.status_code == 503
    assert client.app.state.rate_limiter.storage.get(f"sms:cooldown:{identity}") is None
    assert client.app.state.rate_limiter.storage.reserve_sliding_window(
        f"sms:daily:{identity}", "probe-token", 10, 86_400
    )
