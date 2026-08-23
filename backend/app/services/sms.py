from __future__ import annotations

import base64
import hashlib
import hmac
import json
import secrets
from urllib.parse import quote
from uuid import uuid4

import httpx
from fastapi import HTTPException, Request
from sqlalchemy import select
from sqlalchemy.orm import Session

from backend.app.models import SmsConfig, utcnow
from backend.app.security import ApiKeyCipher
from backend.app.config import Settings
from backend.app.core.storage.base import (
    HashConsumeStatus,
    RateLimitStorage,
    StorageUnavailableError,
)
from backend.app.core.storage.keys import (
    sms_attempts_key,
    sms_code_key,
    sms_cooldown_key,
    sms_daily_key,
)


SMS_PURPOSES = {"login", "register", "reset_password", "change_phone", "admin"}
PHONE_COUNTRY_RULES = {
    "86": (11, 11),
    "852": (8, 8),
    "853": (8, 8),
    "886": (8, 10),
    "65": (8, 8),
    "60": (7, 10),
    "81": (9, 10),
    "82": (8, 10),
    "1": (10, 10),
    "44": (10, 10),
    "61": (9, 9),
}
PHONE_COUNTRY_CODES = tuple(sorted(PHONE_COUNTRY_RULES, key=len, reverse=True))
SMS_DAILY_WINDOW_SECONDS = 24 * 60 * 60
SMS_MAX_CODE_ATTEMPTS = 5


def normalize_phone(phone: str) -> str:
    raw = phone.strip()
    has_explicit_country = raw.startswith("+") or raw.startswith("00")
    digits = "".join(ch for ch in raw if ch.isdigit())
    if raw.startswith("00"):
        digits = digits[2:]
    if not digits:
        return ""
    if len(digits) == 13 and digits.startswith("86"):
        return digits[2:]
    if has_explicit_country:
        for country_code in PHONE_COUNTRY_CODES:
            if not digits.startswith(country_code):
                continue
            local_phone = digits[len(country_code):]
            if country_code == "86":
                return local_phone
            return f"+{country_code}{local_phone}"
    return digits


def split_phone(phone: str) -> tuple[str, str]:
    normalized = normalize_phone(phone)
    if normalized.startswith("+"):
        digits = normalized[1:]
        for country_code in PHONE_COUNTRY_CODES:
            if digits.startswith(country_code):
                return country_code, digits[len(country_code):]
        return "", digits
    return "86", normalized


def mask_phone(phone: str) -> str:
    normalized = normalize_phone(phone)
    country_code, local_phone = split_phone(normalized)
    if len(local_phone) < 7:
        return phone
    if country_code == "86":
        return f"{local_phone[:3]}****{local_phone[-4:]}"
    return f"+{country_code} {local_phone[:2]}****{local_phone[-4:]}"


def sms_code_hash(phone: str, purpose: str, code: str) -> str:
    normalized = normalize_phone(phone)
    return hashlib.sha256(f"{normalized}:{purpose}:{code}".encode("utf-8")).hexdigest()


def load_sms_config(session: Session) -> SmsConfig:
    config = session.scalar(select(SmsConfig).order_by(SmsConfig.created_at.asc()).limit(1))
    if config:
        return config
    config = SmsConfig(debug_mode=True, enabled=True)
    session.add(config)
    session.flush()
    return config


def _purpose_template(config: SmsConfig, purpose: str) -> str:
    if purpose == "register":
        return config.register_template_code or config.login_template_code
    if purpose == "change_phone":
        return config.change_phone_template_code or config.login_template_code
    if purpose == "admin":
        return config.admin_template_code or config.login_template_code
    return config.login_template_code


