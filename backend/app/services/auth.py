from __future__ import annotations

import hashlib
import secrets
from datetime import datetime, timedelta
from typing import Any

from argon2 import PasswordHasher
from argon2.exceptions import VerifyMismatchError
from fastapi import Depends, HTTPException, Request, Response
from sqlalchemy import or_, select
from sqlalchemy.orm import Session

from backend.app.database import get_session
from backend.app.models import LoginEvent, User, UserSession, utcnow
from backend.app.core.rate_limit import client_ip
from backend.app.core.runtime import RuntimeStateService
from backend.app.core.storage.keys import session_cache_key
from backend.app.services.sms import mask_phone, normalize_phone


SESSION_COOKIE = "listingo_session"
REFRESH_COOKIE = "listingo_refresh"

password_hasher = PasswordHasher(time_cost=2, memory_cost=65536, parallelism=2)


def hash_password(password: str) -> str:
    return password_hasher.hash(password)


def verify_password(password_hash: str | None, password: str) -> bool:
    if not password_hash:
        return False
    try:
        return password_hasher.verify(password_hash, password)
    except VerifyMismatchError:
        return False


def hash_token(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def public_user(user: User) -> dict[str, Any]:
    return {
        "id": user.id,
        "phone": user.phone,
        "phone_masked": mask_phone(user.phone),
        "username": user.username,
        "display_name": user.display_name,
        "email": user.email,
        "avatar_initials": user.avatar_initials,
        "uid": user.uid,
        "role": user.role,
        "status": user.status,
        "plan": user.current_plan_code,
        "gender": user.gender,
        "bio": user.bio,
        "password_set": user.password_set,
        "first_password_pending": user.first_password_pending,
        "last_login_at": user.last_login_at,
        "created_at": user.created_at,
        "feishu_webhook": user.feishu_webhook,
        "feishu_webhook_configured": bool(user.feishu_webhook and user.feishu_webhook.strip()),
    }


def find_user_by_identifier(session: Session, identifier: str) -> User | None:
    normalized = normalize_phone(identifier)
    conditions = [User.username == identifier.strip()]
    if normalized:
        conditions.append(User.phone == normalized)
    if "@" in identifier:
        conditions.append(User.email == identifier.strip())
    return session.scalar(select(User).where(or_(*conditions)).limit(1))


def ensure_active_user(user: User) -> None:
    if user.status != "active":
        raise HTTPException(status_code=403, detail="账号已停用，请联系管理员")


def record_login_event(
    session: Session,
    request: Request,
    *,
    user: User | None,
    phone: str = "",
    method: str,
    status: str,
    message: str = "",
) -> None:
    session.add(
        LoginEvent(
            user_id=user.id if user else None,
            phone=normalize_phone(phone or user.phone if user else phone),
            method=method,
            status=status,
            ip_address=client_ip(request),
            user_agent=request.headers.get("user-agent", "")[:1000],
            message=message,
        )
    )


def issue_session(session: Session, request: Request, response: Response, user: User) -> None:
    settings = request.app.state.settings
    session_token = secrets.token_urlsafe(32)
    refresh_token = secrets.token_urlsafe(40)
    now = utcnow()
    auth_session = UserSession(
        user_id=user.id,
        session_token_hash=hash_token(session_token),
        refresh_token_hash=hash_token(refresh_token),
        expires_at=now + timedelta(seconds=settings.session_ttl_seconds),
        refresh_expires_at=now + timedelta(seconds=settings.refresh_ttl_seconds),
        ip_address=client_ip(request),
        user_agent=request.headers.get("user-agent", "")[:1000],
    )
    user.last_login_at = now
    session.add(auth_session)
    response.set_cookie(
        SESSION_COOKIE,
        session_token,
        max_age=settings.session_ttl_seconds,
        httponly=True,
        secure=settings.cookie_secure,
        samesite="lax",
        path="/",
    )
    response.set_cookie(
        REFRESH_COOKIE,
        refresh_token,
        max_age=settings.refresh_ttl_seconds,
        httponly=True,
        secure=settings.cookie_secure,
        samesite="lax",
        path="/",
    )


def clear_session_cookies(response: Response, *, secure: bool = False) -> None:
    response.delete_cookie(SESSION_COOKIE, path="/", secure=secure)
    response.delete_cookie(REFRESH_COOKIE, path="/", secure=secure)


def _testing_user(session: Session, request: Request) -> User | None:
    settings = getattr(request.app.state, "settings", None)
    if not settings or not settings.testing:
        return None
    return session.scalar(select(User).where(User.username == "admin").limit(1)) or session.scalar(
        select(User).order_by(User.created_at.asc()).limit(1)
    )


def _cached_session_metadata(token: str, runtime: RuntimeStateService | None) -> dict[str, str] | None:
    if runtime is None:
        return None
    key = session_cache_key(hash_token(token))
    cached = runtime.get_json_best_effort(key)
    if not isinstance(cached, dict):
        return None
    if not all(isinstance(cached.get(field), str) for field in ("session_id", "user_id", "expires_at")):
        runtime.delete_best_effort(key)
        return None
    return cached


def _cache_session_metadata(token: str, auth_session: UserSession, runtime: RuntimeStateService | None) -> None:
    if runtime is None:
        return
    remaining = int((auth_session.expires_at - utcnow()).total_seconds())
    if remaining < 1:
        return
    runtime.set_json_best_effort(
        session_cache_key(hash_token(token)),
        {
            "session_id": auth_session.id,
            "user_id": auth_session.user_id,
            "expires_at": auth_session.expires_at.isoformat(),
        },
        max(1, min(runtime.ttls.session, remaining)),
    )


def current_user_from_request(session: Session, request: Request) -> User | None:
    token = request.cookies.get(SESSION_COOKIE)
    if token:
        runtime = getattr(request.app.state, "runtime_state", None)
        key = session_cache_key(hash_token(token))
        cached = _cached_session_metadata(token, runtime)
        if cached:
            try:
                expires_at = datetime.fromisoformat(cached["expires_at"])
            except ValueError:
                expires_at = None
            if expires_at is not None and expires_at > utcnow():
                user = session.get(User, cached["user_id"])
                if user:
                    ensure_active_user(user)
                    return user
            runtime.delete_best_effort(key)
            return None

        auth_session = session.scalar(
            select(UserSession).where(
                UserSession.session_token_hash == hash_token(token),
                UserSession.revoked_at.is_(None),
                UserSession.expires_at > utcnow(),
            )
        )
        if not auth_session and runtime is not None:
            runtime.delete_best_effort(key)
        if auth_session:
            _cache_session_metadata(token, auth_session, runtime)
            user = session.get(User, auth_session.user_id)
            if user:
                ensure_active_user(user)
                return user
    fallback = _testing_user(session, request)
    if fallback:
        return fallback
    return None


def get_current_user(request: Request, session: Session = Depends(get_session)) -> User:
    user = current_user_from_request(session, request)
    if not user:
        raise HTTPException(status_code=401, detail="请先登录")
    return user


def get_optional_user(request: Request, session: Session = Depends(get_session)) -> User | None:
    return current_user_from_request(session, request)


def require_admin(request: Request, session: Session = Depends(get_session)) -> User:
    user = get_current_user(request, session)
    if user.role != "admin":
        raise HTTPException(status_code=403, detail="需要管理员权限")
    return user


def can_access_owner(user: User, owner_id: str | None) -> bool:
    return user.role == "admin" or not owner_id or owner_id == user.id


def ensure_owner_access(user: User, owner_id: str | None) -> None:
    if not can_access_owner(user, owner_id):
        raise HTTPException(status_code=404, detail="资源不存在")
