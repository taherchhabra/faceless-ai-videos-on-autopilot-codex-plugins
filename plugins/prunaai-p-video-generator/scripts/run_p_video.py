#!/usr/bin/env python3
"""Generate a video with prunaai/p-video and save it locally."""

from __future__ import annotations

import argparse
import base64
import json
import mimetypes
import os
import re
import sys
import time
import uuid
from pathlib import Path
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.parse import quote, unquote, unquote_to_bytes, urlparse
from urllib.request import Request, urlopen


API_BASE = "https://api.replicate.com/v1"
MODEL_OWNER = "prunaai"
MODEL_NAME = "p-video"
USER_AGENT = "prunaai-p-video-generator/0.1.0"
PLUGIN_ROOT = Path(__file__).resolve().parent.parent
LOCAL_ENV_FILES = (PLUGIN_ROOT / ".env.local",)
TERMINAL_STATUSES = {"succeeded", "failed", "canceled"}
URL_PREFIXES = ("http://", "https://", "data:")
FILE_URL_PREFIX = "file://"
ASPECT_RATIOS = ("16:9", "9:16", "4:3", "3:4", "3:2", "2:3", "1:1")
RESOLUTIONS = ("720p", "1080p")
FPS_VALUES = (24, 48)
EXTENSIONS_BY_MIME = {
    "video/mp4": ".mp4",
    "video/quicktime": ".mov",
    "video/webm": ".webm",
    "image/gif": ".gif",
}


class PVideoError(RuntimeError):
    """Raised for p-video wrapper failures."""


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Generate a single video with prunaai/p-video and save it locally."
    )
    parser.add_argument("prompt", help="Prompt passed directly to prunaai/p-video.")
    parser.add_argument(
        "--image",
        help="Optional image path, file URL, hosted URL, or data URL for image-to-video.",
    )
    parser.add_argument(
        "--audio",
        help="Optional audio path, file URL, hosted URL, or data URL for audio-to-video.",
    )
    parser.add_argument(
        "--aspect-ratio",
        default="16:9",
        choices=ASPECT_RATIOS,
        help="Aspect ratio for text-to-video runs. Ignored when --image is provided.",
    )
    parser.add_argument(
        "--duration",
        type=int,
        default=5,
        choices=range(1, 11),
        metavar="[1-10]",
        help="Video duration in seconds. Ignored when --audio is provided.",
    )
    parser.add_argument(
        "--resolution",
        default="720p",
        choices=RESOLUTIONS,
        help="Output resolution.",
    )
    parser.add_argument(
        "--fps",
        type=int,
        default=24,
        choices=FPS_VALUES,
        help="Output frames per second.",
    )
    parser.add_argument(
        "--draft",
        action="store_true",
        help="Enable draft mode for faster lower-quality previews.",
    )
    parser.add_argument(
        "--prompt-upsampling",
        action=argparse.BooleanOptionalAction,
        default=True,
        help="Enable or disable Replicate prompt upsampling.",
    )
    parser.add_argument(
        "--seed",
        type=int,
        help="Optional random seed for reproducible generation.",
    )
    parser.add_argument(
        "--output-name",
        help="Optional base filename without extension. Defaults to a slug derived from the prompt.",
    )
    parser.add_argument(
        "--output-dir",
        default="output/generated",
        help="Directory for the video and prediction metadata.",
    )
    parser.add_argument(
        "--wait",
        type=int,
        default=60,
        help="Seconds to wait in Replicate sync mode before polling.",
    )
    parser.add_argument(
        "--poll-interval",
        type=float,
        default=2.0,
        help="Seconds between status polls after the initial request.",
    )
    parser.add_argument(
        "--max-polls",
        type=int,
        default=120,
        help="Maximum number of polling attempts.",
    )
    parser.add_argument(
        "--token-env",
        default="REPLICATE_API_TOKEN",
        help="Environment variable that holds the Replicate API token.",
    )
    return parser.parse_args()


def load_env_value(key: str) -> str | None:
    for env_file in LOCAL_ENV_FILES:
        if not env_file.exists():
            continue
        for raw_line in env_file.read_text().splitlines():
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
    raise PVideoError(
        f"Missing {env_name}. Export it or store it in one of: {searched}"
    )


def api_request(
    method: str,
    url: str,
    token: str,
    payload: dict[str, Any] | None = None,
    extra_headers: dict[str, str] | None = None,
    body: bytes | None = None,
) -> dict[str, Any]:
    if payload is not None and body is not None:
        raise PVideoError("Provide either payload or body, not both.")

    headers = {
        "Authorization": f"Bearer {token}",
        "User-Agent": USER_AGENT,
    }
    if extra_headers:
        headers.update(extra_headers)

    if payload is not None:
        headers["Content-Type"] = "application/json"
        body = json.dumps(payload).encode("utf-8")

    request = Request(url, data=body, headers=headers, method=method)
    try:
        with urlopen(request) as response:
            raw = response.read().decode("utf-8")
    except HTTPError as exc:
        message = exc.read().decode("utf-8", "replace")
        raise PVideoError(f"{method} {url} failed with HTTP {exc.code}: {message}") from exc
    except URLError as exc:
        raise PVideoError(f"{method} {url} failed: {exc.reason}") from exc

    try:
        parsed = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise PVideoError(f"{method} {url} returned non-JSON output.") from exc

    if not isinstance(parsed, dict):
        raise PVideoError(f"{method} {url} returned an unexpected response shape.")
    return parsed