def _assert_send_allowed(
    config: SmsConfig,
    phone: str,
    purpose: str,
    *,
    bypass_rate_limit: bool = False,
) -> None:
    if purpose not in SMS_PURPOSES:
        raise HTTPException(status_code=422, detail="Unsupported SMS purpose")
    country_code, local_phone = split_phone(phone)
    phone_rule = PHONE_COUNTRY_RULES.get(country_code)
    if not phone_rule:
        raise HTTPException(status_code=422, detail="暂不支持该手机区号")
    min_length, max_length = phone_rule
    if not (min_length <= len(local_phone) <= max_length):
        raise HTTPException(status_code=422, detail="请输入有效的手机号")
    if config.code_ttl_seconds < 1 or config.cooldown_seconds < 0 or config.daily_limit_per_phone < 1:
        raise HTTPException(status_code=503, detail="短信验证码配置无效，请联系管理员")


def _sms_identity(phone: str, purpose: str) -> str:
    normalized_phone = normalize_phone(phone)
    return hashlib.sha256(f"{normalized_phone}:{purpose}".encode("utf-8")).hexdigest()


def _reserve_send_quota(
    storage: RateLimitStorage,
    identity: str,
    config: SmsConfig,
    *,
    bypass_rate_limit: bool,
    daily_window_seconds: int = SMS_DAILY_WINDOW_SECONDS,
) -> str:
    reservation_token = uuid4().hex
    if bypass_rate_limit:
        return reservation_token

    try:
        if not storage.reserve_sliding_window(
            sms_daily_key(identity),
            reservation_token,
            config.daily_limit_per_phone,
            daily_window_seconds,
        ):
            raise HTTPException(status_code=429, detail="该手机号今日验证码次数已达上限")

        if config.cooldown_seconds > 0:
            cooldown = storage.set_if_absent(
                sms_cooldown_key(identity),
                reservation_token,
                config.cooldown_seconds,
                allow_eviction=False,
            )
            if not cooldown.success:
                storage.release_sliding_window(sms_daily_key(identity), reservation_token)
                raise HTTPException(
                    status_code=429,
                    detail=f"验证码发送过于频繁，请 {config.cooldown_seconds} 秒后再试",
                )
    except StorageUnavailableError:
        storage.release_sliding_window(sms_daily_key(identity), reservation_token)
        raise
    return reservation_token


def _store_verification_code(
    storage: RateLimitStorage,
    identity: str,
    *,
    phone: str,
    purpose: str,
    code: str,
    ttl: int,
) -> bool:
    stored = storage.setex(
        sms_code_key(identity),
        sms_code_hash(phone, purpose, code),
        ttl,
    )
    if not stored.success:
        return False
    storage.delete(sms_attempts_key(identity))
    return True


def _release_send_quota(
    storage: RateLimitStorage,
    identity: str,
    config: SmsConfig,
    reservation_token: str,
) -> None:
    storage.release_sliding_window(sms_daily_key(identity), reservation_token)
    if config.cooldown_seconds > 0:
        storage.delete_if_equal(sms_cooldown_key(identity), reservation_token)


def _percent_encode(value: str | int) -> str:
    return quote(str(value), safe="")


def sms_provider(config: SmsConfig) -> str:
    provider = (config.provider or "aliyun").strip().lower()
    return provider if provider in {"aliyun", "aliyun_pnvs"} else "aliyun"


async def send_aliyun_sms(
    *,
    access_key_id: str,
    access_key_secret: str,
    region_id: str,
    phone: str,
    sign_name: str,
    template_code: str,
    code: str,
    timeout_seconds: float,
) -> str:
    params: dict[str, str] = {
        "AccessKeyId": access_key_id,
        "Action": "SendSms",
        "Format": "JSON",
        "PhoneNumbers": phone,
        "RegionId": region_id or "cn-hangzhou",
        "SignatureMethod": "HMAC-SHA1",
        "SignatureNonce": str(uuid4()),
        "SignatureVersion": "1.0",
        "SignName": sign_name,
        "TemplateCode": template_code,
        "TemplateParam": json.dumps({"code": code}, ensure_ascii=False, separators=(",", ":")),
        "Timestamp": utcnow().strftime("%Y-%m-%dT%H:%M:%SZ"),
        "Version": "2017-05-25",
    }
    canonical = "&".join(f"{_percent_encode(key)}={_percent_encode(params[key])}" for key in sorted(params))
    string_to_sign = "GET&%2F&" + _percent_encode(canonical)
    digest = hmac.new(f"{access_key_secret}&".encode("utf-8"), string_to_sign.encode("utf-8"), hashlib.sha1).digest()
    params["Signature"] = base64.b64encode(digest).decode("ascii")
    async with httpx.AsyncClient(timeout=timeout_seconds) as client:
        response = await client.get("https://dysmsapi.aliyuncs.com/", params=params)
        response.raise_for_status()
    body = response.json()
    if body.get("Code") != "OK":
        raise RuntimeError(body.get("Message") or body.get("Code") or "Aliyun SMS send failed")
    return str(body.get("BizId") or "aliyun-ok")


