from __future__ import annotations

import json
from datetime import timedelta
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Request, Response
from sqlalchemy import select
from sqlalchemy.orm import Session

from backend.app.database import get_session
from backend.app.core.rate_limit import (
    NONCE_TTL_SECONDS,
    NonceStatus,
    RateLimitResult,
    client_ip,
    rate_limit_headers,
)
from backend.app.core.storage.keys import session_cache_key
from backend.app.models import LoginEvent, Notification, User, UserSession, utcnow
from backend.app.schemas import (
    AuthMeOut,
    ChangePhoneConfirmCreate,
    ChangePhoneStartCreate,
    FirstPasswordCreate,
    NotificationOut,
    PasswordChangeCreate,
    PasswordLoginCreate,
    PaymentOrderCreate,
    PaymentOrderOut,
    ProfileUpdate,
    QuotaSummaryOut,
    RegisterCreate,
    SmsLoginCreate,
    SmsSendCreate,
    SmsSendOut,
    SubscriptionPlanOut,
)
from backend.app.services.auth import (
    SESSION_COOKIE,
    clear_session_cookies,
    find_user_by_identifier,
    get_current_user,
    get_optional_user,
    hash_password,
    hash_token,
    issue_session,
    public_user,
    record_login_event,
    verify_password,
)
from backend.app.services.notifications import (
    create_notification,
    list_user_notifications,
    mark_notification_read,
    serialize_notification,
    unread_count,
)
from backend.app.services.sms import normalize_phone, send_sms_code, verify_sms_code
from backend.app.services.subscriptions import (
    create_payment_order,
    current_quota_summary,
    list_subscription_plans,
    mock_pay_order,
    plan_by_code,
    serialize_order,
)


router = APIRouter(prefix="/api/v1", tags=["auth"])

LOGIN_RATE_LIMIT = 20
LOGIN_RATE_WINDOW_SECONDS = 60
REQUEST_NONCE_HEADER = "X-Request-Nonce"


def _consume_login_rate_limit(request: Request, response: Response) -> RateLimitResult:
    result = request.app.state.rate_limiter.consume_rate_limit(
        f"login:{client_ip(request)}",
        LOGIN_RATE_LIMIT,
        LOGIN_RATE_WINDOW_SECONDS,
    )
    for name, value in rate_limit_headers(result).items():
        response.headers[name] = value
    if not result.allowed:
        raise HTTPException(
            status_code=429,
            detail="登录尝试过于频繁，请稍后再试",
            headers=rate_limit_headers(result),
        )
    return result


def _require_fresh_nonce(request: Request) -> None:
    result = request.app.state.rate_limiter.consume_nonce(request.headers.get(REQUEST_NONCE_HEADER, ""))
    if result.status is NonceStatus.ACCEPTED:
        return
    if result.status is NonceStatus.DUPLICATE:
        raise HTTPException(
            status_code=409,
            detail="请求已提交，请勿重复操作",
            headers={"Retry-After": str(result.expires_in_seconds or NONCE_TTL_SECONDS)},
        )
    if result.status is NonceStatus.CAPACITY_EXCEEDED:
        raise HTTPException(status_code=429, detail="请求防重放容量已满，请稍后再试")
    raise HTTPException(status_code=400, detail="请求缺少有效的一次性随机数")


def _record_password_login_failure(
    session: Session,
    request: Request,
    *,
    user: User | None,
    identifier: str,
    message: str,
) -> None:
    blocked = request.app.state.rate_limiter.record_failure_and_block(client_ip(request))
    record_login_event(
        session,
        request,
        user=user,
        phone=identifier,
        method="password",
        status="failed",
        message=message,
    )
    session.commit()
    if blocked:
        raise HTTPException(status_code=403, detail="当前 IP 因异常登录行为已被暂时限制")


def _avatar_initials(display_name: str) -> str:
    if not display_name:
        return "LI"
    ascii_letters = "".join(ch for ch in display_name.upper() if ch.isascii() and ch.isalnum())
    if ascii_letters:
        return ascii_letters[:2]
    return display_name[:2]


def _new_uid(session: Session, phone: str) -> str:
    base = phone[-8:] or "00000000"
    candidate = base
    suffix = 1
    while session.scalar(select(User.id).where(User.uid == candidate).limit(1)):
        suffix += 1
        candidate = f"{base}{suffix}"
    return candidate


