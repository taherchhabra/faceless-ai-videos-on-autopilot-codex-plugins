#!/usr/bin/env python3
"""Generate music with Lyria 3 and save it locally."""

from __future__ import annotations

import argparse
import base64
import json
import mimetypes
import os
import re
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.parse import quote
from urllib.request import Request, urlopen


API_BASE = "https://generativelanguage.googleapis.com/v1beta/models"
USER_AGENT = "lyria-3-song-generator/0.1.0"
PLUGIN_ROOT = Path(__file__).resolve().parent.parent
LOCAL_ENV_FILES = (PLUGIN_ROOT / ".env.local",)
DEFAULT_MODEL = "lyria-3-pro-preview"
MODEL_CHOICES = ("lyria-3-pro-preview", "lyria-3-clip-preview")
MAX_IMAGE_INPUTS = 10
PROMPT_FORMAT_NAME = "timestamped-section-lyrics-v1"
PROMPT_FORMAT_EXAMPLE = (
    '[00:00 - 00:12] [Intro]: Intensity: [2/10]. Lyrics: "None" '
    "[Warm electric guitar, soft synth pad, and a nervous hopeful mood.]"
)
SECTION_LINE_RE = re.compile(
    r'^\[(\d{2}):(\d{2}) - (\d{2}):(\d{2})\] '
    r'\[(Intro|Verse|Chorus|Bridge|Outro|Build)\]: '
    r'Intensity: \[(10|[0-9])/10\]\. '
    r'Lyrics: "(?:[^"\\]|\\.)*" '
    r'\[(.+)\]$'
)
EXTENSIONS_BY_MIME = {
    "audio/mpeg": ".mp3",
    "audio/mp3": ".mp3",
    "audio/wav": ".wav",
    "audio/x-wav": ".wav",
    "audio/flac": ".flac",
    "audio/ogg": ".ogg",
}


class LyriaSongError(RuntimeError):
    """Raised for Lyria song wrapper failures."""


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Generate a song or music clip with Lyria 3 and save it locally."
    )
    parser.add_argument(
        "prompt",
        nargs="?",
        help="Structured prompt passed directly to Lyria 3. Must use the section-line lyric format.",
    )
    parser.add_argument(
        "--prompt-file",
        help="Read the structured prompt from a UTF-8 text file. Recommended for multi-line song layouts.",
    )
    parser.add_argument(
        "--image",
        action="append",
        default=[],
        help="Optional local image path. Repeat up to 10 times to condition the music.",
    )
    parser.add_argument(
        "--model",
        default=DEFAULT_MODEL,
        choices=MODEL_CHOICES,
        help="Lyria model to run. Use the clip model only for short clip requests.",
    )
    parser.add_argument(
        "--output-name",
        help="Optional base filename without extension. Defaults to a slug derived from the prompt.",
    )
    parser.add_argument(
        "--output-dir",
        default="output/generated",
        help="Directory for the generated audio, text, and metadata.",
    )
    parser.add_argument(
        "--save-text",
        action=argparse.BooleanOptionalAction,
        default=True,
        help="Save text output such as lyrics or song structure when returned.",
    )
    parser.add_argument(
        "--token-env",
        default="GEMINI_API_KEY",
        help="Environment variable that holds the Gemini API key.",
    )
    return parser.parse_args()


def load_env_value(key: str) -> str | None:
    for env_file in LOCAL_ENV_FILES:
        if not env_file.exists():
            continue
        for raw_line in env_file.read_text(encoding="utf-8").splitlines():
            line = raw_line.strip()
            if not line or line.startswith("#"):
                continue
            if line.startswith("export "):
                line = line[7:].strip()
            if "=" not in line:
                continue
            name, value = line.split("=", 1)
            if name.strip() != key:
                continue
            cleaned = value.strip().strip('"').strip("'")
            if cleaned:
                return cleaned
    return None


def require_token(env_name: str) -> str:
    token = os.environ.get(env_name)
    if token:
        return token

    token = load_env_value(env_name)
    if token:
        return token

    searched = ", ".join(str(path) for path in LOCAL_ENV_FILES)
    raise LyriaSongError(
        f"Missing {env_name}. Export it or store it in one of: {searched}"
    )


def read_prompt(args: argparse.Namespace) -> str:
    if args.prompt:
        prompt = args.prompt
    elif args.prompt_file:
        prompt = Path(args.prompt_file).expanduser().read_text(encoding="utf-8")
    elif not sys.stdin.isatty():
        prompt = sys.stdin.read()
        if not prompt.strip():
            raise LyriaSongError(
                "Missing prompt. Pass a prompt, use --prompt-file, or pipe text on stdin."
            )
    else:
        raise LyriaSongError(
            "Missing prompt. Pass a prompt, use --prompt-file, or pipe text on stdin."
        )

    prompt = prompt.strip()
    if not prompt:
        raise LyriaSongError("Prompt must not be empty.")
    return validate_prompt(prompt)


