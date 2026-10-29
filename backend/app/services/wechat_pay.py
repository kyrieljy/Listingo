"""Direct-merchant APIv3 Native payments, using WeChat Pay public-key verification."""
from __future__ import annotations

import asyncio
import base64
import json
import logging
import secrets
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path
from urllib.parse import quote, urlencode

import httpx
from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import padding, rsa
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from sqlalchemy import or_, select
from sqlalchemy.orm import Session

from backend.app.config import Settings
from backend.app.models import PaymentOrder, User, utcnow
from backend.app.services.subscriptions import fulfill_paid_order

logger = logging.getLogger(__name__)


class PaymentError(Exception):
    def __init__(self, code: str, message: str, status: int = 502):
        self.code, self.message, self.status = code, message, status
        super().__init__(message)


class WechatPayClient:
    def __init__(self, settings: Settings):
        self.settings = settings
        required = (settings.wechat_mchid, settings.wechat_appid, settings.wechat_merchant_serial,
                    settings.wechat_private_key_path, settings.wechat_public_key_id, settings.wechat_public_key_path)
        if not all(required) or len(settings.wechat_api_v3_key.encode()) != 32:
            raise ValueError("微信支付参数不完整，或 APIv3 密钥不是 32 字节")
        if not settings.wechat_notify_url.startswith("https://"):
            raise ValueError("微信支付回调必须使用 HTTPS")
        self.private_key = serialization.load_pem_private_key(Path(settings.wechat_private_key_path).read_bytes(), password=None)
        self.public_key = serialization.load_pem_public_key(Path(settings.wechat_public_key_path).read_bytes())
        if not isinstance(self.private_key, rsa.RSAPrivateKey) or not isinstance(self.public_key, rsa.RSAPublicKey):
            raise ValueError("微信支付需要 RSA 密钥")

    def verify(self, headers, body: bytes) -> None:
        try:
            timestamp = headers["Wechatpay-Timestamp"]
            nonce = headers["Wechatpay-Nonce"]
            if headers["Wechatpay-Serial"] != self.settings.wechat_public_key_id:
                raise ValueError("unknown verification key")
            if abs(time.time() - int(timestamp)) > 300:
                raise ValueError("stale signature")
            signature = base64.b64decode(headers["Wechatpay-Signature"], validate=True)
            message = timestamp.encode() + b"\n" + nonce.encode() + b"\n" + body + b"\n"
            self.public_key.verify(signature, message, padding.PKCS1v15(), hashes.SHA256())
        except (KeyError, ValueError, InvalidSignature, TypeError) as exc:
            raise PaymentError("INVALID_SIGNATURE", "微信支付签名校验失败", 401) from exc

    def request(self, method: str, path: str, payload: dict | None = None) -> dict:
        body = json.dumps(payload, ensure_ascii=False, separators=(",", ":")) if payload is not None else ""
        timestamp, nonce = str(int(time.time())), secrets.token_hex(16)
        message = f"{method}\n{path}\n{timestamp}\n{nonce}\n{body}\n".encode()
        signature = base64.b64encode(self.private_key.sign(message, padding.PKCS1v15(), hashes.SHA256())).decode()
        authorization = (f'WECHATPAY2-SHA256-RSA2048 mchid="{self.settings.wechat_mchid}",'
                         f'nonce_str="{nonce}",timestamp="{timestamp}",'
                         f'serial_no="{self.settings.wechat_merchant_serial}",signature="{signature}"')
        try:
            with httpx.Client(timeout=10.0, follow_redirects=False) as client:
                response = client.request(method, "https://api.mch.weixin.qq.com" + path, content=body.encode(), headers={
                    "Authorization": authorization, "Accept": "application/json", "Content-Type": "application/json",
                    "Wechatpay-Serial": self.settings.wechat_public_key_id, "User-Agent": "Listingo/1.0",
                })
        except httpx.HTTPError as exc:
            raise PaymentError("NETWORK_ERROR", "支付服务连接失败，请稍后重试") from exc
        logger.info("wechat_api method=%s status=%s request_id=%s", method, response.status_code, response.headers.get("Request-ID", ""))
        # Never consume an unverified error or query response as a payment fact.
        self.verify(response.headers, response.content)
        try:
            data = response.json() if response.content else {}
            if not isinstance(data, dict):
                raise ValueError("invalid object")
        except ValueError as exc:
            raise PaymentError("INVALID_RESPONSE", "微信支付返回格式错误") from exc
        if response.is_error:
            raise PaymentError(str(data.get("code", "GATEWAY_ERROR")), "微信支付请求失败，请稍后重试")
        return data

    def native(self, order: PaymentOrder) -> str:
        snapshot = json.loads(order.snapshot_json)
        data = self.request("POST", "/v3/pay/transactions/native", {
            "appid": self.settings.wechat_appid, "mchid": self.settings.wechat_mchid,
            "description": ("Listingo " + str(snapshot.get("name", "订单"))).encode("utf-8")[:120].decode("utf-8", errors="ignore"),
            "out_trade_no": order.order_no, "notify_url": self.settings.wechat_notify_url,
            "time_expire": order.expires_at.isoformat(timespec="seconds"),
            "amount": {"total": order.amount_cents, "currency": order.currency},
        })
        url = data.get("code_url", "")
        if not isinstance(url, str) or not url.startswith("weixin://wxpay/"):
            raise PaymentError("INVALID_RESPONSE", "微信支付未返回有效二维码")
        return url

    def query(self, order: PaymentOrder) -> dict:
        path = "/v3/pay/transactions/out-trade-no/" + quote(order.order_no, safe="")
        return self.request("GET", path + "?" + urlencode({"mchid": self.settings.wechat_mchid}))

    def close(self, order: PaymentOrder) -> None:
        self.request("POST", "/v3/pay/transactions/out-trade-no/" + quote(order.order_no, safe="") + "/close",
                     {"mchid": self.settings.wechat_mchid})

    def notification(self, headers, body: bytes) -> dict:
        self.verify(headers, body)
        try:
            event = json.loads(body)
            if event["event_type"] != "TRANSACTION.SUCCESS":
                raise ValueError("unexpected event")
            resource = event["resource"]
            if resource["algorithm"] != "AEAD_AES_256_GCM":
                raise ValueError("unexpected algorithm")
            clear = AESGCM(self.settings.wechat_api_v3_key.encode()).decrypt(
                resource["nonce"].encode(), base64.b64decode(resource["ciphertext"], validate=True),
                resource.get("associated_data", "").encode(),
            )
            data = json.loads(clear)
            if not isinstance(data, dict):
                raise ValueError("invalid transaction")
            return data
        except Exception as exc:
            raise PaymentError("INVALID_NOTIFICATION", "支付通知格式或解密失败", 400) from exc


