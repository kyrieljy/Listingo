"""Website OAuth and phone-verified account association."""
import json
import logging
import re
import secrets
from urllib.parse import urlencode, urlsplit

import httpx
from fastapi import APIRouter, Depends, HTTPException, Request, Response
from fastapi.responses import RedirectResponse
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from backend.app.api.auth import _consume_login_rate_limit, _get_or_create_user_by_phone
from backend.app.config import Settings
from backend.app.core.storage.keys import wechat_login_key
from backend.app.database import get_session
from backend.app.models import User, WechatIdentity
from backend.app.schemas import AuthMeOut, SmsSendOut
from backend.app.services.auth import (
    SESSION_COOKIE, current_user_from_request, hash_token, issue_session, public_user, record_login_event,
)
from backend.app.services.notifications import unread_count
from backend.app.services.sms import normalize_phone, send_sms_code, verify_sms_code

router = APIRouter(prefix="/api/v1/auth/wechat", tags=["auth"])
CALLBACK_PATH = "/api/v1/auth/wechat/callback"
COOKIE_PATH = "/api/v1/auth/wechat"
STATE_COOKIE = "listingo_wx_state"
BIND_COOKIE = "listingo_wx_bind"
STATE_TTL = 300
BIND_TTL = 600
TOKEN_URL = "https://api.weixin.qq.com/sns/oauth2/access_token"
TOKEN_PATTERN = re.compile(r"[A-Za-z0-9_-]{43}")


class _HideWechatTokenRequests(logging.Filter):
    def filter(self, record: logging.LogRecord) -> bool:
        return TOKEN_URL not in record.getMessage()


logging.getLogger("httpx").addFilter(_HideWechatTokenRequests())


class WechatCallbackLogMiddleware:
    """Keep the callback query available to FastAPI and out of Uvicorn access logs."""

    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        if scope["type"] == "http" and scope.get("path", "").rstrip("/") == CALLBACK_PATH:
            callback_scope = dict(scope)
            scope["query_string"] = b""
            await self.app(callback_scope, receive, send)
        else:
            await self.app(scope, receive, send)


def validate_wechat_login(settings: Settings) -> None:
    if not settings.wechat_login_enabled:
        return
    callback = urlsplit(settings.wechat_login_callback_url)
    if (
        not re.fullmatch(r"wx[A-Za-z0-9]{1,62}", settings.wechat_login_app_id)
        or not settings.wechat_login_app_secret.strip()
        or callback.scheme != "https"
        or not callback.hostname
        or callback.username is not None
        or callback.password is not None
        or callback.path != CALLBACK_PATH
        or callback.query
        or callback.fragment
        or (settings.production and not settings.cookie_secure)
    ):
        raise RuntimeError("微信登录需要网站应用凭据和有效的 HTTPS 授权回调地址")


def _settings(request: Request) -> Settings:
    settings = request.app.state.settings
    if not settings.wechat_login_enabled:
        raise HTTPException(404, "微信登录未启用")
    return settings


def _cookie_token(request: Request, name: str) -> str:
    token = request.cookies.get(name, "")
    return token if TOKEN_PATTERN.fullmatch(token) else ""


def _key(kind: str, token: str) -> str:
    return wechat_login_key(kind, hash_token(token))


def _set_cookie(request: Request, response: Response, name: str, value: str, ttl: int) -> None:
    response.set_cookie(name, value, max_age=ttl, httponly=True, samesite="lax",
                        secure=request.app.state.settings.cookie_secure, path=COOKIE_PATH)


def _redirect(result: str) -> RedirectResponse:
    return RedirectResponse(f"/app?wechat={result}", status_code=303, headers={
        "Cache-Control": "no-store", "Referrer-Policy": "no-referrer",
    })


def _store(request: Request, key: str, value: str, ttl: int) -> None:
    if not request.app.state.runtime_state.storage.setex(key, value, ttl).success:
        raise HTTPException(503, "微信登录暂不可用，请稍后重试")


def _pending(request: Request, settings: Settings):
    token = _cookie_token(request, BIND_COOKIE)
    if not token:
        return None
    entry = request.app.state.runtime_state.storage.get(_key("bind", token))
    if entry is None:
        return None
    app_id, openid = json.loads(entry.value)
    return (token, entry.value, openid) if app_id == settings.wechat_login_app_id else None


def _require_guest(request: Request, session: Session) -> None:
    if request.cookies.get(SESSION_COOKIE) and current_user_from_request(session, request):
        raise HTTPException(409, "请先退出当前账号，再使用微信登录")


def _check_user(user: User) -> None:
    if user.status != "active":
        raise HTTPException(403, "账号已停用，请联系管理员")
    if user.role != "user":
        raise HTTPException(403, "此账号请使用原有登录方式")


async def exchange_openid(settings: Settings, code: str) -> str:
    try:
        async with httpx.AsyncClient(timeout=8, follow_redirects=False) as client:
            response = await client.get(TOKEN_URL, params={
                "appid": settings.wechat_login_app_id,
                "secret": settings.wechat_login_app_secret,
                "code": code,
                "grant_type": "authorization_code",
            })
            response.raise_for_status()
            data = response.json()
    except (httpx.HTTPError, ValueError):
        raise HTTPException(502, "微信授权服务暂不可用") from None
    if not isinstance(data, dict) or data.get("errcode"):
        raise HTTPException(502, "微信授权失败，请重新扫码")
    openid = data.get("openid")
    if not isinstance(openid, str) or not 1 <= len(openid) <= 128:
        raise HTTPException(502, "未收到有效的微信身份")
    return openid


