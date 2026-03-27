# Replicate Model Runner

Repo-local Codex plugin for running Replicate models and saving outputs into the workspace.

## What it includes

- `skills/run-any-replicate-model/SKILL.md`: guidance for model discovery, schema inspection, and execution
- `scripts/search_replicate_models.py`: search public Replicate models for a task
- `scripts/run_replicate_model.py`: direct HTTP fallback that runs a model from a slug plus JSON input

## Requirements

- Either export `REPLICATE_API_TOKEN`
- Or store it once in `plugins/replicate-model-runner/.env.local`

Example `plugins/replicate-model-runner/.env.local`:

```bash
REPLICATE_API_TOKEN=your_token_here
```

## Quick examples

```bash
python3 plugins/replicate-model-runner/scripts/search_replicate_models.py \
  "fast image generation with good text rendering" \
  --include-collections
```

```bash
python3 plugins/replicate-model-runner/scripts/run_replicate_model.py \
  black-forest-labs/flux-schnell \
  --input-json '{"prompt":"A tiger walking on a rope in a circus"}'
```

```bash
python3 plugins/replicate-model-runner/scripts/run_replicate_model.py \
  prunaai/p-image \
  --input-file path/to/input.json
```

## Local asset inputs

`run_replicate_model.py` can resolve local files anywhere inside the input JSON, not just image fields.

- By default, local file paths are uploaded to the Replicate Files API and replaced with temporary Replicate file URLs before the prediction runs.
- Supported path styles include absolute paths, `./relative-path`, `../relative-path`, `~/home-relative-path`, `file:///...`, and simple filenames like `clip.mp4`.
- Relative paths are resolved from the input JSON file's directory when using `--input-file`, otherwise from the current working directory.

Example:

```bash
python3 plugins/replicate-model-runner/scripts/run_replicate_model.py \
  prunaai/p-image-edit \
  --input-json '{
    "prompt": "Turn this into a cinematic jungle leap",
    "images": ["./output/generated/a-woman-jumping-from-a-tree.jpeg"],
    "aspect_ratio": "match_input_image"
  }'
```

Optional flags:

- `--local-assets upload` (default): upload local files through Replicate Files API
- `--local-assets data-uri`: inline local files as data URIs
- `--local-assets auto`: inline files up to `--inline-max-bytes`, upload larger ones
- `--local-assets off`: disable local file handling

The script writes prediction metadata to `output/replicate/<prediction-id>/` and downloads file outputs into `output/replicate/<prediction-id>/files/`.

When local assets are resolved, the run directory also includes:

- `input.original.json`: the original local-path payload that you supplied
- `prepared-assets.json`: metadata for each local asset that was uploaded or inlined

## References

- Replicate HTTP API: https://replicate.com/docs/reference/http
- Create a prediction: https://replicate.com/docs/topics/predictions/create-a-prediction
