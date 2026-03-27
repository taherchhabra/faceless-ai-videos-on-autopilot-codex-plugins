#!/usr/bin/env python3
"""Search public Replicate models for a user task."""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen


API_BASE = "https://api.replicate.com/v1"
USER_AGENT = "replicate-model-runner/0.1.0"
PLUGIN_ROOT = Path(__file__).resolve().parent.parent
LOCAL_ENV_FILES = (PLUGIN_ROOT / ".env.local",)


class ReplicateSearchError(RuntimeError):
    """Raised for Replicate search failures."""


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Search Replicate models for a user task or prompt."
    )
    parser.add_argument("query", help="Search query, such as 'fast image generation with text'.")
    parser.add_argument(
        "--limit",
        type=int,
        default=10,
        help="Maximum number of model results to return (1-50).",
    )
    parser.add_argument(
        "--include-collections",
        action="store_true",
        help="Also print matching Replicate collections.",
    )
    parser.add_argument(
        "--json",
        action="store_true",
        help="Print the raw search payload as JSON.",
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
    raise ReplicateSearchError(
        f"Missing {env_name}. Export it or store it in one of: {searched}"
    )


def api_get(url: str, token: str) -> dict[str, Any]:
    request = Request(
        url,
        headers={
            "Authorization": f"Bearer {token}",
            "User-Agent": USER_AGENT,
        },
    )
    try:
        with urlopen(request) as response:
            raw = response.read().decode("utf-8")
    except HTTPError as exc:
        message = exc.read().decode("utf-8", "replace")
        raise ReplicateSearchError(f"GET {url} failed with HTTP {exc.code}: {message}") from exc
    except URLError as exc:
        raise ReplicateSearchError(f"GET {url} failed: {exc.reason}") from exc

    try:
        payload = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise ReplicateSearchError(f"GET {url} returned non-JSON output.") from exc

    if not isinstance(payload, dict):
        raise ReplicateSearchError(f"GET {url} returned an unexpected response shape.")
    return payload


def search_models(query: str, limit: int, token: str) -> dict[str, Any]:
    bounded_limit = max(1, min(limit, 50))
    params = urlencode({"query": query, "limit": bounded_limit})
    return api_get(f"{API_BASE}/search?{params}", token)


def normalize_model_result(entry: Any) -> dict[str, Any] | None:
    if not isinstance(entry, dict):
        return None

    model = entry.get("model") if isinstance(entry.get("model"), dict) else entry
    metadata = entry.get("metadata") if isinstance(entry.get("metadata"), dict) else {}
    if not isinstance(model, dict):
        return None

    owner = model.get("owner")
    name = model.get("name")
    if not owner or not name:
        return None

    return {
        "slug": f"{owner}/{name}",
        "owner": owner,
        "name": name,
        "description": model.get("description") or metadata.get("generated_description") or "",
        "generated_description": metadata.get("generated_description") or "",
        "url": model.get("url") or f"https://replicate.com/{owner}/{name}",
        "run_count": model.get("run_count"),
        "score": metadata.get("score"),
        "tags": metadata.get("tags") or [],
        "visibility": model.get("visibility"),
    }


def print_text_summary(payload: dict[str, Any], include_collections: bool) -> None:
    models = [
        normalized
        for entry in payload.get("models", [])
        if (normalized := normalize_model_result(entry)) is not None
    ]

    print(f"Query: {payload.get('query', '')}")
    print()

    if not models:
        print("No model results.")
    else:
        print("Models:")
        for index, model in enumerate(models, start=1):
            parts: list[str] = []
            score = model.get("score")
            if isinstance(score, (int, float)):
                parts.append(f"score {score:.3f}")
            run_count = model.get("run_count")
            if isinstance(run_count, int):
                parts.append(f"runs {run_count}")
            tags = model.get("tags") or []
            if tags:
                parts.append("tags " + ", ".join(str(tag) for tag in tags[:5]))

            print(f"{index}. {model['slug']}")
            if parts:
                print(f"   {' | '.join(parts)}")
            description = model.get("description") or ""
            if description:
                print(f"   {description}")
            print(f"   {model['url']}")

    if include_collections:
        collections = payload.get("collections", [])
        print()
        if not collections:
            print("Collections: none")
        else:
            print("Collections:")
            for index, collection in enumerate(collections, start=1):
                if not isinstance(collection, dict):
                    continue
                name = collection.get("name") or collection.get("slug") or "unknown"
                slug = collection.get("slug") or ""
                description = collection.get("description") or ""
                print(f"{index}. {name}")
                if slug:
                    print(f"   https://replicate.com/collections/{slug}")
                if description:
                    print(f"   {description}")


def main() -> int:
    args = parse_args()
    token = require_token(args.token_env)
    payload = search_models(args.query, args.limit, token)

    if args.json:
        json.dump(payload, sys.stdout, indent=2)
        sys.stdout.write("\n")
        return 0

    print_text_summary(payload, args.include_collections)
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except ReplicateSearchError as exc:
        print(str(exc), file=sys.stderr)
        raise SystemExit(1)