@router.get("/status")
def status(request: Request, response: Response):
    settings = request.app.state.settings
    response.headers["Cache-Control"] = "no-store"
    return {
        "enabled": settings.wechat_login_enabled,
        "pending_phone": settings.wechat_login_enabled and _pending(request, settings) is not None,
    }


@router.get("/start")
def start(request: Request, session: Session = Depends(get_session)):
    settings = _settings(request)
    _require_guest(request, session)
    state, browser_token = secrets.token_urlsafe(32), secrets.token_urlsafe(32)
    query = urlencode({
        "appid": settings.wechat_login_app_id,
        "redirect_uri": settings.wechat_login_callback_url,
        "response_type": "code",
        "scope": "snsapi_login",
        "state": state,
    })
    response = RedirectResponse(f"https://open.weixin.qq.com/connect/qrconnect?{query}#wechat_redirect",
                                headers={"Cache-Control": "no-store", "Referrer-Policy": "no-referrer"})
    _consume_login_rate_limit(request, response)
    storage = request.app.state.runtime_state.storage
    pending = _cookie_token(request, BIND_COOKIE)
    if pending:
        storage.delete(_key("bind", pending))
    _store(request, _key("state", state), hash_token(browser_token), STATE_TTL)
    _set_cookie(request, response, STATE_COOKIE, browser_token, STATE_TTL)
    response.delete_cookie(BIND_COOKIE, path=COOKIE_PATH)
    return response


@router.get("/callback")
async def callback(request: Request, session: Session = Depends(get_session)):
    settings = _settings(request)
    state = request.query_params.get("state", "")
    browser_token = _cookie_token(request, STATE_COOKIE)
    storage = request.app.state.runtime_state.storage
    if not browser_token or not TOKEN_PATTERN.fullmatch(state) or not storage.delete_if_equal(
        _key("state", state), hash_token(browser_token)
    ):
        return _redirect("expired")
    code = request.query_params.get("code", "")
    result = "cancelled" if not code else "failed"
    user = None
    pending = None
    if code and len(code) <= 512:
        try:
            _require_guest(request, session)
            openid = await exchange_openid(settings, code)
            user = session.scalar(select(User).join(WechatIdentity).where(
                WechatIdentity.app_id == settings.wechat_login_app_id, WechatIdentity.openid == openid,
            ).with_for_update(of=User))
            if user is None:
                pending = secrets.token_urlsafe(32)
                _store(request, _key("bind", pending), json.dumps([settings.wechat_login_app_id, openid]), BIND_TTL)
                result = "phone"
            else:
                _check_user(user)
                result = "success"
        except HTTPException as exc:
            result = "blocked" if exc.status_code in (403, 409) else "failed"
    response = _redirect(result)
    response.delete_cookie(STATE_COOKIE, path=COOKIE_PATH)
    if pending and result == "phone":
        _set_cookie(request, response, BIND_COOKIE, pending, BIND_TTL)
    if user is not None and result == "success":
        issue_session(session, request, response, user)
        record_login_event(session, request, user=user, method="wechat", status="succeeded")
        session.commit()
    return response


class BindPhone(BaseModel):
    phone: str = Field(min_length=5, max_length=32, pattern=r"^\+?\d{5,32}$")


class ConfirmPhone(BindPhone):
    code: str = Field(min_length=4, max_length=12)


def _require_pending(request: Request, session: Session):
    settings = _settings(request)
    _require_guest(request, session)
    pending = _pending(request, settings)
    if pending is None:
        raise HTTPException(410, "微信授权已过期，请重新扫码")
    return settings, pending


@router.post("/phone/send", response_model=SmsSendOut)
async def phone_send(payload: BindPhone, request: Request, response: Response, session: Session = Depends(get_session)):
    _, (token, _, _) = _require_pending(request, session)
    _consume_login_rate_limit(request, response)
    result = await send_sms_code(session, request, phone=payload.phone, purpose="wechat_bind",
                                 challenge=token, cipher=request.app.state.cipher)
    session.commit()
    return result


@router.post("/phone/confirm", response_model=AuthMeOut)
def phone_confirm(payload: ConfirmPhone, request: Request, response: Response, session: Session = Depends(get_session)):
    settings, (token, stored, openid) = _require_pending(request, session)
    _consume_login_rate_limit(request, response)
    phone = normalize_phone(payload.phone)
    verify_sms_code(request, phone=phone, purpose="wechat_bind", code=payload.code, challenge=token)
    if not request.app.state.runtime_state.storage.delete_if_equal(_key("bind", token), stored):
        raise HTTPException(410, "微信授权已过期，请重新扫码")
    try:
        candidate = _get_or_create_user_by_phone(session, phone)
        user = session.scalar(select(User).where(User.id == candidate.id).with_for_update()
                              .execution_options(populate_existing=True))
        if user is None or user.phone != phone:
            raise HTTPException(409, "手机号已变更，请重新扫码")
        _check_user(user)
        existing = session.scalar(select(WechatIdentity).where(
            WechatIdentity.app_id == settings.wechat_login_app_id, WechatIdentity.user_id == user.id,
        ))
        if existing:
            raise HTTPException(409, "该手机号的账号已关联微信，请使用原微信扫码登录")
        session.add(WechatIdentity(app_id=settings.wechat_login_app_id, openid=openid, user_id=user.id))
        session.flush()
        issue_session(session, request, response, user)
        record_login_event(session, request, user=user, method="wechat", status="succeeded")
        session.commit()
    except IntegrityError:
        session.rollback()
        raise HTTPException(409, "微信身份或手机号已关联，请重新扫码") from None
    response.delete_cookie(BIND_COOKIE, path=COOKIE_PATH)
    return {"user": public_user(user), "unread_count": unread_count(session, user)}
