# Prunaai P-Image Generator

Repo-local Codex plugin for generating images with `prunaai/p-image` on Replicate.

## What it includes

- `skills/generate-with-p-image/SKILL.md`: focused workflow for prompt-to-image generation
- `scripts/run_p_image.py`: local wrapper for `prunaai/p-image`
- `assets/`: Replicate branding reused for plugin UI metadata

## Requirements

- Export `REPLICATE_API_TOKEN`
- Or store it once in `plugins/prunaai-p-image-generator/.env.local`

Example `plugins/prunaai-p-image-generator/.env.local`:

```bash
REPLICATE_API_TOKEN=your_token_here
```

## Quick example

```bash
python3 plugins/prunaai-p-image-generator/scripts/run_p_image.py \
  "A woman performing a motorcycle stunt, standing upright on a moving stunt bike, photorealistic action shot" \
  --aspect-ratio 16:9 \
  --output-name woman-bike-stunt
```

The script writes:

- The generated image to `output/generated/<name>.<ext>`
- The raw prediction payload to `output/generated/<name>.replicate.json`

## Notes

- The plugin is intentionally narrow: it only targets `prunaai/p-image`.
- The wrapper keeps inputs minimal and focused on `prompt` plus `aspect_ratio`.
