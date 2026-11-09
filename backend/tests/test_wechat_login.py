from concurrent.futures import ThreadPoolExecutor
from contextlib import closing
from urllib.parse import parse_qs, urlsplit

import httpx
import pytest
from fastapi import HTTPException
from fastapi.testclient import TestClient
from sqlalchemy import func, select

from backend.app.api import wechat_login
from backend.app.models import User, WechatIdentity
from backend.app.services.auth import SESSION_COOKIE

BASE = "/api/v1/auth/wechat"
PHONE = "+8613800138000"


@pytest.fixture
def oauth(client, monkeypatch):
    settings = client.app.state.settings
    settings.wechat_login_enabled = True
    settings.wechat_login_app_id = "wxWebsiteTest"
    settings.wechat_login_app_secret = "fake-app-secret"
    settings.testing = False  # Exercise anonymous sessions without test auth fallback.

    async def exchange(settings, code):
        if code == "bad":
            raise HTTPException(502, "provider failure")
        return code

    monkeypatch.setattr(wechat_login, "exchange_openid", exchange)
    try:
        yield client
    finally:
        settings.testing = True


def start(browser):
    response = browser.get(f"{BASE}/start", follow_redirects=False)
    assert response.status_code == 307
    target = urlsplit(response.headers["location"])
    assert target.netloc == "open.weixin.qq.com"
    query = parse_qs(target.query)
    assert query["scope"] == ["snsapi_login"]
    assert query["redirect_uri"] == ["https://listingo.net/api/v1/auth/wechat/callback"]
    return query["state"][0]


def finish(browser, state, code=None):
    params = {"state": state}
    if code is not None:
        params["code"] = code
    return browser.get(f"{BASE}/callback", params=params, follow_redirects=False)


def send(browser, phone=PHONE):
    response = browser.post(f"{BASE}/phone/send", json={"phone": phone})
    assert response.status_code == 200, response.text
    return response.json()["debug_code"]


def confirm(browser, code, phone=PHONE):
    return browser.post(f"{BASE}/phone/confirm", json={"phone": phone, "code": code})


def test_disabled_by_default(client):
    assert client.get(f"{BASE}/status").json() == {"enabled": False, "pending_phone": False}
    assert client.get(f"{BASE}/start").status_code == 404


def test_exchange_uses_server_credentials_without_logging_them(client, monkeypatch, caplog):
    import asyncio
    import logging

    settings = client.app.state.settings
    settings.wechat_login_app_id = "wxWebsiteTest"
    settings.wechat_login_app_secret = "secret-fixture-only"
    auth_code = "authorization-fixture-only"
    async_client = httpx.AsyncClient

    def respond(request):
        assert str(request.url.copy_with(query=None)) == wechat_login.TOKEN_URL
        assert dict(request.url.params) == {
            "appid": settings.wechat_login_app_id, "secret": settings.wechat_login_app_secret,
            "code": auth_code, "grant_type": "authorization_code",
        }
        return httpx.Response(200, json={"openid": "validated-openid", "access_token": "discard-this"})

    def build_client(**kwargs):
        return async_client(transport=httpx.MockTransport(respond), **kwargs)

    monkeypatch.setattr(wechat_login.httpx, "AsyncClient", build_client)
    with caplog.at_level(logging.INFO, logger="httpx"):
        assert asyncio.run(wechat_login.exchange_openid(settings, auth_code)) == "validated-openid"
    assert settings.wechat_login_app_secret not in caplog.text
    assert auth_code not in caplog.text


def test_expired_state_and_binding_are_rejected(oauth):
    state = start(oauth)
    storage = oauth.app.state.runtime_state.storage
    storage.delete(wechat_login._key("state", state))
    assert finish(oauth, state, "openid").headers["location"] == "/app?wechat=expired"
    finish(oauth, start(oauth), "openid")
    storage.delete(wechat_login._key("bind", oauth.cookies[wechat_login.BIND_COOKIE]))
    assert oauth.post(f"{BASE}/phone/send", json={"phone": PHONE}).status_code == 410


