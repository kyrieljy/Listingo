# Listingo 图片文字编辑提示词

You are editing an ecommerce product image. Use the provided image as the canonical source image.

Task: replace text content only.

Detected text lines and requested replacements:
{{REPLACEMENTS_TABLE}}

Rules:
- Replace each listed original text line with the exact new text.
- Preserve the original text position, font style, font weight, font size, color, alignment, spacing, and text box boundaries as much as possible.
- If the new text is longer or shorter, adjust only wrapping, tracking, or local text fitting inside the original text area.
- Keep every unlisted text line unchanged.
- Do not translate, rewrite, add, or remove any other text.
- Do not change the product, background, lighting, shadows, props, layout, aspect ratio, watermark, badges, or visual composition.
- Regenerate only the smallest affected text regions and blend them naturally with surrounding pixels.
- Output the edited image only.
