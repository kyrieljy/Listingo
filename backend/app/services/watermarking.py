from __future__ import annotations

from pathlib import Path

from PIL import Image


DEFAULT_WATERMARK_PATH = Path(__file__).resolve().parents[1] / "static" / "watermarks" / "ai-generated-badge.png"


def apply_ai_watermark(
    source_path: str | Path,
    destination: str | Path,
    *,
    watermark_path: str | Path = DEFAULT_WATERMARK_PATH,
) -> Path:
    source = Path(source_path)
    output = Path(destination)
    output.parent.mkdir(parents=True, exist_ok=True)

    with Image.open(source) as source_image, Image.open(watermark_path) as watermark_source:
        base = source_image.convert("RGBA")
        watermark = watermark_source.convert("RGBA")
        margin = max(1, round(min(base.width, base.height) * 0.03))
        available_width = max(1, base.width - margin * 2)
        target_width = min(max(96, round(base.width * 0.18)), 220, available_width)
        target_height = max(1, round(watermark.height * target_width / watermark.width))
        watermark = watermark.resize((target_width, target_height), Image.Resampling.LANCZOS)
        x = max(margin, base.width - watermark.width - margin)
        y = max(margin, base.height - watermark.height - margin)
        base.alpha_composite(watermark, (x, y))
        base.save(output, format="PNG")
    return output
