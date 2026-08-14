from backend.app.models import SmsConfig
from backend.app.services.sms import mask_phone, normalize_phone, split_phone


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
