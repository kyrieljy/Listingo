from datetime import timedelta

from sqlalchemy import select

from backend.app.models import User, UserSession, utcnow
from backend.app.services.auth import hash_token


def test_watermark_acknowledgement_follows_account_and_respects_current_plan(client):
    endpoint = "/api/v1/account/watermark-acknowledgement"
    with client.app.state.session_factory() as session:
        paid = User(phone="13800009001", username="paid_export", uid="9001", display_name="Paid", current_plan_code="monthly_basic")
        free = User(phone="13800009002", username="free_export", uid="9002", display_name="Free")
        session.add_all([paid, free])
        session.flush()
        for user, token in ((paid, "paid-first"), (paid, "paid-second"), (free, "free-first")):
            expires_at = utcnow() + timedelta(hours=1)
            session.add(UserSession(
                user_id=user.id, session_token_hash=hash_token(token), refresh_token_hash=hash_token(token + "-refresh"),
                expires_at=expires_at, refresh_expires_at=expires_at,
            ))
        session.commit()

    def as_user(token):
        return {"Cookie": f"listingo_session={token}"}

    def acknowledged(token):
        response = client.get("/api/v1/auth/me", headers=as_user(token))
        assert response.status_code == 200
        return response.json()["user"]["watermark_acknowledged"]

    assert acknowledged("paid-first") is False
    assert client.put(endpoint, headers=as_user("paid-first")).json() == {"watermark_acknowledged": True}
    assert client.put(endpoint, headers=as_user("paid-first")).status_code == 200
    assert acknowledged("paid-second") is True
    assert client.put(endpoint, headers=as_user("free-first")).status_code == 403
    assert acknowledged("free-first") is False

    with client.app.state.session_factory() as session:
        paid = session.scalar(select(User).where(User.username == "paid_export"))
        paid.current_plan_code = "free"
        session.commit()
    assert client.put(endpoint, headers=as_user("paid-second")).status_code == 403
    assert acknowledged("paid-second") is True
