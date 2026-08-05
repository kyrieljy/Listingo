from __future__ import annotations

import argparse
import asyncio
import json
from pathlib import Path

from backend.app.config import Settings
from backend.app.database import build_engine, build_session_factory
from backend.app.models import Provider
from backend.app.security import ApiKeyCipher
from backend.app.services.providers import HELLOBABYGO_IMAGE_ADAPTER, ProviderClient
from backend.app.services.storage import public_file_url


async def run(provider_code: str, reference_path: Path | None) -> None:
    settings = Settings()
    session_factory = build_session_factory(build_engine(settings))
    with session_factory() as session:
        provider = session.query(Provider).filter_by(code=provider_code).one()
        if not provider.encrypted_api_key:
            raise SystemExit(f"{provider_code}: API key is not configured")
        key = ApiKeyCipher(settings.secret_key_path).decrypt(provider.encrypted_api_key)
        input_paths = [str(reference_path)] if reference_path else []
        input_urls = (
            [public_file_url(settings, reference_path)]
            if reference_path and provider.adapter == HELLOBABYGO_IMAGE_ADAPTER
            else None
        )
        result = await ProviderClient().generate_image(
            provider,
            key,
            "Keep the exact product identity. Create a clean ecommerce image with the words DAILY HYDRATION in the upper left.",
            input_paths,
            "1:1",
            input_urls=input_urls,
        )
        config = json.loads(provider.config_json)
        route = "reference" if input_paths else "generate"
        print(
            json.dumps(
                {
                    "provider": provider.code,
                    "model": provider.model_name,
                    "route": route,
                    "result_bytes": len(result),
                    "resolution": config.get("resolution"),
                    "size": config.get("size"),
                },
                ensure_ascii=False,
            )
        )


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Explicit live image-provider smoke test (billable).")
    parser.add_argument("provider_code", choices=["yunwu-nano", "yunwu-nano-pro", "yunwu-image-2", "aplus-mobile-edit-low-cost"])
    parser.add_argument("--reference", type=Path)
    args = parser.parse_args()
    if args.reference and not args.reference.is_file():
        raise SystemExit(f"Reference image not found: {args.reference}")
    asyncio.run(run(args.provider_code, args.reference))