def _create_user(session: Session, *, phone: str, username: str | None = None, password: str | None = None) -> User:
    normalized = normalize_phone(phone)
    if session.scalar(select(User).where(User.phone == normalized).limit(1)):
        raise HTTPException(status_code=409, detail="手机号已注册")
    username = (username or normalized).strip()
    if session.scalar(select(User).where(User.username == username).limit(1)):
        raise HTTPException(status_code=409, detail="账号名已存在")
    display_name = "Listingo 用户"
    user = User(
        phone=normalized,
        username=username,
        email="",
        display_name=display_name,
        avatar_initials=_avatar_initials(display_name),
        uid=_new_uid(session, normalized),
        role="user",
        status="active",
        password_hash=hash_password(password) if password else None,
        password_set=bool(password),
        current_plan_code="free",
    )
    session.add(user)
    session.flush()
    create_notification(
        session,
        user.id,
        title="注册成功",
        body="欢迎使用 Listingo，免费版额度已开通。你可以在个人中心查看套餐、额度和消息提醒。",
        category="register",
    )
    return user


@router.post("/auth/sms/send", response_model=SmsSendOut)
async def send_sms(payload: SmsSendCreate, request: Request, session: Session = Depends(get_session)) -> dict[str, Any]:
    normalized_phone = normalize_phone(payload.phone)
    bypass_rate_limit = False
    if payload.purpose == "admin":
        bypass_rate_limit = bool(
            session.scalar(
                select(User.id)
                .where(User.phone == normalized_phone, User.role == "admin", User.status == "active")
                .limit(1)
            )
        )
    result = await send_sms_code(
        session,
        request,
        phone=normalized_phone,
        purpose=payload.purpose,
        cipher=request.app.state.cipher,
        bypass_rate_limit=bypass_rate_limit,
    )
    session.commit()
    return result


@router.post("/auth/sms/login", response_model=AuthMeOut)
def login_with_sms(
    payload: SmsLoginCreate,
    request: Request,
    response: Response,
    session: Session = Depends(get_session),
) -> dict[str, Any]:
    purpose = "register" if payload.mode == "register" else "login"
    verify_sms_code(request, phone=payload.phone, purpose=purpose, code=payload.code)
    phone = normalize_phone(payload.phone)
    user = session.scalar(select(User).where(User.phone == phone).limit(1))
    if not user:
        if payload.mode != "register":
            raise HTTPException(status_code=404, detail="该手机号尚未注册，请先注册")
        user = _create_user(session, phone=phone)
    if user.status != "active":
        raise HTTPException(status_code=403, detail="账号已停用，请联系管理员")
    issue_session(session, request, response, user)
    record_login_event(session, request, user=user, method="sms", status="succeeded")
    session.commit()
    return {"user": public_user(user), "unread_count": unread_count(session, user)}


@router.post("/auth/register", response_model=AuthMeOut)
def register(
    payload: RegisterCreate,
    request: Request,
    response: Response,
    session: Session = Depends(get_session),
) -> dict[str, Any]:
    verify_sms_code(request, phone=payload.phone, purpose="register", code=payload.code)
    user = _create_user(session, phone=payload.phone, username=payload.username, password=payload.password)
    issue_session(session, request, response, user)
    record_login_event(session, request, user=user, method="register", status="succeeded")
    session.commit()
    return {"user": public_user(user), "unread_count": unread_count(session, user)}


@router.post("/auth/password/login", response_model=AuthMeOut)
def login_with_password(
    payload: PasswordLoginCreate,
    request: Request,
    response: Response,
    session: Session = Depends(get_session),
) -> dict[str, Any]:
    ip_address = client_ip(request)
    _consume_login_rate_limit(request, response)
    # WARNING: process-memory blocks disappear after restart; a CAPTCHA is still needed
    # before password login can withstand restart-window credential stuffing.
    user = find_user_by_identifier(session, payload.identifier)
    if not user or not verify_password(user.password_hash, payload.password):
        _record_password_login_failure(
            session,
            request,
            user=user,
            identifier=payload.identifier,
            message="bad_credentials",
        )
        raise HTTPException(status_code=401, detail="账号或密码不正确")
    if user.role == "admin":
        if not payload.admin_code:
            _record_password_login_failure(
                session,
                request,
                user=user,
                identifier=payload.identifier,
                message="admin_code_required",
            )
            raise HTTPException(status_code=422, detail="管理员账号需要短信二次验证")
        try:
            verify_sms_code(request, phone=user.phone, purpose="admin", code=payload.admin_code)
        except HTTPException:
            _record_password_login_failure(
                session,
                request,
                user=user,
                identifier=payload.identifier,
                message="admin_code_invalid",
            )
            raise
    if user.status != "active":
        _record_password_login_failure(
            session,
            request,
            user=user,
            identifier=payload.identifier,
            message="user_disabled",
        )
        raise HTTPException(status_code=403, detail="账号已停用，请联系管理员")
    issue_session(session, request, response, user)
    request.app.state.rate_limiter.clear_login_failures(ip_address)
    record_login_event(session, request, user=user, method="password", status="succeeded")
    session.commit()
    return {"user": public_user(user), "unread_count": unread_count(session, user)}