def test_new_user_then_repeat_scan(oauth):
    assert finish(oauth, start(oauth), "openid-new").headers["location"] == "/app?wechat=phone"
    assert SESSION_COOKIE not in oauth.cookies
    assert oauth.get(f"{BASE}/status").json()["pending_phone"]
    code = send(oauth)
    assert confirm(oauth, "wrong-code").status_code == 422
    logged_in = confirm(oauth, code)
    assert logged_in.status_code == 200, logged_in.text
    user_id = logged_in.json()["user"]["id"]
    assert SESSION_COOKIE in oauth.cookies
    assert not oauth.get(f"{BASE}/status").json()["pending_phone"]
    assert confirm(oauth, code).status_code == 409
    oauth.post("/api/v1/auth/logout")
    assert finish(oauth, start(oauth), "openid-new").headers["location"] == "/app?wechat=success"
    assert oauth.get("/api/v1/auth/me").json()["user"]["id"] == user_id


def test_existing_account_retains_identity_and_plan(oauth):
    from backend.app.api.auth import _create_user
    with oauth.app.state.session_factory() as session:
        user = _create_user(session, phone=PHONE, username="existing_user")
        user.current_plan_code = "existing_plan"
        user_id = user.id
        session.commit()
    finish(oauth, start(oauth), "openid-existing")
    response = confirm(oauth, send(oauth))
    assert response.status_code == 200, response.text
    assert response.json()["user"]["id"] == user_id
    with oauth.app.state.session_factory() as session:
        assert session.get(User, user_id).current_plan_code == "existing_plan"
        assert session.scalar(select(func.count()).select_from(WechatIdentity)) == 1


@pytest.mark.parametrize(("code", "result"), [(None, "cancelled"), ("bad", "failed"), ("valid", "phone")])
def test_callback_only_accepts_its_browser_and_consumes_state(oauth, code, result):
    state = start(oauth)
    with closing(TestClient(oauth.app)) as other:
        assert finish(other, state, code).headers["location"] == "/app?wechat=expired"
    assert finish(oauth, state, code).headers["location"] == f"/app?wechat={result}"
    assert finish(oauth, state, code).headers["location"] == "/app?wechat=expired"
    assert SESSION_COOKIE not in oauth.cookies


def test_sms_code_bound_to_wechat_challenge(oauth):
    finish(oauth, start(oauth), "first")
    code = send(oauth)
    with closing(TestClient(oauth.app)) as other:
        finish(other, start(other), "second")
        assert confirm(other, code).status_code == 422
    assert confirm(oauth, code).status_code == 200


@pytest.mark.parametrize(("role", "status", "linked", "expected"), [
    ("admin", "active", False, 403),
    ("user", "disabled", False, 403),
    ("user", "active", True, 409),
])
def test_phone_conflicts_do_not_issue_session(oauth, role, status, linked, expected):
    from backend.app.api.auth import _create_user
    with oauth.app.state.session_factory() as session:
        user = _create_user(session, phone=PHONE)
        user.role, user.status = role, status
        if linked:
            session.add(WechatIdentity(app_id="wxWebsiteTest", openid="already-linked", user_id=user.id))
        session.commit()
    finish(oauth, start(oauth), "new-openid")
    assert confirm(oauth, send(oauth)).status_code == expected
    assert SESSION_COOKIE not in oauth.cookies


def test_concurrent_same_openid_creates_one_account(oauth):
    phones = [PHONE, "+8613800138001"]
    with closing(TestClient(oauth.app)) as other:
        browsers = [oauth, other]
        for browser in browsers:
            finish(browser, start(browser), "same-openid")
        codes = [send(browser, phone) for browser, phone in zip(browsers, phones)]
        with ThreadPoolExecutor(2) as pool:
            futures = [pool.submit(confirm, browser, code, phone)
                       for browser, code, phone in zip(browsers, codes, phones)]
            assert sorted(f.result().status_code for f in futures) == [200, 409]
    with oauth.app.state.session_factory() as session:
        assert session.scalar(select(func.count()).select_from(WechatIdentity)) == 1
        assert session.scalar(select(func.count()).select_from(User).where(User.role == "user")) == 1
