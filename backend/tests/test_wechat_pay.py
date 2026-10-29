from __future__ import annotations

import base64
import json
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import timedelta
from uuid import uuid4

import httpx
import pytest
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import padding, rsa
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from sqlalchemy import func, select

from backend.app.config import Settings
from backend.app.models import BeanGrant, BeanPack, PaymentOrder, SubscriptionPlan, User, UserSession, UserSubscription, utcnow
from backend.app.services.auth import SESSION_COOKIE, hash_token, get_current_user, require_admin
from backend.app.services.subscriptions import create_payment_order
from backend.app.services.wechat_pay import PaymentError, WechatPayClient, reconcile_order, settle_transaction


@pytest.fixture()
def gateway(tmp_path, client):
    merchant = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    platform = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    private_path, public_path = tmp_path / "merchant.pem", tmp_path / "wechat.pem"
    private_path.write_bytes(merchant.private_bytes(serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8, serialization.NoEncryption()))
    public_path.write_bytes(platform.public_key().public_bytes(serialization.Encoding.PEM, serialization.PublicFormat.SubjectPublicKeyInfo))
    settings = client.app.state.settings.model_copy(update={
        "wechat_mchid": "1900000001", "wechat_appid": "wx-test", "wechat_api_v3_key": "a" * 32,
        "wechat_merchant_serial": "merchant-serial", "wechat_private_key_path": str(private_path),
        "wechat_public_key_path": str(public_path), "wechat_public_key_id": "PUB_KEY_ID_TEST",
    })
    gateway = WechatPayClient(settings)
    gateway.platform_key = platform
    client.app.state.wechat_pay = gateway
    return gateway


@pytest.fixture()
def buyer(client):
    suffix = uuid4().hex[:10]
    with client.app.state.session_factory() as session:
        user = User(phone="138" + suffix, username=suffix, display_name="Buyer", uid=suffix)
        session.add(user)
        session.flush()
        token = uuid4().hex
        session.add(UserSession(user_id=user.id, session_token_hash=hash_token(token), refresh_token_hash=hash_token(uuid4().hex),
                                expires_at=utcnow() + timedelta(hours=1), refresh_expires_at=utcnow() + timedelta(days=1)))
        session.commit()
    client.cookies.set(SESSION_COOKIE, token)
    client.app.dependency_overrides[get_current_user] = lambda: user
    return user


def make_order(client, buyer, *, plan=False):
    with client.app.state.session_factory() as session:
        order = create_payment_order(session, session.get(User, buyer.id), **(
            {"plan_code": "monthly_basic"} if plan else {"bean_pack_code": "beans_50"}
        ))
        order.payment_channel = "wechat_native"
        session.commit()
        return order


def fact(order, **updates):
    return {"mchid": "1900000001", "appid": "wx-test", "out_trade_no": order.order_no,
            "trade_state": "SUCCESS", "transaction_id": "wx" + order.id,
            "success_time": utcnow().isoformat(), "amount": {"total": order.amount_cents, "currency": "CNY"}, **updates}


def signed(gateway, body, timestamp=None):
    timestamp = str(timestamp or int(time.time()))
    nonce = "nonce"
    message = timestamp.encode() + b"\n" + nonce.encode() + b"\n" + body + b"\n"
    return {"Wechatpay-Timestamp": timestamp, "Wechatpay-Nonce": nonce,
            "Wechatpay-Serial": gateway.settings.wechat_public_key_id,
            "Wechatpay-Signature": base64.b64encode(gateway.platform_key.sign(message, padding.PKCS1v15(), hashes.SHA256())).decode()}


def notification(gateway, transaction):
    nonce, aad = "123456789012", "transaction"
    ciphertext = AESGCM(gateway.settings.wechat_api_v3_key.encode()).encrypt(nonce.encode(), json.dumps(transaction).encode(), aad.encode())
    body = json.dumps({"event_type": "TRANSACTION.SUCCESS", "resource": {
        "algorithm": "AEAD_AES_256_GCM", "nonce": nonce, "associated_data": aad,
        "ciphertext": base64.b64encode(ciphertext).decode(),
    }}).encode()
    return body, signed(gateway, body)