@router.post("/auth/first-password", response_model=AuthMeOut)
def set_first_password(
    payload: FirstPasswordCreate,
    current_user: User = Depends(get_current_user),
    session: Session = Depends(get_session),
) -> dict[str, Any]:
    if not current_user.first_password_pending and current_user.password_set:
        raise HTTPException(status_code=409, detail="登录密码已设置")
    current_user.password_hash = hash_password(payload.password)
    current_user.password_set = True
    current_user.first_password_pending = False
    create_notification(
        session,
        current_user.id,
        title="管理员密码已设置",
        body="你的管理员账号已完成首次密码设置。后续密码登录仍需要短信二次验证。",
        category="security",
    )
    session.commit()
    return {"user": public_user(current_user), "unread_count": unread_count(session, current_user)}


@router.post("/auth/logout")
def logout(request: Request, response: Response, session: Session = Depends(get_session)) -> dict[str, Any]:
    token = request.cookies.get(SESSION_COOKIE)
    if token:
        auth_session = session.scalar(select(UserSession).where(UserSession.session_token_hash == hash_token(token)))
        if auth_session:
            auth_session.revoked_at = utcnow()
            session.commit()
            runtime = getattr(request.app.state, "runtime_state", None)
            if runtime is not None:
                runtime.delete_best_effort(session_cache_key(hash_token(token)))
    clear_session_cookies(response, secure=request.app.state.settings.cookie_secure)
    return {"ok": True}


@router.get("/auth/me", response_model=AuthMeOut)
def me(current_user: User | None = Depends(get_optional_user), session: Session = Depends(get_session)) -> dict[str, Any]:
    if not current_user:
        return {"user": None, "unread_count": 0}
    return {"user": public_user(current_user), "unread_count": unread_count(session, current_user)}


@router.patch("/account/profile", response_model=AuthMeOut)
def update_profile(payload: ProfileUpdate, current_user: User = Depends(get_current_user), session: Session = Depends(get_session)) -> dict[str, Any]:
    updates = payload.model_dump(exclude_unset=True)
    if "display_name" in updates and updates["display_name"] is not None:
        current_user.display_name = updates["display_name"].strip()
        current_user.avatar_initials = _avatar_initials(current_user.display_name)
    if "email" in updates and updates["email"] is not None:
        current_user.email = updates["email"].strip()
    if "gender" in updates and updates["gender"] is not None:
        current_user.gender = updates["gender"].strip()
    if "bio" in updates and updates["bio"] is not None:
        current_user.bio = updates["bio"].strip()
    session.commit()
    return {"user": public_user(current_user), "unread_count": unread_count(session, current_user)}


@router.post("/account/change-phone/start", response_model=SmsSendOut)
async def change_phone_start(
    payload: ChangePhoneStartCreate,
    request: Request,
    current_user: User = Depends(get_current_user),
    session: Session = Depends(get_session),
) -> dict[str, Any]:
    result = await send_sms_code(
        session,
        request,
        phone=payload.phone,
        purpose="change_phone",
        cipher=request.app.state.cipher,
    )
    session.commit()
    return result


@router.post("/account/change-phone/confirm", response_model=AuthMeOut)
def change_phone_confirm(
    payload: ChangePhoneConfirmCreate,
    request: Request,
    current_user: User = Depends(get_current_user),
    session: Session = Depends(get_session),
) -> dict[str, Any]:
    new_phone = normalize_phone(payload.phone)
    existing = session.scalar(select(User).where(User.phone == new_phone, User.id != current_user.id).limit(1))
    if existing:
        raise HTTPException(status_code=409, detail="手机号已被其他账号绑定")
    verify_sms_code(request, phone=new_phone, purpose="change_phone", code=payload.code)
    current_user.phone = new_phone
    create_notification(session, current_user.id, title="手机号已换绑", body="你的登录手机号已完成换绑。", category="security")
    session.commit()
    return {"user": public_user(current_user), "unread_count": unread_count(session, current_user)}