def validate_prompt(prompt: str) -> str:
    normalized_lines = [line.strip() for line in prompt.splitlines() if line.strip()]
    if not normalized_lines:
        raise LyriaSongError("Prompt must contain at least one formatted section line.")

    for index, line in enumerate(normalized_lines, start=1):
        match = SECTION_LINE_RE.fullmatch(line)
        if match is None:
            raise LyriaSongError(
                "Prompt must use one non-empty line per section in this exact format:\n"
                f"{PROMPT_FORMAT_EXAMPLE}\n"
                f"Invalid line {index}: {line}"
            )

        start_seconds = int(match.group(1)) * 60 + int(match.group(2))
        end_seconds = int(match.group(3)) * 60 + int(match.group(4))
        if end_seconds <= start_seconds:
            raise LyriaSongError(
                f"Line {index} has an end time that is not after the start time: {line}"
            )

    return "\n".join(normalized_lines)


def sanitize_stem(value: str) -> str:
    cleaned = re.sub(r"[^A-Za-z0-9._-]+", "-", value.strip().lower()).strip("-")
    return cleaned or "lyria-song"


def default_output_name(prompt: str) -> str:
    clipped = " ".join(prompt.split())[:80]
    return sanitize_stem(clipped)


def candidate_exists(candidate: Path) -> bool:
    known_paths = [
        candidate.with_suffix(".lyrics.txt"),
        candidate.with_suffix(".gemini.json"),
    ]
    for extension in set(EXTENSIONS_BY_MIME.values()) | {".bin"}:
        known_paths.append(candidate.with_suffix(extension))
        known_paths.append(candidate.parent / f"{candidate.name}-2{extension}")
    return any(path.exists() for path in known_paths)


def unique_base_path(output_dir: Path, stem: str) -> Path:
    counter = 1
    while True:
        suffix = "" if counter == 1 else f"-{counter}"
        candidate = output_dir / f"{stem}{suffix}"
        if not candidate_exists(candidate):
            return candidate
        counter += 1


def guess_mime_type(path: Path) -> str:
    guessed, _ = mimetypes.guess_type(path.name)
    return guessed or "application/octet-stream"


def resolve_images(image_args: list[str]) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    if len(image_args) > MAX_IMAGE_INPUTS:
        raise LyriaSongError(
            f"Lyria 3 currently supports at most {MAX_IMAGE_INPUTS} image inputs."
        )

    request_parts: list[dict[str, Any]] = []
    details: list[dict[str, Any]] = []
    for raw_path in image_args:
        path = Path(raw_path).expanduser()
        if not path.exists() or not path.is_file():
            raise LyriaSongError(f"Image input does not exist or is not a file: {raw_path}")
        mime_type = guess_mime_type(path)
        data = path.read_bytes()
        request_parts.append(
            {
                "inline_data": {
                    "mime_type": mime_type,
                    "data": base64.b64encode(data).decode("ascii"),
                }
            }
        )
        details.append(
            {
                "path": str(path.resolve()),
                "mime_type": mime_type,
                "bytes": len(data),
            }
        )
    return request_parts, details


def api_request(model: str, api_key: str, payload: dict[str, Any]) -> dict[str, Any]:
    url = f"{API_BASE}/{quote(model)}:generateContent"
    body = json.dumps(payload).encode("utf-8")
    request = Request(
        url,
        data=body,
        headers={
            "Content-Type": "application/json",
            "User-Agent": USER_AGENT,
            "x-goog-api-key": api_key,
        },
        method="POST",
    )

    try:
        with urlopen(request) as response:
            raw = response.read().decode("utf-8")
    except HTTPError as exc:
        message = exc.read().decode("utf-8", "replace")
        raise LyriaSongError(
            f"POST {url} failed with HTTP {exc.code}: {message}"
        ) from exc
    except URLError as exc:
        raise LyriaSongError(f"POST {url} failed: {exc.reason}") from exc

    try:
        parsed = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise LyriaSongError("Gemini returned non-JSON output.") from exc

    if not isinstance(parsed, dict):
        raise LyriaSongError("Gemini returned an unexpected response shape.")
    return parsed


def build_payload(prompt: str, image_parts: list[dict[str, Any]]) -> dict[str, Any]:
    return {
        "contents": [
            {
                "parts": [
                    {"text": prompt},
                    *image_parts,
                ]
            }
        ],
        "generationConfig": {
            "responseModalities": ["AUDIO", "TEXT"],
        },
    }