def locked_order(session: Session, order_id: str, user_id: str | None = None) -> PaymentOrder:
    order = session.get(PaymentOrder, order_id)
    if order is None or (user_id is not None and order.user_id != user_id):
        raise PaymentError("NOT_FOUND", "订单不存在", 404)
    # All settlement paths lock user then order, serializing different orders for the same user.
    session.scalar(select(User).where(User.id == order.user_id).with_for_update().execution_options(populate_existing=True))
    return session.scalar(select(PaymentOrder).where(PaymentOrder.id == order_id).with_for_update().execution_options(populate_existing=True))


def settle_transaction(session: Session, client: WechatPayClient, data: dict) -> PaymentOrder:
    order = session.scalar(select(PaymentOrder).where(PaymentOrder.order_no == data.get("out_trade_no")))
    if order is None:
        raise PaymentError("NOT_FOUND", "订单不存在", 404)
    order = locked_order(session, order.id)
    amount = data.get("amount") or {}
    transaction_id = data.get("transaction_id")
    valid = (data.get("mchid") == client.settings.wechat_mchid and data.get("appid") == client.settings.wechat_appid
             and data.get("trade_state") == "SUCCESS" and amount.get("total") == order.amount_cents
             and amount.get("currency") == order.currency and isinstance(transaction_id, str) and 0 < len(transaction_id) <= 64
             and order.payment_channel == "wechat_native")
    if not valid:
        if order.status not in {"paid", "refunded"}:
            order.status, order.payment_error = "manual_review", "PAYMENT_FACT_MISMATCH"
            if (data.get("mchid") == client.settings.wechat_mchid and data.get("appid") == client.settings.wechat_appid
                    and data.get("trade_state") == "SUCCESS" and isinstance(transaction_id, str) and 0 < len(transaction_id) <= 64):
                order.wechat_transaction_id = transaction_id
        logger.error("payment_manual_review order=%s reason=PAYMENT_FACT_MISMATCH", order.order_no)
        return order
    if order.status in {"paid", "refunded", "manual_review"}:
        if order.wechat_transaction_id and order.wechat_transaction_id != transaction_id:
            raise PaymentError("TRANSACTION_MISMATCH", "订单交易号不匹配", 409)
        return order
    order.wechat_transaction_id = transaction_id
    try:
        paid_at = datetime.fromisoformat(data["success_time"].replace("Z", "+00:00"))
        if paid_at.tzinfo is None:
            raise ValueError("missing timezone")
    except (KeyError, ValueError, TypeError, AttributeError) as exc:
        raise PaymentError("INVALID_TRANSACTION", "支付时间格式错误", 400) from exc
    # A late notification is valid if the authoritative payment happened before expiry.
    if order.expires_at and paid_at > order.expires_at:
        order.status, order.payment_error = "manual_review", "PAID_AFTER_EXPIRY"
        order.paid_at = paid_at
        logger.error("payment_manual_review order=%s reason=PAID_AFTER_EXPIRY", order.order_no)
        return order
    fulfill_paid_order(session, order, paid_at=paid_at)
    return order


