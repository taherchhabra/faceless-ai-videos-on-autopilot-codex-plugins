---
name: generate-with-p-video
description: Generate a video with prunaai/p-video and save the video plus Replicate metadata locally.
---

# Generate With P-Video

Use this skill when the user wants a straightforward video generation flow through Replicate using `prunaai/p-video`.

## Prerequisites

- Set `REPLICATE_API_TOKEN` in the environment, or store it in `plugins/prunaai-p-video-generator/.env.local`.

## Workflow

1. Keep the user's prompt intact unless they ask for prompt help.
2. Use `--image` for image-to-video runs and `--audio` when the model should follow an audio track.
3. Pick the aspect ratio, resolution, and FPS that match the requested use case. Start with `--draft` for fast iteration when speed matters more than quality.
4. Run the bundled script:

```bash
python3 plugins/prunaai-p-video-generator/scripts/run_p_video.py \
  "A cinematic motorcycle stunt across a rain-soaked bridge at sunrise" \
  --aspect-ratio 16:9 \
  --duration 5 \
  --output-name motorcycle-stunt
```

5. The script saves:
   - `output/generated/<name>.<ext>`
   - `output/generated/<name>.replicate.json`

## Rules

- Do not search for alternate models; this plugin is intentionally fixed to `prunaai/p-video`.
- Do not invent extra inputs that are not part of the model schema.
- Save the generated video inside the workspace, not only as a Replicate URL.