def parse_response_parts(
    response: dict[str, Any],
) -> tuple[list[str], list[dict[str, Any]], list[str], Any]:
    candidates = response.get("candidates")
    if not isinstance(candidates, list) or not candidates:
        prompt_feedback = response.get("promptFeedback")
        raise LyriaSongError(
            "Gemini returned no candidates."
            + (f" promptFeedback={prompt_feedback}" if prompt_feedback else "")
        )

    text_parts: list[str] = []
    audio_parts: list[dict[str, Any]] = []
    finish_reasons: list[str] = []

    for candidate in candidates:
        if not isinstance(candidate, dict):
            continue
        finish_reason = candidate.get("finishReason")
        if isinstance(finish_reason, str) and finish_reason:
            finish_reasons.append(finish_reason)

        content = candidate.get("content")
        parts = content.get("parts") if isinstance(content, dict) else None
        if not isinstance(parts, list):
            continue

        for part in parts:
            if not isinstance(part, dict):
                continue
            text = part.get("text")
            if isinstance(text, str) and text:
                text_parts.append(text)
                continue

            inline_data = part.get("inlineData")
            if inline_data is None:
                inline_data = part.get("inline_data")
            if not isinstance(inline_data, dict):
                continue

            data = inline_data.get("data")
            if not isinstance(data, str) or not data:
                continue

            mime_type = inline_data.get("mimeType")
            if mime_type is None:
                mime_type = inline_data.get("mime_type")
            if not isinstance(mime_type, str) or not mime_type:
                mime_type = "application/octet-stream"

            try:
                decoded = base64.b64decode(data)
            except Exception as exc:  # pragma: no cover - defensive decode error handling
                raise LyriaSongError("Gemini returned invalid base64 audio data.") from exc

            audio_parts.append(
                {
                    "mime_type": mime_type,
                    "data": decoded,
                }
            )

    return text_parts, audio_parts, finish_reasons, response.get("promptFeedback")


def extension_for_mime(mime_type: str) -> str:
    return EXTENSIONS_BY_MIME.get(mime_type) or mimetypes.guess_extension(mime_type) or ".bin"


def save_audio_outputs(
    audio_parts: list[dict[str, Any]],
    base_path: Path,
) -> list[dict[str, Any]]:
    outputs: list[dict[str, Any]] = []
    for index, audio_part in enumerate(audio_parts, start=1):
        stem_path = base_path if index == 1 else base_path.parent / f"{base_path.name}-{index}"
        extension = extension_for_mime(str(audio_part["mime_type"]))
        output_path = stem_path.with_suffix(extension)
        output_path.write_bytes(audio_part["data"])
        outputs.append(
            {
                "path": str(output_path),
                "mime_type": audio_part["mime_type"],
                "bytes": len(audio_part["data"]),
            }
        )
    return outputs


def save_text_output(text_parts: list[str], base_path: Path) -> Path:
    text_path = base_path.with_suffix(".lyrics.txt")
    text_path.write_text("\n\n".join(text_parts).strip() + "\n", encoding="utf-8")
    return text_path


def build_metadata(
    prompt: str,
    model: str,
    image_details: list[dict[str, Any]],
    text_parts: list[str],
    text_path: Path | None,
    audio_outputs: list[dict[str, Any]],
    finish_reasons: list[str],
    prompt_feedback: Any,
) -> dict[str, Any]:
    return {
        "provider": "google",
        "transport": "rest",
        "model": model,
        "prompt_format": PROMPT_FORMAT_NAME,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "prompt": prompt,
        "images": image_details,
        "response_modalities": ["AUDIO", "TEXT"],
        "finish_reasons": finish_reasons,
        "prompt_feedback": prompt_feedback,
        "audio_outputs": audio_outputs,
        "text_output_path": str(text_path) if text_path else None,
        "text_parts": text_parts,
    }


def main() -> None:
    args = parse_args()
    prompt = read_prompt(args)
    api_key = require_token(args.token_env)
    image_parts, image_details = resolve_images(args.image)

    response = api_request(
        model=args.model,
        api_key=api_key,
        payload=build_payload(prompt, image_parts),
    )
    text_parts, audio_parts, finish_reasons, prompt_feedback = parse_response_parts(response)
    if not audio_parts:
        raise LyriaSongError("Lyria 3 returned no audio data.")

    output_dir = Path(args.output_dir).expanduser().resolve()
    output_dir.mkdir(parents=True, exist_ok=True)
    stem = sanitize_stem(Path(args.output_name).stem) if args.output_name else default_output_name(prompt)
    base_path = unique_base_path(output_dir, stem)

    audio_outputs = save_audio_outputs(audio_parts, base_path)
    text_path = save_text_output(text_parts, base_path) if text_parts and args.save_text else None

    metadata = build_metadata(
        prompt=prompt,
        model=args.model,
        image_details=image_details,
        text_parts=text_parts,
        text_path=text_path,
        audio_outputs=audio_outputs,
        finish_reasons=finish_reasons,
        prompt_feedback=prompt_feedback,
    )
    metadata_path = base_path.with_suffix(".gemini.json")
    metadata_path.write_text(json.dumps(metadata, indent=2) + "\n", encoding="utf-8")

    if text_parts:
        print("Text output:")
        print("\n\n".join(text_parts))
        print()

    for audio_output in audio_outputs:
        print(f"Audio saved to: {audio_output['path']}")
    if text_path:
        print(f"Text saved to: {text_path}")
    print(f"Metadata saved to: {metadata_path}")


if __name__ == "__main__":
    try:
        main()
    except LyriaSongError as exc:
        print(f"Error: {exc}", file=sys.stderr)
        raise SystemExit(1)
