---
name: generate-with-p-image-edit
description: Edit one or more images with prunaai/p-image-edit and save the edited image plus Replicate metadata locally.
---

# Generate With P-Image Edit

Use this skill when the user wants a straightforward image editing flow through Replicate using `prunaai/p-image-edit`.

## Prerequisites

- Set `REPLICATE_API_TOKEN` in the environment, or store it in `plugins/prunaai-p-image-edit-generator/.env.local`.

## Workflow

1. Keep the user's prompt intact unless they ask for prompt help.
2. Use one or more `--image` inputs. For editing tasks, the first image is the source image to edit.
3. Pick the aspect ratio that matches the requested use case.
4. Run the bundled script:

```bash
python3 plugins/prunaai-p-image-edit-generator/scripts/run_p_image_edit.py \
  "Turn this into a cinematic jungle action scene" \
  --image output/generated/a-woman-jumping-from-a-tree.jpeg \
  --aspect-ratio match_input_image \
  --output-name woman-jumping-tree-edit
```

5. The script saves:
   - `output/generated/<name>.<ext>`
   - `output/generated/<name>.replicate.json`

## Rules

- Do not search for alternate models; this plugin is intentionally fixed to `prunaai/p-image-edit`.
- Do not add extra inputs unless the model specifically requires them.
- Save the generated image inside the workspace, not only as a Replicate URL.
