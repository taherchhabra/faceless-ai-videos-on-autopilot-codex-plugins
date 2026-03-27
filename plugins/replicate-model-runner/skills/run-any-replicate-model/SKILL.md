---
name: run-any-replicate-model
description: Run any Replicate model, inspect schemas, and save generated outputs locally with the bundled CLI.
---

# Run Any Replicate Model

Use this skill when the user wants to run a model on Replicate, compare candidate models, inspect a model schema, or generate file outputs like images, audio, or video.

## Prerequisites

- Set `REPLICATE_API_TOKEN` in the environment, or store it in `plugins/replicate-model-runner/.env.local`.

## Workflow

1. If the user does not know which model to use, search first:

```bash
python3 plugins/replicate-model-runner/scripts/search_replicate_models.py \
  "fast image generation with good text rendering" \
  --include-collections
```

2. Identify the chosen model slug as `owner/name`.
3. Inspect the schema before guessing inputs.
   - Open the model's `api/schema` page or fetch model metadata through the Replicate HTTP API.
4. Build exact input JSON.
5. Run the bundled script:

```bash
python3 plugins/replicate-model-runner/scripts/run_replicate_model.py owner/name \
  --input-json '{"prompt":"A tiger walking on a tightrope in a circus"}'
```

6. For larger inputs, use a JSON file:

```bash
python3 plugins/replicate-model-runner/scripts/run_replicate_model.py owner/name \
  --input-file path/to/input.json
```

7. If model inputs include local files such as images, audio, video, PDFs, or zip files, pass the local paths directly in the JSON. The runner uploads them automatically by default.

8. If you need reproducibility, pin the model version:

```bash
python3 plugins/replicate-model-runner/scripts/run_replicate_model.py owner/name \
  --version 8527975e894984ac13c83a6ba96533dbe666cd1093b0dc4ba3632c0baa5f3ca2 \
  --input-file path/to/input.json
```

## Output layout

- Raw prediction: `output/replicate/<prediction-id>/prediction.json`
- Normalized output payload: `output/replicate/<prediction-id>/output.json`
- Original local-path payload when assets were resolved: `output/replicate/<prediction-id>/input.original.json`
- Uploaded or inlined asset metadata: `output/replicate/<prediction-id>/prepared-assets.json`
- Downloaded files: `output/replicate/<prediction-id>/files/`

## Rules

- Do not guess model inputs without checking the schema.
- If the user only describes a task, search for candidate models before picking one.
- Keep the user's exact prompt and only add detail when they ask for prompt help.
- Save generated outputs inside the workspace, not only as temporary Replicate URLs.
- Prefer direct local file paths over hand-built data URIs unless the user explicitly wants inline inputs.