def test_crypto_notification_and_replay_age(gateway):
    body, headers = notification(gateway, {"hello": "world"})
    assert gateway.notification(httpx.Headers(headers), body) == {"hello": "world"}
    with pytest.raises(PaymentError):
        gateway.verify(httpx.Headers(headers), body + b" ")
    with pytest.raises(PaymentError):
        gateway.verify(httpx.Headers(signed(gateway, body, int(time.time()) - 600)), body)
    headers["Wechatpay-Serial"] = "unknown"
    with pytest.raises(PaymentError):
        gateway.verify(httpx.Headers(headers), body)


def test_outgoing_signature_and_signed_response(gateway, monkeypatch):
    def request(_client, method, url, **kwargs):
        assert method == "POST" and url.endswith("/v3/pay/transactions/native")
        auth = kwargs["headers"]["Authorization"].split(" ", 1)[1]
        fields = dict(item.split("=", 1) for item in auth.split(","))
        fields = {k: v.strip('"') for k, v in fields.items()}
        message = (f"POST\n/v3/pay/transactions/native\n{fields['timestamp']}\n{fields['nonce_str']}\n".encode()
                   + kwargs["content"] + b"\n")
        gateway.private_key.public_key().verify(base64.b64decode(fields["signature"]), message, padding.PKCS1v15(), hashes.SHA256())
        body = b'{"code_url":"weixin://wxpay/test"}'
        return httpx.Response(200, content=body, headers=signed(gateway, body))
    monkeypatch.setattr(httpx.Client, "request", request)
    assert gateway.request("POST", "/v3/pay/transactions/native", {"description": "中文"})["code_url"]
    monkeypatch.setattr(httpx.Client, "request", lambda *a, **k: httpx.Response(200, json={"trade_state": "SUCCESS"}))
    with pytest.raises(PaymentError):
        gateway.request("GET", "/v3/pay/transactions/out-trade-no/test")


def test_native_reuses_qr_and_order_owner(client, gateway, buyer, monkeypatch):
    order = make_order(client, buyer)
    calls = []
    monkeypatch.setattr(gateway, "native", lambda order: calls.append(order.id) or "weixin://wxpay/test")
    url = f"/api/v1/subscription/orders/{order.id}/wechat-native"
    assert client.post(url).json()["code_url"] == "weixin://wxpay/test"
    assert client.post(url).status_code == 200
    assert calls == [order.id]
    assert client.get(f"/api/v1/subscription/orders/{order.id}").json()["status"] == "pending"
    other = User(id="other", phone="other", uid="other", username="other", display_name="other")
    client.app.dependency_overrides[get_current_user] = lambda: other
    assert client.post(url).status_code == 404
    assert client.get(f"/api/v1/subscription/orders/{order.id}").status_code == 404


@pytest.mark.parametrize("plan", [False, True])
def test_signed_callback_once_and_snapshot(client, gateway, buyer, plan):
    order = make_order(client, buyer, plan=plan)
    expected = json.loads(order.snapshot_json)["beans"]
    original_name = json.loads(order.snapshot_json)["name"]
    with client.app.state.session_factory() as session:
        product = session.get(SubscriptionPlan, order.plan_id) if plan else session.get(BeanPack, order.bean_pack_id)
        product.beans = expected + 1000
        product.name = "Updated after checkout"
        product.enabled = False
        session.commit()
    body, headers = notification(gateway, fact(order))
    assert client.post("/api/v1/payments/wechat/notify", content=body, headers=headers).status_code == 204
    assert client.post("/api/v1/payments/wechat/notify", content=body, headers=headers).status_code == 204
    receipt = client.get(f"/api/v1/subscription/orders/{order.id}").json()
    assert receipt["beans"] == expected
    assert receipt["plan_name" if plan else "bean_pack_name"] == original_name
    with client.app.state.session_factory() as session:
        grants = session.scalars(select(BeanGrant).where(BeanGrant.user_id == buyer.id)).all()
        assert len(grants) == 1 and grants[0].amount == expected
        assert session.get(PaymentOrder, order.id).status == "paid"
        assert session.scalar(select(func.count()).select_from(UserSubscription).where(UserSubscription.user_id == buyer.id)) == int(plan)


