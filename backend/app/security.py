from __future__ import annotations

from pathlib import Path

from cryptography.fernet import Fernet


class ApiKeyCipher:
    def __init__(self, key_path: Path) -> None:
        key_path.parent.mkdir(parents=True, exist_ok=True)
        if not key_path.exists():
            key_path.write_bytes(Fernet.generate_key())
        self._fernet = Fernet(key_path.read_bytes().strip())

    def encrypt(self, value: str) -> str:
        return self._fernet.encrypt(value.encode("utf-8")).decode("ascii")

    def decrypt(self, value: str) -> str:
        return self._fernet.decrypt(value.encode("ascii")).decode("utf-8")


def mask_api_key(value: str | None) -> str | None:
    if not value:
        return None
    if len(value) <= 8:
        return value[:2] + "••••" + value[-2:]
    return value[:4] + "••••••••" + value[-4:]
