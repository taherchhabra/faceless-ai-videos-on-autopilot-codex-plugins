# Prunaai P-Video Generator

Repo-local Codex plugin for generating videos with `prunaai/p-video` on Replicate.

## What it includes

- `skills/generate-with-p-video/SKILL.md`: focused workflow for prompt-based video generation
- `scripts/run_p_video.py`: local wrapper for `prunaai/p-video`
- `assets/`: Replicate branding reused for plugin UI metadata

## Requirements

- Export `REPLICATE_API_TOKEN`
- Or store it once in `plugins/prunaai-p-video-generator/.env.local`

Example `plugins/prunaai-p-video-generator/.env.local`:

```bash
REPLICATE_API_TOKEN=your_token_here
```

## Quick examples

Text to video:

```bash
python3 plugins/prunaai-p-video-generator/scripts/run_p_video.py \
  "A cinematic motorcycle stunt across a rain-soaked bridge at sunrise" \
  --aspect-ratio 16:9 \
  --duration 5 \
  --output-name motorcycle-stunt
```

Image to video:

```bash
python3 plugins/prunaai-p-video-generator/scripts/run_p_video.py \
  "Turn this product photo into a polished ad shot with subtle camera movement" \
  --image output/generated/product-shot.png \
  --duration 5 \
  --output-name product-ad
```

The script writes:

- The generated video to `output/generated/<name>.<ext>`
- The raw prediction payload to `output/generated/<name>.replicate.json`

## Notes

- The plugin is intentionally narrow: it only targets `prunaai/p-video`.
- Local `--image` and `--audio` paths are uploaded to the Replicate Files API automatically.
- `--aspect-ratio` only applies to text-only runs. Replicate ignores it when an image is provided.
- `--duration` only applies when no audio track is provided. Replicate uses the audio duration otherwise.
