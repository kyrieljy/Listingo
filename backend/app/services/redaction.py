from __future__ import annotations

import json
from typing import Any


SECRET_KEYS = {"authorization", "api_key", "apikey", "token", "cookie", "set-cookie", "encrypted_api_key"}


def redact(value: Any) -> Any:
    if isinstance(value, dict):
        clean: dict[str, Any] = {}
        for key, item in value.items():
            if key.lower() in SECRET_KEYS:
                clean[key] = "[REDACTED]"
            elif isinstance(item, str) and len(item) > 300 and _looks_like_base64(item):
                clean[key] = f"[BASE64 {len(item)} chars]"
            else:
                clean[key] = redact(item)
        return clean
    if isinstance(value, list):
        return [redact(item) for item in value]
    return value


def safe_json(value: Any) -> str:
    return json.dumps(redact(value), ensure_ascii=False, default=str)


def _looks_like_base64(value: str) -> bool:
    candidate = value.removeprefix("data:image/png;base64,").removeprefix("data:image/jpeg;base64,")
    return len(candidate) > 300 and all(character.isalnum() or character in "+/=_-\n\r" for character in candidate[:300])