def resolve_version(token: str) -> str:
    url = f"{API_BASE}/models/{quote(MODEL_OWNER)}/{quote(MODEL_NAME)}"
    model_data = api_request("GET", url, token)
    latest_version = model_data.get("latest_version") or {}
    version = latest_version.get("id")
    if not isinstance(version, str) or not version:
        raise PVideoError(
            "Could not resolve latest_version.id for prunaai/p-video."
        )
    return version


def content_type_for_path(path: Path) -> str:
    guessed, _ = mimetypes.guess_type(path.name)
    return guessed or "application/octet-stream"


def build_multipart_body(parts: list[tuple[str, Path]]) -> tuple[bytes, str]:
    boundary = f"----replicate-upload-{uuid.uuid4().hex}"
    chunks: list[bytes] = []

    for field_name, path in parts:
        filename = path.name
        content_type = content_type_for_path(path)
        payload = path.read_bytes()
        chunks.append(f"--{boundary}\r\n".encode("utf-8"))
        chunks.append(
            (
                f'Content-Disposition: form-data; name="{field_name}"; '
                f'filename="{filename}"\r\n'
            ).encode("utf-8")
        )
        chunks.append(f"Content-Type: {content_type}\r\n\r\n".encode("utf-8"))
        chunks.append(payload)
        chunks.append(b"\r\n")

    chunks.append(f"--{boundary}--\r\n".encode("utf-8"))
    return b"".join(chunks), f"multipart/form-data; boundary={boundary}"


def upload_local_file(path: Path, token: str) -> str:
    body, content_type = build_multipart_body([("content", path)])
    response = api_request(
        "POST",
        f"{API_BASE}/files",
        token,
        extra_headers={"Content-Type": content_type},
        body=body,
    )
    urls = response.get("urls")
    uploaded_url = urls.get("get") if isinstance(urls, dict) else None
    if not isinstance(uploaded_url, str) or not uploaded_url:
        raise PVideoError(f"Replicate file upload did not return a usable URL for {path}")
    return uploaded_url


def resolve_local_path(value: str) -> Path:
    if value.startswith(FILE_URL_PREFIX):
        parsed = urlparse(value)
        if parsed.scheme != "file":
            raise PVideoError(f"Unsupported file URL: {value}")
        if parsed.netloc not in ("", "localhost"):
            raise PVideoError(f"Unsupported file URL host: {value}")
        resolved = Path(unquote(parsed.path))
    else:
        resolved = Path(value).expanduser()

    if not resolved.is_absolute():
        resolved = (Path.cwd() / resolved).resolve()
    else:
        resolved = resolved.resolve()

    if not resolved.exists():
        raise PVideoError(f"Referenced local file does not exist: {resolved}")
    if not resolved.is_file():
        raise PVideoError(f"Referenced local file is not a file: {resolved}")
    return resolved


def prepare_asset(value: str | None, token: str) -> str | None:
    if not value:
        return None
    if value.startswith(URL_PREFIXES):
        return value
    return upload_local_file(resolve_local_path(value), token)


def create_prediction(
    version: str,
    prompt: str,
    image: str | None,
    audio: str | None,
    aspect_ratio: str,
    duration: int,
    resolution: str,
    fps: int,
    draft: bool,
    prompt_upsampling: bool,
    seed: int | None,
    token: str,
    wait: int,
) -> dict[str, Any]:
    headers: dict[str, str] = {}
    if wait > 0:
        headers["Prefer"] = f"wait={min(wait, 60)}"

    model_input: dict[str, Any] = {
        "prompt": prompt,
        "resolution": resolution,
        "fps": fps,
        "draft": draft,
        "prompt_upsampling": prompt_upsampling,
    }
    if image:
        model_input["image"] = image
    else:
        model_input["aspect_ratio"] = aspect_ratio
    if audio:
        model_input["audio"] = audio
    else:
        model_input["duration"] = duration
    if seed is not None:
        model_input["seed"] = seed

    payload = {
        "version": version,
        "input": model_input,
    }
    return api_request("POST", f"{API_BASE}/predictions", token, payload, headers)


def poll_prediction(
    prediction: dict[str, Any],
    token: str,
    interval: float,
    max_polls: int,
) -> dict[str, Any]:
    current = prediction
    urls = current.get("urls")
    get_url = urls.get("get") if isinstance(urls, dict) else None
    if not isinstance(get_url, str) or not get_url:
        return current

    for _ in range(max_polls):
        status = current.get("status")
        if status in TERMINAL_STATUSES:
            return current
        time.sleep(interval)
        current = api_request("GET", get_url, token)
    return current


