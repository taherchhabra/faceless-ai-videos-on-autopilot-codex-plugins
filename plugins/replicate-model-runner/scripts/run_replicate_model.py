#!/usr/bin/env python3
"""Run a Replicate model and save generated outputs locally."""

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
from typing import Any, Iterator
from urllib.error import HTTPError, URLError
from urllib.parse import quote, unquote, unquote_to_bytes, urlparse
from urllib.request import Request, urlopen


API_BASE = "https://api.replicate.com/v1"
USER_AGENT = "replicate-model-runner/0.1.0"
TERMINAL_STATUSES = {"succeeded", "failed", "canceled"}
URL_PREFIXES = ("http://", "https://", "data:")
FILE_URL_PREFIX = "file://"
PLUGIN_ROOT = Path(__file__).resolve().parent.parent
LOCAL_ENV_FILES = (PLUGIN_ROOT / ".env.local",)
DEFAULT_DATA_URI_MAX_BYTES = 1_000_000
EXTENSIONS_BY_MIME = {
    "image/png": ".png",
    "image/jpeg": ".jpg",
    "image/webp": ".webp",
    "image/gif": ".gif",
    "audio/mpeg": ".mp3",
    "audio/wav": ".wav",
    "audio/x-wav": ".wav",
    "audio/flac": ".flac",
    "video/mp4": ".mp4",
    "application/json": ".json",
    "text/plain": ".txt",
}


class ReplicateError(RuntimeError):
    """Raised for Replicate API failures."""


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Run any Replicate model from a model slug plus JSON input."
    )
    parser.add_argument(
        "model",
        help="Model slug in owner/name format.",
    )
    parser.add_argument(
        "--version",
        help="Optional Replicate version id. If omitted, the latest version is resolved automatically.",
    )
    input_group = parser.add_mutually_exclusive_group()
    input_group.add_argument(
        "--input-json",
        default="{}",
        help="JSON object with model inputs.",
    )
    input_group.add_argument(
        "--input-file",
        help="Path to a JSON file containing model inputs.",
    )
    parser.add_argument(
        "--local-assets",
        choices=("upload", "data-uri", "auto", "off"),
        default="upload",
        help=(
            "How to handle local file paths found inside model inputs. "
            "'upload' sends them to the Replicate Files API, 'data-uri' inlines them, "
            "'auto' inlines files up to --inline-max-bytes and uploads larger ones, "
            "and 'off' leaves input strings unchanged."
        ),
    )
    parser.add_argument(
        "--inline-max-bytes",
        type=int,
        default=DEFAULT_DATA_URI_MAX_BYTES,
        help="Maximum local file size to inline as a data URI when --local-assets=auto.",
    )
    parser.add_argument(
        "--output-dir",
        default="output/replicate",
        help="Base directory for saved predictions.",
    )
    parser.add_argument(
        "--wait",
        type=int,
        default=60,
        help="Seconds to wait in Replicate sync mode before polling. Use 0 to skip sync wait.",
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
        "--cancel-after",
        help="Optional Replicate Cancel-After duration such as 30s, 5m, or 1h30m.",
    )
    parser.add_argument(
        "--token-env",
        default="REPLICATE_API_TOKEN",
        help="Environment variable that holds the Replicate API token.",
    )
    parser.add_argument(
        "--no-download",
        action="store_true",
        help="Do not download file outputs; only save the prediction payload.",
    )
    return parser.parse_args()


