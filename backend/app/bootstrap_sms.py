"""Interactive first-run SMS setup through SSH, without enabling debug login."""
from getpass import getpass
from sqlalchemy import select
from backend.app.config import Settings
from backend.app.database import build_engine, build_session_factory
from backend.app.models import SmsConfig
from backend.app.security import ApiKeyCipher


def main():
    settings = Settings()
    provider = input("SMS provider (aliyun / aliyun_pnvs): ").strip()
    if provider not in {"aliyun", "aliyun_pnvs"}:
        raise SystemExit("Unsupported provider")
    access_id = getpass("AccessKey ID (hidden): ").strip()
    secret = getpass("AccessKey Secret (hidden): ").strip()
    sign = input("Approved SMS sign name: ").strip()
    login = input("Login template code: ").strip()
    admin = input("Admin verification template code: ").strip()
    if not all((access_id, secret, sign, login, admin)):
        raise SystemExit("All fields are required; nothing changed")
    engine = build_engine(settings)
    try:
        with build_session_factory(engine)() as session:
            config = session.scalar(select(SmsConfig).with_for_update())
            if config is None:
                config = SmsConfig()
                session.add(config)
            config.provider, config.enabled, config.debug_mode = provider, True, False
            config.access_key_id = access_id
            config.encrypted_access_key_secret = ApiKeyCipher(settings.secret_key_path).encrypt(secret)
            config.sign_name, config.login_template_code, config.admin_template_code = sign, login, admin
            session.commit()
        print("SMS configuration saved. Verify actual delivery before opening traffic.")
    finally:
        engine.dispose()


if __name__ == "__main__":
    main()