def reconcile_order(session: Session, client: WechatPayClient, order: PaymentOrder) -> None:
    order = locked_order(session, order.id)
    if order.status != "pending":
        return
    order.last_checked_at = utcnow()
    if order.payment_channel != "wechat_native":
        if order.expires_at and order.expires_at <= utcnow():
            order.status = "expired"
        return
    try:
        data = client.query(order)
    except PaymentError as exc:
        if exc.code == "ORDER_NOT_EXIST" and order.expires_at and order.expires_at <= utcnow():
            order.status = "expired"
            return
        raise
    state = data.get("trade_state")
    if state == "SUCCESS":
        settle_transaction(session, client, data)
    elif state in {"CLOSED", "REVOKED", "PAYERROR"}:
        order.status = "closed"
    elif state == "NOTPAY" and order.expires_at and order.expires_at <= utcnow():
        try:
            client.close(order)
            order.status = "closed"
        except PaymentError as exc:
            if exc.code == "ORDERPAID":
                settle_transaction(session, client, client.query(order))
            else:
                raise


def reconcile_batch(factory, client: WechatPayClient) -> None:
    with factory() as session:
        ids = list(session.scalars(select(PaymentOrder.id).where(
            PaymentOrder.status == "pending",
            or_(PaymentOrder.last_checked_at.is_(None), PaymentOrder.last_checked_at < utcnow() - timedelta(seconds=30)),
        ).order_by(PaymentOrder.last_checked_at.asc().nullsfirst(), PaymentOrder.created_at).limit(50)))
    for order_id in ids:
        with factory() as session:
            try:
                reconcile_order(session, client, session.get(PaymentOrder, order_id))
                session.commit()
            except Exception:
                session.rollback()
                # Advance retry time after rollback, so one broken order cannot starve others.
                with session.begin():
                    order = session.get(PaymentOrder, order_id)
                    if order:
                        order.last_checked_at = utcnow()
                logger.exception("payment_reconcile_failed order_id=%s", order_id)


async def reconcile_loop(factory, client: WechatPayClient, stop: asyncio.Event) -> None:
    while not stop.is_set():
        try:
            await asyncio.to_thread(reconcile_batch, factory, client)
        except Exception:
            logger.exception("payment_reconcile_batch_failed")
        try:
            await asyncio.wait_for(stop.wait(), timeout=client.settings.wechat_reconcile_interval_seconds)
        except asyncio.TimeoutError:
            pass