@pytest.mark.parametrize("updates", [{"amount": {"total": 1, "currency": "CNY"}}, {"appid": "other"}, {"mchid": "other"}, {"amount": {"total": 5000, "currency": "USD"}}])
def test_mismatched_payment_never_grants(client, gateway, buyer, updates):
    order = make_order(client, buyer)
    with client.app.state.session_factory() as session:
        settle_transaction(session, gateway, fact(order, **updates))
        session.commit()
        assert session.get(PaymentOrder, order.id).status == "manual_review"
        assert session.scalar(select(func.count()).select_from(BeanGrant).where(BeanGrant.user_id == buyer.id)) == 0


def test_forged_callback_and_production_mock_disabled(client, gateway, buyer):
    order = make_order(client, buyer)
    body, headers = notification(gateway, fact(order))
    assert client.post("/api/v1/payments/wechat/notify", content=body + b" ", headers=headers).status_code == 401
    client.app.state.settings = client.app.state.settings.model_copy(update={"testing": False})
    assert client.post(f"/api/v1/subscription/orders/{order.id}/mock-pay").status_code == 404
    assert client.get("/files/.secret_key").status_code == 404


def test_concurrent_settlement_and_rollback(client, gateway, buyer, monkeypatch):
    order = make_order(client, buyer)
    data = fact(order)
    from backend.app.services import subscriptions
    grant = subscriptions.grant_beans
    def fail(*args, **kwargs):
        raise RuntimeError("database failure")
    monkeypatch.setattr(subscriptions, "grant_beans", fail)
    with client.app.state.session_factory() as session:
        with pytest.raises(RuntimeError):
            settle_transaction(session, gateway, data)
        session.rollback()
        assert session.get(PaymentOrder, order.id).status == "pending"
    monkeypatch.setattr(subscriptions, "grant_beans", grant)
    def settle(_):
        with client.app.state.session_factory() as session:
            settle_transaction(session, gateway, data)
            session.commit()
    with ThreadPoolExecutor(max_workers=4) as pool:
        list(pool.map(settle, range(4)))
    with client.app.state.session_factory() as session:
        assert session.scalar(select(func.count()).select_from(BeanGrant).where(BeanGrant.user_id == buyer.id)) == 1


def test_reconcile_lost_callback_expiry_and_close_race(client, gateway, buyer, monkeypatch):
    order = make_order(client, buyer)
    monkeypatch.setattr(gateway, "query", lambda o: fact(o))
    with client.app.state.session_factory() as session:
        reconcile_order(session, gateway, session.get(PaymentOrder, order.id))
        session.commit()
        assert session.get(PaymentOrder, order.id).status == "paid"
    order = make_order(client, buyer)
    with client.app.state.session_factory() as session:
        current = session.get(PaymentOrder, order.id)
        current.expires_at = utcnow() - timedelta(seconds=10)
        session.commit()
    monkeypatch.setattr(gateway, "query", lambda o: {"trade_state": "NOTPAY"})
    closes = []
    monkeypatch.setattr(gateway, "close", lambda o: closes.append(o.id))
    with client.app.state.session_factory() as session:
        reconcile_order(session, gateway, session.get(PaymentOrder, order.id))
        session.commit()
        assert session.get(PaymentOrder, order.id).status == "closed"
        assert closes == [order.id]


def test_active_subscription_rejected_and_double_purchase_review(client, gateway, buyer):
    first = make_order(client, buyer, plan=True)
    with client.app.state.session_factory() as session:
        # Simulate two different plan orders created before either was paid.
        second = create_payment_order(session, session.get(User, buyer.id), plan_code="monthly_standard")
        second.payment_channel = "wechat_native"
        session.commit()
    with client.app.state.session_factory() as session:
        settle_transaction(session, gateway, fact(first))
        session.commit()
    response = client.post("/api/v1/subscription/orders", json={"plan_code": "monthly_standard"})
    assert response.status_code == 409
    with client.app.state.session_factory() as session:
        settle_transaction(session, gateway, fact(second))
        session.commit()
        assert session.get(PaymentOrder, second.id).status == "manual_review"
    make_order(client, buyer)  # Top-ups are still available.


def test_refund_record_requires_admin_and_revokes_only_order(client, gateway, buyer):
    order = make_order(client, buyer, plan=True)
    with client.app.state.session_factory() as session:
        settle_transaction(session, gateway, fact(order))
        session.commit()
    url = f"/api/v1/admin/payment-orders/{order.id}/refund-record"
    payload = {"reference": "refund123", "note": "商户平台已核对全额退款，未使用权益撤销"}
    assert client.post(url, json=payload).status_code == 403
    client.app.dependency_overrides[require_admin] = lambda: buyer
    assert client.post(url, json=payload).json()["status"] == "refunded"
    assert client.post(url, json=payload).status_code == 200
    with client.app.state.session_factory() as session:
        assert session.scalar(select(BeanGrant).where(BeanGrant.user_id == buyer.id)).remaining_beans == 0
        assert session.scalar(select(UserSubscription).where(UserSubscription.user_id == buyer.id)).status == "refunded"


