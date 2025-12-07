#!/usr/bin/env python3
"""Minimal CLI wrapper to run Perplexity web search via OpenRouter.

Usage:
    python scripts/perplexity_search.py "Latest research on ultra high-res tiling"

The script takes a single positional argument (the search prompt). Multiline prompts
can be passed with quotes or heredocs in your shell. Results are printed to stdout.
"""
from __future__ import annotations

import argparse
import os
import sys
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, List, Mapping, Optional

import requests


MODEL = "perplexity/sonar"  # Cheapest Perplexity model; matches chat_research_tool.py
CONTEXT_SIZE = "medium"
MAX_SEARCH_RESULTS = 20
TIMEOUT_SECONDS = 120


@dataclass
class Citation:
    title: Optional[str]
    url: Optional[str]
    snippet: Optional[str]

    def as_line(self) -> str:
        title = self.title or "(no title)"
        if self.snippet:
            return f"- {title} — {self.url} | {self.snippet}"
        return f"- {title} — {self.url}"


class PerplexitySearchError(RuntimeError):
    """Raised when the Perplexity search call fails."""


def _load_env() -> None:
    """Load a local .env (without extra deps) if present."""

    def _load_env_file(env_path: Path) -> None:
        if not env_path.is_file():
            return
        for raw_line in env_path.read_text().splitlines():
            line = raw_line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, value = line.split("=", 1)
            key = key.strip()
            value = value.strip().strip('"').strip("'")
            if key and key not in os.environ:
                os.environ[key] = value

    # Prefer repo root .env (scripts/../.env), fall back to CWD.
    script_root = Path(__file__).resolve().parent
    repo_root_env = script_root.parent / ".env"
    cwd_env = Path.cwd() / ".env"
    _load_env_file(repo_root_env)
    if cwd_env != repo_root_env:
        _load_env_file(cwd_env)


def _resolve_endpoint() -> str:
    """Return the OpenRouter endpoint honoring optional overrides."""

    base_url = os.getenv("OPENROUTER_BASE_URL")
    if base_url:
        base_url = base_url.rstrip("/")
        if not base_url.endswith("/chat/completions"):
            base_url = f"{base_url}/chat/completions"
        return base_url
    return "https://openrouter.ai/api/v1/chat/completions"


def _normalise_message_content(content: Any) -> str:
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        parts: List[str] = []
        for item in content:
            if isinstance(item, str):
                parts.append(item)
            elif isinstance(item, Mapping):
                text_value = item.get("text")
                if isinstance(text_value, str):
                    parts.append(text_value)
                elif text_value is not None:
                    parts.append(str(text_value))
            elif item is not None:
                parts.append(str(item))
        return " ".join(part for part in parts if part).strip()
    if content is None:
        return ""
    return str(content)


def _extract_citations(
    response_data: Mapping[str, Any],
    message: Mapping[str, Any],
) -> List[Citation]:
    """Return citations from Perplexity payload (search_results or annotations)."""

    seen: Dict[str, Citation] = {}

    def _append(url: Optional[str], title: Optional[str], snippet: Optional[str]) -> None:
        if not url or url in seen:
            return
        seen[url] = Citation(title=title, url=url, snippet=snippet)

    search_results = response_data.get("search_results")
    if isinstance(search_results, list) and search_results:
        for result in search_results:
            if isinstance(result, Mapping):
                url = result.get("url")
                title = result.get("title")
                snippet = result.get("snippet")
                if url and (title or snippet):
                    _append(url, title, snippet)

    if seen:
        return list(seen.values())

    annotations = message.get("annotations")
    annotation_lookup: Dict[str, Dict[str, Optional[str]]] = {}
    if isinstance(annotations, list):
        for annotation in annotations:
            if not isinstance(annotation, Mapping):
                continue
            source = annotation.get("url_citation")
            if isinstance(source, Mapping):
                url = source.get("url")
                if url:
                    annotation_lookup[url] = {
                        "title": source.get("title"),
                        "snippet": source.get("snippet"),
                    }
            else:
                url = annotation.get("url")
                if url:
                    annotation_lookup[url] = {
                        "title": annotation.get("title"),
                        "snippet": annotation.get("snippet"),
                    }

    legacy_citations = response_data.get("citations")
    if isinstance(legacy_citations, list):
        for entry in legacy_citations:
            if isinstance(entry, str):
                meta = annotation_lookup.get(entry, {})
                _append(entry, meta.get("title"), meta.get("snippet"))
            elif isinstance(entry, Mapping):
                _append(entry.get("url"), entry.get("title"), entry.get("snippet"))

    if not seen and annotation_lookup:
        for url, meta in annotation_lookup.items():
            _append(url, meta.get("title"), meta.get("snippet"))

    return list(seen.values())