async def send_aliyun_pnvs_sms(
    *,
    access_key_id: str,
    access_key_secret: str,
    region_id: str,
    country_code: str,
    phone: str,
    sign_name: str,
    template_code: str,
    code: str,
    valid_seconds: int,
    interval_seconds: int,
    timeout_seconds: float,
) -> str:
    valid_minutes = max(1, (valid_seconds + 59) // 60)
    params: dict[str, str] = {
        "AccessKeyId": access_key_id,
        "Action": "SendSmsVerifyCode",
        "AutoRetry": "1",
        "CodeLength": str(len(code)),
        "CodeType": "1",
        "CountryCode": country_code,
        "DuplicatePolicy": "1",
        "Format": "JSON",
        "Interval": str(interval_seconds),
        "OutId": f"auth_{uuid4().hex[:18]}",
        "PhoneNumber": phone,
        "RegionId": region_id or "cn-hangzhou",
        "ReturnVerifyCode": "false",
        "SignName": sign_name,
        "SignatureMethod": "HMAC-SHA1",
        "SignatureNonce": str(uuid4()),
        "SignatureVersion": "1.0",
        "TemplateCode": template_code,
        "TemplateParam": json.dumps({"code": code, "min": str(valid_minutes)}, ensure_ascii=False, separators=(",", ":")),
        "Timestamp": utcnow().strftime("%Y-%m-%dT%H:%M:%SZ"),
        "ValidTime": str(valid_seconds),
        "Version": "2017-05-25",
    }
    canonical = "&".join(f"{_percent_encode(key)}={_percent_encode(params[key])}" for key in sorted(params))
    string_to_sign = "GET&%2F&" + _percent_encode(canonical)
    digest = hmac.new(f"{access_key_secret}&".encode("utf-8"), string_to_sign.encode("utf-8"), hashlib.sha1).digest()
    params["Signature"] = base64.b64encode(digest).decode("ascii")
    async with httpx.AsyncClient(timeout=timeout_seconds) as client:
        response = await client.get("https://dypnsapi.aliyuncs.com/", params=params)
        response.raise_for_status()
    body = response.json()
    code_value = body.get("Code") or body.get("code")
    success = body.get("Success", body.get("success", True))
    if code_value != "OK" or success is False:
        raise RuntimeError(body.get("Message") or body.get("message") or code_value or "Aliyun PNVS SMS send failed")
    model = body.get("Model") or body.get("model") or {}
    return str(model.get("BizId") or model.get("bizId") or model.get("RequestId") or model.get("requestId") or body.get("RequestId") or body.get("requestId") or "aliyun-pnvs-ok")


async def send_sms_code(
    session: Session,
    request: Request,
    *,
    phone: str,
    purpose: str,
    cipher: ApiKeyCipher,
    bypass_rate_limit: bool = False,
) -> dict[str, object]:
    normalized_phone = normalize_phone(phone)
    country_code, local_phone = split_phone(normalized_phone)
    config = load_sms_config(session)
    settings = request.app.state.settings
    if not isinstance(settings, Settings):
        settings = Settings()
    _assert_send_allowed(config, normalized_phone, purpose, bypass_rate_limit=bypass_rate_limit)
    if not config.enabled and not config.debug_mode:
        raise HTTPException(status_code=503, detail="短信服务未启用，请联系管理员")
    storage = request.app.state.rate_limiter.storage
    identity = _sms_identity(normalized_phone, purpose)
    reservation_token = _reserve_send_quota(
        storage,
        identity,
        config,
        bypass_rate_limit=bypass_rate_limit,
        daily_window_seconds=settings.redis_sms_daily_window_seconds,
    )

    configured_debug_code = settings.debug_sms_code.strip() if settings.debug_sms_code else ""
    code = configured_debug_code if config.debug_mode and configured_debug_code else f"{secrets.randbelow(1_000_000):06d}"
    try:
        if not config.debug_mode:
            template_code = _purpose_template(config, purpose)
            secret = cipher.decrypt(config.encrypted_access_key_secret) if config.encrypted_access_key_secret else ""
            missing = []
            if not config.access_key_id:
                missing.append("AccessKey ID")
            if not secret:
                missing.append("AccessKey Secret")
            if not config.sign_name:
                missing.append("SignName 短信签名")
            if not template_code:
                missing.append("TemplateCode 短信模板")
            if missing:
                raise HTTPException(status_code=503, detail=f"短信服务参数未配置完整：请配置 {', '.join(missing)}")
            provider = sms_provider(config)
            if provider == "aliyun_pnvs":
                await send_aliyun_pnvs_sms(
                    access_key_id=config.access_key_id,
                    access_key_secret=secret,
                    region_id=config.region_id,
                    country_code=country_code,
                    phone=local_phone,
                    sign_name=config.sign_name,
                    template_code=template_code,
                    code=code,
                    valid_seconds=config.code_ttl_seconds,
                    interval_seconds=config.cooldown_seconds,
                    timeout_seconds=settings.sms_timeout_seconds,
                )
            else:
                await send_aliyun_sms(
                    access_key_id=config.access_key_id,
                    access_key_secret=secret,
                    region_id=config.region_id,
                    phone=local_phone if country_code == "86" else f"{country_code}{local_phone}",
                    sign_name=config.sign_name,
                    template_code=template_code,
                    code=code,
                    timeout_seconds=settings.sms_timeout_seconds,
                )
        if not _store_verification_code(
            storage,
            identity,
            phone=normalized_phone,
            purpose=purpose,
            code=code,
            ttl=config.code_ttl_seconds,
        ):
            raise HTTPException(status_code=503, detail="验证码存储暂不可用，请稍后再试")
    except (httpx.HTTPError, RuntimeError, HTTPException, StorageUnavailableError) as exc:
        _release_send_quota(storage, identity, config, reservation_token)
        if isinstance(exc, httpx.HTTPError):
            raise HTTPException(status_code=502, detail=f"短信发送失败：{exc}") from exc
        if isinstance(exc, RuntimeError):
            raise HTTPException(status_code=502, detail=f"短信发送失败：{exc}") from exc
        raise

    return {
        "ok": True,
        "expires_in": config.code_ttl_seconds,
        "debug_code": code if config.debug_mode else None,
        "message": f"验证码已发送至 {mask_phone(normalized_phone)}",
    }


def verify_sms_code(request: Request, *, phone: str, purpose: str, code: str) -> None:
    normalized_phone = normalize_phone(phone)
    storage = request.app.state.rate_limiter.storage
    settings = request.app.state.settings
    if not isinstance(settings, Settings):
        settings = Settings()
    max_attempts = settings.redis_sms_max_attempts
    identity = _sms_identity(normalized_phone, purpose)
    code_key = sms_code_key(identity)
    stored_code = storage.get(code_key)
    if stored_code is None:
        raise HTTPException(status_code=422, detail="验证码不存在或已过期")
    status = storage.consume_hash_once(
        code_key,
        sms_attempts_key(identity),
        sms_code_hash(normalized_phone, purpose, code.strip()),
        ttl=stored_code.expires_in_seconds or 60,
        max_attempts=max_attempts,
    )
    if status is HashConsumeStatus.MISSING:
        raise HTTPException(status_code=422, detail="验证码不存在或已过期")
    if status is HashConsumeStatus.LIMIT_EXCEEDED:
        raise HTTPException(status_code=429, detail="验证码尝试次数过多，请重新获取")
    if status is HashConsumeStatus.MISMATCH:
        raise HTTPException(status_code=422, detail="验证码不正确")