def sanitize_stem(value: str) -> str:
    cleaned = re.sub(r"[^A-Za-z0-9._-]+", "-", value.strip().lower()).strip("-")
    return cleaned or "p-video-output"


def default_output_name(prompt: str) -> str:
    clipped = " ".join(prompt.split())[:80]
    return sanitize_stem(f"{clipped}-video")


def unique_base_path(output_dir: Path, stem: str) -> Path:
    counter = 1
    while True:
        suffix = "" if counter == 1 else f"-{counter}"
        candidate = output_dir / f"{stem}{suffix}"
        if not any(
            path.exists()
            for path in (
                candidate.with_suffix(".replicate.json"),
                candidate.with_suffix(".mp4"),
                candidate.with_suffix(".mov"),
                candidate.with_suffix(".webm"),
                candidate.with_suffix(".gif"),
                candidate.with_suffix(".bin"),
            )
        ):
            return candidate
        counter += 1


def extension_for(content_type: str | None, source_url: str | None) -> str:
    if source_url:
        candidate = Path(urlparse(source_url).path).suffix
        if candidate:
            return candidate
    if content_type:
        guessed = EXTENSIONS_BY_MIME.get(content_type)
        if guessed:
            return guessed
        guessed = mimetypes.guess_extension(content_type)
        if guessed:
            return guessed
    return ".bin"


def download_data_url(value: str) -> tuple[bytes, str]:
    header, encoded = value.split(",", 1)
    mime = "application/octet-stream"
    if header.startswith("data:"):
        mime = header[5:].split(";", 1)[0] or mime
    if ";base64" in header:
        data = base64.b64decode(encoded)
    else:
        data = unquote_to_bytes(encoded)
    return data, mime


def download_output(value: str) -> tuple[bytes, str]:
    if value.startswith("data:"):
        return download_data_url(value)

    request = Request(value, headers={"User-Agent": USER_AGENT})
    try:
        with urlopen(request) as response:
            data = response.read()
            content_type = response.headers.get_content_type()
    except HTTPError as exc:
        message = exc.read().decode("utf-8", "replace")
        raise PVideoError(f"Downloading output failed with HTTP {exc.code}: {message}") from exc
    except URLError as exc:
        raise PVideoError(f"Downloading output failed: {exc.reason}") from exc

    return data, content_type


def extract_output_url(prediction: dict[str, Any]) -> str:
    output = prediction.get("output")
    if isinstance(output, str) and output.startswith(URL_PREFIXES):
        return output
    if isinstance(output, list):
        for item in output:
            if isinstance(item, str) and item.startswith(URL_PREFIXES):
                return item
    raise PVideoError("Prediction finished without a downloadable video output.")


def write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2) + "\n")


def main() -> int:
    args = parse_args()
    token = require_token(args.token_env)
    version = resolve_version(token)
    image = prepare_asset(args.image, token)
    audio = prepare_asset(args.audio, token)

    prediction = create_prediction(
        version=version,
        prompt=args.prompt,
        image=image,
        audio=audio,
        aspect_ratio=args.aspect_ratio,
        duration=args.duration,
        resolution=args.resolution,
        fps=args.fps,
        draft=args.draft,
        prompt_upsampling=args.prompt_upsampling,
        seed=args.seed,
        token=token,
        wait=args.wait,
    )
    prediction = poll_prediction(
        prediction,
        token=token,
        interval=args.poll_interval,
        max_polls=args.max_polls,
    )

    status = prediction.get("status")
    if status in {"failed", "canceled"}:
        raise PVideoError(
            f"Prediction {prediction.get('id')} finished with status {status}: {prediction.get('error')}"
        )
    if status != "succeeded":
        raise PVideoError(
            f"Prediction {prediction.get('id')} did not finish within the polling window. "
            f"Last status: {status}"
        )

    output_url = extract_output_url(prediction)
    video_bytes, content_type = download_output(output_url)

    output_dir = Path(args.output_dir).expanduser().resolve()
    output_dir.mkdir(parents=True, exist_ok=True)
    base_path = unique_base_path(
        output_dir,
        sanitize_stem(args.output_name) if args.output_name else default_output_name(args.prompt),
    )

    video_path = base_path.with_suffix(extension_for(content_type, output_url))
    video_path.write_bytes(video_bytes)

    metadata_path = base_path.with_suffix(".replicate.json")
    write_json(metadata_path, prediction)

    summary = {
        "model": f"{MODEL_OWNER}/{MODEL_NAME}",
        "version": version,
        "prediction_id": prediction.get("id"),
        "status": prediction.get("status"),
        "video_path": str(video_path),
        "metadata_path": str(metadata_path),
        "prediction_url": ((prediction.get("urls") or {}).get("web"))
        if isinstance(prediction.get("urls"), dict)
        else None,
    }
    json.dump(summary, sys.stdout, indent=2)
    sys.stdout.write("\n")
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except PVideoError as exc:
        print(str(exc), file=sys.stderr)
        raise SystemExit(1)