def perform_search(query: str) -> Dict[str, Any]:
    """Execute the fixed Perplexity search call and return structured data."""

    if not query.strip():
        raise PerplexitySearchError("A non-empty query is required.")

    _load_env()

    api_key = os.getenv("OPENROUTER_API_KEY")
    if not api_key:
        raise PerplexitySearchError("OPENROUTER_API_KEY environment variable must be set.")

    payload: Dict[str, Any] = {
        "model": MODEL,
        "messages": [
            {
                "role": "user",
                "content": query.strip(),
            }
        ],
        "web_search_options": {
            "search_context_size": CONTEXT_SIZE,
            "max_search_results": MAX_SEARCH_RESULTS,
        },
    }

    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
        "Accept": "application/json",
        "X-Title": "ultra-resolution-quads-perplexity-cli",
    }

    endpoint = _resolve_endpoint()
    start = time.perf_counter()

    try:
        response = requests.post(endpoint, headers=headers, json=payload, timeout=TIMEOUT_SECONDS)
    except requests.RequestException as exc:
        raise PerplexitySearchError(f"Failed to reach OpenRouter: {exc}") from exc

    try:
        response.raise_for_status()
    except requests.HTTPError as exc:
        raise PerplexitySearchError(
            f"OpenRouter returned HTTP {response.status_code}: {response.text}"
        ) from exc

    try:
        data = response.json()
    except ValueError as exc:
        raise PerplexitySearchError("OpenRouter returned invalid JSON payload.") from exc

    error_block = data.get("error")
    if error_block:
        if isinstance(error_block, Mapping):
            message = error_block.get("message") or str(error_block)
        else:
            message = str(error_block)
        raise PerplexitySearchError(f"OpenRouter error: {message}")

    choices = data.get("choices")
    if not isinstance(choices, list) or not choices:
        raise PerplexitySearchError("OpenRouter returned no choices for the query.")

    message = choices[0].get("message") or {}
    content = _normalise_message_content(message.get("content"))
    citations = _extract_citations(data, message)
    duration_ms = (time.perf_counter() - start) * 1000.0

    usage = data.get("usage")
    if not isinstance(usage, Mapping):
        usage = {}

    return {
        "content": content,
        "citations": citations,
        "usage": dict(usage),
        "duration_ms": duration_ms,
    }


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Run a Perplexity Sonar web search via OpenRouter (no UI)."
    )
    parser.add_argument(
        "query",
        help="Prompt or search specification (use shell quotes/heredoc for multiline).",
    )
    return parser.parse_args()


def main() -> int:
    args = _parse_args()
    try:
        result = perform_search(args.query)
    except PerplexitySearchError as exc:
        sys.stderr.write(f"perplexity_search error: {exc}\n")
        return 1

    content = result["content"]
    citations: List[Citation] = result["citations"]
    usage: Dict[str, Any] = result["usage"]
    duration_ms: float = result["duration_ms"]

    print(f"[perplexity] model={MODEL} context={CONTEXT_SIZE} results={MAX_SEARCH_RESULTS}")
    print(f"[perplexity] duration={duration_ms:.1f}ms")
    if usage:
        prompt_tokens = usage.get("prompt_tokens")
        completion_tokens = usage.get("completion_tokens")
        total_tokens = usage.get("total_tokens")
        parts = []
        if prompt_tokens is not None:
            parts.append(f"prompt_tokens={prompt_tokens}")
        if completion_tokens is not None:
            parts.append(f"completion_tokens={completion_tokens}")
        if total_tokens is not None:
            parts.append(f"total_tokens={total_tokens}")
        if parts:
            print(f"[perplexity] usage: " + " ".join(parts))

    print("\n=== Result ===\n")
    print(content.strip())

    if citations:
        print("\n=== Citations ===\n")
        for citation in citations:
            print(citation.as_line())

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
