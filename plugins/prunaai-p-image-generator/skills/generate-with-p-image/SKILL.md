---
name: generate-with-p-image
description: Generate a single image with prunaai/p-image and save the image plus Replicate metadata locally.
---

# Generate With P-Image

Use this skill when the user wants a straightforward image generation flow through Replicate using `prunaai/p-image`.

## Prerequisites

- Set `REPLICATE_API_TOKEN` in the environment, or store it in `plugins/prunaai-p-image-generator/.env.local`.

## Workflow

1. Keep the user's prompt intact unless they ask for prompt help.
2. Pick the aspect ratio that matches the requested use case.
3. Run the bundled script:

```bash
python3 plugins/prunaai-p-image-generator/scripts/run_p_image.py \
  "A tiger walking on a tightrope in a circus" \
  --aspect-ratio 16:9 \
  --output-name tiger-circus
```

4. The script saves:
   - `output/generated/<name>.<ext>`
   - `output/generated/<name>.replicate.json`

## Rules

- Do not search for alternate models; this plugin is intentionally fixed to `prunaai/p-image`.
- Do not add extra inputs unless the model specifically requires them.
- Save the generated image inside the workspace, not only as a Replicate URL.