@router.post("/account/password", response_model=AuthMeOut)
def change_password(
    payload: PasswordChangeCreate,
    request: Request,
    current_user: User = Depends(get_current_user),
    session: Session = Depends(get_session),
) -> dict[str, Any]:
    _require_fresh_nonce(request)
    if current_user.password_set and not verify_password(current_user.password_hash, payload.current_password):
        raise HTTPException(status_code=401, detail="当前密码不正确")
    current_user.password_hash = hash_password(payload.next_password)
    current_user.password_set = True
    current_user.first_password_pending = False
    create_notification(session, current_user.id, title="登录密码已更新", body="你的登录密码已修改。", category="security")
    session.commit()
    return {"user": public_user(current_user), "unread_count": unread_count(session, current_user)}


@router.get("/account/login-events")
def login_events(current_user: User = Depends(get_current_user), session: Session = Depends(get_session)) -> list[dict[str, Any]]:
    rows = session.scalars(
        select(LoginEvent).where(LoginEvent.user_id == current_user.id).order_by(LoginEvent.created_at.desc()).limit(20)
    ).all()
    return [
        {
            "id": row.id,
            "method": row.method,
            "status": row.status,
            "ip_address": row.ip_address,
            "user_agent": row.user_agent,
            "message": row.message,
            "created_at": row.created_at,
        }
        for row in rows
    ]


@router.get("/subscription/plans", response_model=list[SubscriptionPlanOut])
def subscription_plans(session: Session = Depends(get_session)) -> list[dict[str, Any]]:
    return list_subscription_plans(session, include_internal=False)


@router.get("/subscription/me", response_model=QuotaSummaryOut)
def subscription_me(current_user: User = Depends(get_current_user), session: Session = Depends(get_session)) -> dict[str, Any]:
    return current_quota_summary(session, current_user)


@router.get("/quota/me", response_model=QuotaSummaryOut)
def quota_me(current_user: User = Depends(get_current_user), session: Session = Depends(get_session)) -> dict[str, Any]:
    return current_quota_summary(session, current_user)


@router.post("/subscription/orders", response_model=PaymentOrderOut, status_code=201)
def create_order(
    payload: PaymentOrderCreate,
    current_user: User = Depends(get_current_user),
    session: Session = Depends(get_session),
) -> dict[str, Any]:
    order = create_payment_order(session, current_user, plan_code=payload.plan_code, billing_cycle=payload.billing_cycle)
    session.commit()
    return serialize_order(session, order)


@router.post("/subscription/orders/{order_id}/mock-pay", response_model=PaymentOrderOut)
def mock_pay(
    order_id: str,
    request: Request,
    current_user: User = Depends(get_current_user),
    session: Session = Depends(get_session),
) -> dict[str, Any]:
    _require_fresh_nonce(request)
    order = mock_pay_order(session, current_user, order_id)
    session.commit()
    return serialize_order(session, order)


@router.get("/notifications", response_model=list[NotificationOut])
def notifications(current_user: User = Depends(get_current_user), session: Session = Depends(get_session)) -> list[dict[str, Any]]:
    return list_user_notifications(session, current_user)


@router.post("/notifications/{notification_id}/read", response_model=NotificationOut)
def read_notification(
    notification_id: str,
    current_user: User = Depends(get_current_user),
    session: Session = Depends(get_session),
) -> dict[str, Any]:
    notification = session.get(Notification, notification_id)
    if not notification or notification.user_id != current_user.id:
        raise HTTPException(status_code=404, detail="消息不存在")
    mark_notification_read(session, notification)
    session.commit()
    return serialize_notification(notification)


@router.post("/notifications/read-all")
def read_all_notifications(current_user: User = Depends(get_current_user), session: Session = Depends(get_session)) -> dict[str, Any]:
    notifications = session.scalars(select(Notification).where(Notification.user_id == current_user.id, Notification.unread.is_(True))).all()
    for notification in notifications:
        mark_notification_read(session, notification)
    session.commit()
    return {"ok": True, "count": len(notifications)}