def load_input_payload(args: argparse.Namespace) -> tuple[dict[str, Any], Path]:
    if args.input_file:
        input_path = Path(args.input_file).expanduser().resolve()
        payload = json.loads(input_path.read_text())
        base_dir = input_path.parent
    else:
        payload = json.loads(args.input_json)
        base_dir = Path.cwd()
    if not isinstance(payload, dict):
        raise ReplicateError("Input payload must be a JSON object.")
    return payload, base_dir


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
    raise ReplicateError(
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
        raise ReplicateError("Provide either payload or body, not both.")
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
        raise ReplicateError(f"{method} {url} failed with HTTP {exc.code}: {message}") from exc
    except URLError as exc:
        raise ReplicateError(f"{method} {url} failed: {exc.reason}") from exc

    try:
        parsed = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise ReplicateError(f"{method} {url} returned non-JSON output.") from exc

    if not isinstance(parsed, dict):
        raise ReplicateError(f"{method} {url} returned an unexpected response shape.")
    return parsed


def parse_model_slug(model: str) -> tuple[str, str]:
    if "/" not in model:
        raise ReplicateError("Model must use owner/name format.")
    owner, name = model.split("/", 1)
    if not owner or not name:
        raise ReplicateError("Model must use owner/name format.")
    return owner, name


def resolve_version(model: str, token: str) -> tuple[str, dict[str, Any]]:
    owner, name = parse_model_slug(model)
    url = f"{API_BASE}/models/{quote(owner)}/{quote(name)}"
    model_data = api_request("GET", url, token)
    latest_version = model_data.get("latest_version") or {}
    version = latest_version.get("id")
    if not isinstance(version, str) or not version:
        raise ReplicateError(
            "Could not resolve latest_version.id for this model. Pass --version explicitly."
        )
    return version, model_data


def create_prediction(
    version: str,
    input_payload: dict[str, Any],
    token: str,
    wait: int,
    cancel_after: str | None,
) -> dict[str, Any]:
    headers: dict[str, str] = {}
    if wait > 0:
        headers["Prefer"] = f"wait={min(wait, 60)}"
    if cancel_after:
        headers["Cancel-After"] = cancel_after
    payload = {
        "version": version,
        "input": input_payload,
    }
    return api_request("POST", f"{API_BASE}/predictions", token, payload, headers)


def poll_prediction(
    prediction: dict[str, Any],
    token: str,
    interval: float,
    max_polls: int,
) -> dict[str, Any]:
    current = prediction
    get_url = ((current.get("urls") or {}).get("get")) if isinstance(current.get("urls"), dict) else None
    if not get_url:
        return current

    for _ in range(max_polls):
        status = current.get("status")
        output = current.get("output")
        if status in TERMINAL_STATUSES or output not in (None, ""):
            return current
        time.sleep(interval)
        current = api_request("GET", get_url, token)
    return current


def sanitize_filename(name: str) -> str:
    cleaned = re.sub(r"[^A-Za-z0-9._-]+", "-", name).strip("-")
    return cleaned or "output"


def looks_like_url(value: str) -> bool:
    return value.startswith(URL_PREFIXES)


def is_plain_filename(value: str) -> bool:
    return bool(re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._-]*\.[A-Za-z0-9]{1,16}", value))


def resolve_local_asset_path(value: str, base_dir: Path) -> Path | None:
    if not isinstance(value, str) or not value or looks_like_url(value):
        return None

    candidate_value: str | None = None
    explicit_path = False
    if value.startswith(FILE_URL_PREFIX):
        parsed = urlparse(value)
        if parsed.scheme != "file":
            return None
        if parsed.netloc not in ("", "localhost"):
            raise ReplicateError(f"Unsupported file URL host for input asset: {value}")
        candidate_value = unquote(parsed.path)
        explicit_path = True
    elif value.startswith("~/"):
        candidate_value = value
        explicit_path = True
    elif value.startswith(("./", "../", "/")):
        candidate_value = value
        explicit_path = True
    elif "/" in value or "\\" in value:
        candidate_value = value
    elif is_plain_filename(value):
        candidate_value = value

    if candidate_value is None:
        return None

    candidate = Path(candidate_value).expanduser()
    if not candidate.is_absolute():
        candidate = (base_dir / candidate).resolve()
    else:
        candidate = candidate.resolve()

    if not candidate.exists():
        if explicit_path:
            raise ReplicateError(f"Referenced local asset does not exist: {candidate}")
        return None
    if not candidate.is_file():
        if explicit_path:
            raise ReplicateError(f"Referenced local asset is not a file: {candidate}")
        return None
    return candidate


def content_type_for_path(path: Path) -> str:
    guessed, _ = mimetypes.guess_type(path.name)
    return guessed or "application/octet-stream"


def data_uri_for_path(path: Path) -> tuple[str, str]:
    content_type = content_type_for_path(path)
    encoded = base64.b64encode(path.read_bytes()).decode("ascii")
    return f"data:{content_type};base64,{encoded}", content_type


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


def upload_local_asset(path: Path, token: str) -> dict[str, Any]:
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
        raise ReplicateError(f"Replicate file upload did not return a usable URL for {path}")
    return response


def prepare_input_payload(
    payload: dict[str, Any],
    base_dir: Path,
    local_assets_mode: str,
    inline_max_bytes: int,
    token: str,
) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    if local_assets_mode == "off":
        return payload, []

    resolved_cache: dict[tuple[str, str], str] = {}
    asset_records: list[dict[str, Any]] = []

    def transform(value: Any, json_path: str) -> Any:
        if isinstance(value, dict):
            return {key: transform(item, f"{json_path}.{key}") for key, item in value.items()}
        if isinstance(value, list):
            return [transform(item, f"{json_path}[{index}]") for index, item in enumerate(value)]
        if not isinstance(value, str):
            return value

        asset_path = resolve_local_asset_path(value, base_dir)
        if asset_path is None:
            return value

        if local_assets_mode == "data-uri":
            mode = "data-uri"
        elif local_assets_mode == "auto":
            mode = "data-uri" if asset_path.stat().st_size <= inline_max_bytes else "upload"
        else:
            mode = "upload"

        cache_key = (mode, str(asset_path))
        if cache_key in resolved_cache:
            return resolved_cache[cache_key]

        content_type = content_type_for_path(asset_path)
        size = asset_path.stat().st_size
        if mode == "data-uri":
            resolved_value, _ = data_uri_for_path(asset_path)
            record: dict[str, Any] = {
                "json_path": json_path,
                "mode": mode,
                "source_path": str(asset_path),
                "content_type": content_type,
                "size": size,
            }
        else:
            upload_response = upload_local_asset(asset_path, token)
            urls = upload_response.get("urls") or {}
            resolved_value = urls.get("get")
            record = {
                "json_path": json_path,
                "mode": mode,
                "source_path": str(asset_path),
                "content_type": upload_response.get("content_type") or content_type,
                "size": upload_response.get("size") or size,
                "file_id": upload_response.get("id"),
                "file_url": resolved_value,
                "expires_at": upload_response.get("expires_at"),
            }

        if not isinstance(resolved_value, str) or not resolved_value:
            raise ReplicateError(f"Could not resolve local asset for input: {asset_path}")

        resolved_cache[cache_key] = resolved_value
        asset_records.append(record)
        return resolved_value

    return transform(payload, "$.input"), asset_records


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


def unique_path(path: Path) -> Path:
    if not path.exists():
        return path
    stem = path.stem
    suffix = path.suffix
    counter = 2
    while True:
        candidate = path.with_name(f"{stem}-{counter}{suffix}")
        if not candidate.exists():
            return candidate
        counter += 1


def iter_file_outputs(value: Any, path: str = "$.output") -> Iterator[tuple[str, str]]:
    if isinstance(value, str) and value.startswith(URL_PREFIXES):
        yield path, value
        return
    if isinstance(value, list):
        for index, item in enumerate(value):
            yield from iter_file_outputs(item, f"{path}[{index}]")
        return
    if isinstance(value, dict):
        for key, item in value.items():
            yield from iter_file_outputs(item, f"{path}.{key}")


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


def download_url(value: str) -> tuple[bytes, str]:
    if value.startswith("data:"):
        return download_data_url(value)

    request = Request(value, headers={"User-Agent": USER_AGENT})
    try:
        with urlopen(request) as response:
            data = response.read()
            content_type = response.headers.get_content_type()
    except HTTPError as exc:
        message = exc.read().decode("utf-8", "replace")
        raise ReplicateError(f"Downloading output failed with HTTP {exc.code}: {message}") from exc
    except URLError as exc:
        raise ReplicateError(f"Downloading output failed: {exc.reason}") from exc

    return data, content_type


def save_output_files(output: Any, files_dir: Path) -> list[dict[str, str]]:
    saved_files: list[dict[str, str]] = []
    files_dir.mkdir(parents=True, exist_ok=True)

    for index, (json_path, source) in enumerate(iter_file_outputs(output), start=1):
        payload, content_type = download_url(source)
        source_name = Path(urlparse(source).path).name if source.startswith(("http://", "https://")) else ""
        filename = sanitize_filename(source_name or f"output-{index:03d}")
        suffix = extension_for(content_type, source)
        target = unique_path(files_dir / f"{Path(filename).stem}{suffix}")
        target.write_bytes(payload)
        saved_files.append(
            {
                "json_path": json_path,
                "source": source,
                "path": str(target.resolve()),
                "content_type": content_type,
            }
        )

    return saved_files


def write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2) + "\n")


