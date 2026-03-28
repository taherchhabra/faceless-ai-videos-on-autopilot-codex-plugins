# Lyria 3 Song Generator

Repo-local Codex plugin for generating songs with Google's `lyria-3-pro-preview` model and short clips with `lyria-3-clip-preview`.

## What it includes

- `skills/generate-with-lyria-3/SKILL.md`: focused workflow for Lyria 3 music generation
- `scripts/run_lyria_song.py`: local wrapper that calls the Gemini REST API with only the Python standard library
- `assets/`: lightweight local SVG assets for plugin metadata

## Requirements

- Export `GEMINI_API_KEY`
- Or store it once in `plugins/lyria-3-song-generator/.env.local`
- Python 3 with standard-library HTTPS support. No extra Python packages are required.

Example `plugins/lyria-3-song-generator/.env.local`:

```bash
GEMINI_API_KEY=your_api_key_here
```

## Required lyric format

Every non-empty prompt line must use this exact format:

```text
[MM:SS - MM:SS] [SECTION NAME]: Intensity: [X/10]. Lyrics: "[LYRICS OR NONE]" [Detailed musical and emotional breakdown]
```

Allowed section names:

- `Intro`
- `Verse`
- `Chorus`
- `Bridge`
- `Outro`
- `Build`

Example prompt file:

```text
[00:00 - 00:12] [Intro]: Intensity: [2/10]. Lyrics: "None" [Warm electric guitar, soft synth pad, and a nervous hopeful mood.]
[00:12 - 00:30] [Verse]: Intensity: [4/10]. Lyrics: "Streetlights drip gold on the avenue / Shoes on the concrete keeping time with you" [Gentle kick, close vocal, and a restrained indie-pop groove.]
[00:30 - 00:48] [Chorus]: Intensity: [8/10]. Lyrics: "City lights after rain / Burning bright through the pain" [Wide synths, bigger drums, soaring harmonies, and a cinematic emotional lift.]
[00:48 - 01:00] [Outro]: Intensity: [3/10]. Lyrics: "None" [The drums fall away, reverb tails linger, and the song resolves softly.]
```

The script rejects freeform prompts that do not match this format.

## Quick examples

Generate a full song from a formatted prompt file:

```bash
python3 plugins/lyria-3-song-generator/scripts/run_lyria_song.py \
  --prompt-file prompts/city-lights.txt \
  --output-name city-lights
```

Generate a short clip instead of a full song:

```bash
python3 plugins/lyria-3-song-generator/scripts/run_lyria_song.py \
  --prompt-file prompts/acoustic-clip.txt \
  --model lyria-3-clip-preview \
  --output-name acoustic-clip
```

Condition the music on local reference images:

```bash
python3 plugins/lyria-3-song-generator/scripts/run_lyria_song.py \
  --prompt-file prompts/storm-atmosphere.txt \
  --image references/storm-1.jpg \
  --image references/storm-2.jpg \
  --output-name storm-atmosphere
```

The script writes:

- The generated audio to `output/generated/<name>.<ext>`
- Optional lyrics or structure text to `output/generated/<name>.lyrics.txt`
- Run metadata to `output/generated/<name>.gemini.json`

## Notes

- The wrapper defaults to `lyria-3-pro-preview` because it is intended for full songs.
- Input prompts must use the required timestamped section-line lyric format; freeform prose prompts are rejected before the API call.
- Text output may contain generated lyrics or a structured description of the song, depending on the prompt and model response.
- Local image conditioning is limited to 10 files per request to match the current Lyria 3 docs.
- Image inputs are sent inline as base64 in the request body, so very large images will increase request size.
- Prompts are kept intact; use `--prompt-file` for most runs because the required format is usually multi-line.
