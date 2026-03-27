# Prunaai P-Image Edit Generator

Repo-local Codex plugin for editing images with `prunaai/p-image-edit` on Replicate.

## What it includes

- `skills/generate-with-p-image-edit/SKILL.md`: focused workflow for prompt-based image editing
- `scripts/run_p_image_edit.py`: local wrapper for `prunaai/p-image-edit`
- `assets/`: Replicate branding reused for plugin UI metadata

## Requirements

- Export `REPLICATE_API_TOKEN`
- Or store it once in `plugins/prunaai-p-image-edit-generator/.env.local`

Example `plugins/prunaai-p-image-edit-generator/.env.local`:

```bash
REPLICATE_API_TOKEN=your_token_here
```

## Quick example

```bash
python3 plugins/prunaai-p-image-edit-generator/scripts/run_p_image_edit.py \
  "Turn this into a cinematic jungle action scene" \
  --image output/generated/a-woman-jumping-from-a-tree.jpeg \
  --aspect-ratio match_input_image \
  --output-name woman-jumping-tree-edit
```

The script writes:

- The edited image to `output/generated/<name>.<ext>`
- The raw prediction payload to `output/generated/<name>.replicate.json`

## Notes

- The plugin is intentionally narrow: it only targets `prunaai/p-image-edit`.
- Local image paths are uploaded to the Replicate Files API automatically.
- The wrapper keeps inputs minimal and focused on `prompt`, `images`, `aspect_ratio`, and optional `mode`.