def main() -> int:
    args = parse_args()
    token = require_token(args.token_env)
    original_input_payload, input_base_dir = load_input_payload(args)
    input_payload, prepared_assets = prepare_input_payload(
        original_input_payload,
        input_base_dir,
        args.local_assets,
        args.inline_max_bytes,
        token,
    )

    version = args.version
    model_data: dict[str, Any] | None = None
    if not version:
        version, model_data = resolve_version(args.model, token)

    prediction = create_prediction(version, input_payload, token, args.wait, args.cancel_after)
    prediction = poll_prediction(prediction, token, args.poll_interval, args.max_polls)

    prediction_id = prediction.get("id") or "unknown-prediction"
    run_dir = Path(args.output_dir).expanduser().resolve() / str(prediction_id)
    run_dir.mkdir(parents=True, exist_ok=True)

    write_json(run_dir / "prediction.json", prediction)
    write_json(run_dir / "input.json", input_payload)
    if input_payload != original_input_payload:
        write_json(run_dir / "input.original.json", original_input_payload)
    write_json(run_dir / "output.json", prediction.get("output"))
    if model_data is not None:
        write_json(run_dir / "model.json", model_data)
    if prepared_assets:
        write_json(run_dir / "prepared-assets.json", prepared_assets)

    saved_files: list[dict[str, str]] = []
    if not args.no_download:
        saved_files = save_output_files(prediction.get("output"), run_dir / "files")
        write_json(run_dir / "saved-files.json", saved_files)

    summary = {
        "model": args.model,
        "version": version,
        "prediction_id": prediction.get("id"),
        "status": prediction.get("status"),
        "error": prediction.get("error"),
        "prediction_url": ((prediction.get("urls") or {}).get("web"))
        if isinstance(prediction.get("urls"), dict)
        else None,
        "output_dir": str(run_dir),
        "prepared_assets": prepared_assets,
        "saved_files": saved_files,
    }
    json.dump(summary, sys.stdout, indent=2)
    sys.stdout.write("\n")

    if prediction.get("status") in {"failed", "canceled"}:
        return 2
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except ReplicateError as exc:
        print(str(exc), file=sys.stderr)
        raise SystemExit(1)