def test_close_paid_race_and_late_notification(client, gateway, buyer, monkeypatch):
    order = make_order(client, buyer)
    with client.app.state.session_factory() as session:
        current = session.get(PaymentOrder, order.id)
        current.expires_at = utcnow() - timedelta(seconds=10)
        session.commit()
        expiry = current.expires_at
    paid = fact(order, success_time=(expiry - timedelta(seconds=1)).isoformat())
    queries = iter([{"trade_state": "NOTPAY"}, paid])
    monkeypatch.setattr(gateway, "query", lambda o: next(queries))
    def close(o):
        raise PaymentError("ORDERPAID", "paid")
    monkeypatch.setattr(gateway, "close", close)
    with client.app.state.session_factory() as session:
        reconcile_order(session, gateway, session.get(PaymentOrder, order.id))
        session.commit()
        assert session.get(PaymentOrder, order.id).status == "paid"
    # Closed local state must still accept a verified late notification paid before expiry.
    next_order = make_order(client, buyer)
    with client.app.state.session_factory() as session:
        current = session.get(PaymentOrder, next_order.id)
        current.status = "closed"
        current.expires_at = expiry
        session.commit()
        settle_transaction(session, gateway, fact(next_order, success_time=(expiry - timedelta(seconds=1)).isoformat()))
        session.commit()
        assert session.get(PaymentOrder, next_order.id).status == "paid"


def test_transaction_uniqueness_and_concurrent_different_plans(client, gateway, buyer):
    first = make_order(client, buyer, plan=True)
    with client.app.state.session_factory() as session:
        second = create_payment_order(session, session.get(User, buyer.id), plan_code="monthly_standard")
        second.payment_channel = "wechat_native"
        session.commit()
    def settle(order):
        with client.app.state.session_factory() as session:
            settle_transaction(session, gateway, fact(order))
            session.commit()
    with ThreadPoolExecutor(max_workers=2) as pool:
        list(pool.map(settle, [first, second]))
    with client.app.state.session_factory() as session:
        statuses = list(session.scalars(select(PaymentOrder.status).where(PaymentOrder.user_id == buyer.id)))
        assert sorted(statuses) == ["manual_review", "paid"]
        assert session.scalar(select(func.count()).select_from(UserSubscription).where(UserSubscription.user_id == buyer.id)) == 1
    pack = make_order(client, buyer)
    from sqlalchemy.exc import IntegrityError
    with client.app.state.session_factory() as session:
        with pytest.raises(IntegrityError):
            settle_transaction(session, gateway, fact(pack, transaction_id=fact(first)["transaction_id"]))
            session.commit()
        session.rollback()
        assert session.get(PaymentOrder, pack.id).status == "pending"


def test_repeated_order_expired_qr_and_gateway_disabled(client, gateway, buyer):
    first = make_order(client, buyer)
    assert make_order(client, buyer).id == first.id
    with client.app.state.session_factory() as session:
        order = session.get(PaymentOrder, first.id)
        order.expires_at = utcnow() - timedelta(seconds=1)
        session.commit()
    assert client.post(f"/api/v1/subscription/orders/{first.id}/wechat-native").status_code == 409
    second = make_order(client, buyer)
    assert second.id != first.id
    client.app.state.wechat_pay = None
    assert client.post(f"/api/v1/subscription/orders/{second.id}/wechat-native").status_code == 503


def test_production_rejects_testing_and_debug_sms(client):
    from backend.app.main import create_app
    unsafe = client.app.state.settings.model_copy(update={"production": True, "cookie_secure": True, "bootstrap_admin_phone": "13800138000"})
    with pytest.raises(RuntimeError, match="testing"):
        create_app(unsafe)
    client.app.state.settings = unsafe
    response = client.post("/api/v1/auth/sms/send", json={"phone": "13800138000", "purpose": "login"})
    assert response.status_code == 503
    assert "debug_code" not in response.json()
