---
name: generate-with-lyria-3
description: Generate full songs or short music clips with Google's Lyria 3 and save the audio plus metadata locally.
---

# Generate With Lyria 3

Use this skill when the user wants a song, music clip, lyrics-driven composition, or a structured prompt rendered with Google's Lyria 3.

## Prerequisites

- Set `GEMINI_API_KEY` in the environment, or store it in `plugins/lyria-3-song-generator/.env.local`.
- No extra Python packages are required; the wrapper uses the Gemini REST API directly.

## Workflow

1. Keep the user's prompt intact unless they explicitly ask for prompt help.
2. The prompt must use one non-empty line per section in this exact format:

```text
[MM:SS - MM:SS] [SECTION NAME]: Intensity: [X/10]. Lyrics: "[LYRICS OR NONE]" [Detailed musical and emotional breakdown]
```

3. Only use these section names: `Intro`, `Verse`, `Chorus`, `Bridge`, `Outro`, `Build`.
4. Use `--prompt-file` for most runs because the format is usually multi-line.
5. Default to `lyria-3-pro-preview` for full songs. Only switch to `--model lyria-3-clip-preview` when the user explicitly wants a short clip.
6. Add up to 10 `--image` inputs when the user wants the music inspired by reference images.
7. Run the bundled script:

```bash
python3 plugins/lyria-3-song-generator/scripts/run_lyria_song.py \
  --prompt-file prompts/song-idea.txt \
  --output-name song-idea
```

8. The script saves:
   - `output/generated/<name>.<ext>`
   - `output/generated/<name>.lyrics.txt` when text output is returned
   - `output/generated/<name>.gemini.json`

## Rules

- Do not switch to other music models; this plugin is intentionally fixed to Lyria 3.
- Do not accept freeform lyric prompts; require the timestamped section-line format.
- Do not rewrite provided lyrics unless the user asks for that.
- Save the generated audio inside the workspace, not only as console output.
