"""LLM provider adapters with a deliberately small common interface."""

from __future__ import annotations

import json
import time
import urllib.error
import urllib.request
from dataclasses import dataclass
from typing import Any, Protocol


@dataclass(frozen=True)
class ProviderResult:
    text: str
    duration_seconds: float
    metadata: dict[str, Any]


class ClaimProvider(Protocol):
    backend: str
    model: str

    def generate(
        self,
        *,
        system_prompt: str,
        user_prompt: str,
        response_schema: dict[str, Any],
        temperature: float,
    ) -> ProviderResult: ...

    def describe(self) -> dict[str, Any]: ...


class OllamaProvider:
    backend = "ollama"

    def __init__(
        self,
        model: str,
        *,
        base_url: str = "http://127.0.0.1:11434",
        timeout_seconds: float = 900,
        context_length: int = 16384,
        seed: int = 17,
    ) -> None:
        self.model = model
        self.base_url = base_url.rstrip("/")
        self.timeout_seconds = timeout_seconds
        self.context_length = context_length
        self.seed = seed

    def generate(
        self,
        *,
        system_prompt: str,
        user_prompt: str,
        response_schema: dict[str, Any],
        temperature: float,
    ) -> ProviderResult:
        request_body = {
            "model": self.model,
            "messages": [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt},
            ],
            "stream": False,
            "format": response_schema,
            "think": False,
            "options": {
                "temperature": temperature,
                "seed": self.seed,
                "num_ctx": self.context_length,
            },
            "keep_alive": "30m",
        }
        request = urllib.request.Request(
            f"{self.base_url}/api/chat",
            data=json.dumps(request_body).encode("utf-8"),
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        started = time.monotonic()
        try:
            with urllib.request.urlopen(request, timeout=self.timeout_seconds) as response:
                payload = json.load(response)
        except urllib.error.HTTPError as exc:
            details = exc.read().decode("utf-8", errors="replace")
            raise RuntimeError(f"Ollama returned HTTP {exc.code}: {details}") from exc
        except urllib.error.URLError as exc:
            raise RuntimeError(f"Cannot reach Ollama at {self.base_url}: {exc.reason}") from exc
        duration = time.monotonic() - started
        content = payload.get("message", {}).get("content")
        if not isinstance(content, str):
            raise RuntimeError(f"Ollama response did not contain message.content: {payload}")
        metadata = {
            key: payload.get(key)
            for key in (
                "created_at",
                "done_reason",
                "total_duration",
                "load_duration",
                "prompt_eval_count",
                "prompt_eval_duration",
                "eval_count",
                "eval_duration",
            )
            if key in payload
        }
        return ProviderResult(text=content, duration_seconds=duration, metadata=metadata)

    def describe(self) -> dict[str, Any]:
        tags = self._request_json("GET", "/api/tags")
        selected = next(
            (
                item
                for item in tags.get("models", [])
                if item.get("name") == self.model or item.get("model") == self.model
            ),
            {},
        )
        shown = self._request_json("POST", "/api/show", {"model": self.model})
        return {
            "backend": self.backend,
            "model": self.model,
            "digest": selected.get("digest"),
            "size_bytes": selected.get("size"),
            "modified_at": selected.get("modified_at") or shown.get("modified_at"),
            "details": shown.get("details") or selected.get("details"),
            "capabilities": shown.get("capabilities"),
        }

    def _request_json(self, method: str, path: str, body: dict[str, Any] | None = None) -> dict[str, Any]:
        request = urllib.request.Request(
            f"{self.base_url}{path}",
            data=json.dumps(body).encode("utf-8") if body is not None else None,
            headers={"Content-Type": "application/json"},
            method=method,
        )
        try:
            with urllib.request.urlopen(request, timeout=self.timeout_seconds) as response:
                return json.load(response)
        except urllib.error.HTTPError as exc:
            details = exc.read().decode("utf-8", errors="replace")
            raise RuntimeError(f"Ollama returned HTTP {exc.code}: {details}") from exc
        except urllib.error.URLError as exc:
            raise RuntimeError(f"Cannot reach Ollama at {self.base_url}: {exc.reason}") from exc


class OpenAIProvider:
    backend = "openai"

    def __init__(self, model: str, *, timeout_seconds: float = 900) -> None:
        try:
            from openai import OpenAI
        except ImportError as exc:
            raise RuntimeError("Install the project with the 'openai' extra to use this backend") from exc
        self.model = model
        self.client = OpenAI(timeout=timeout_seconds)

    def generate(
        self,
        *,
        system_prompt: str,
        user_prompt: str,
        response_schema: dict[str, Any],
        temperature: float,
    ) -> ProviderResult:
        started = time.monotonic()
        response = self.client.responses.create(
            model=self.model,
            instructions=system_prompt,
            input=user_prompt,
            text={
                "format": {
                    "type": "json_schema",
                    "name": "historical_claim_candidates",
                    "schema": response_schema,
                    "strict": True,
                }
            },
            store=False,
        )
        duration = time.monotonic() - started
        return ProviderResult(
            text=response.output_text,
            duration_seconds=duration,
            metadata={"response_id": response.id, "usage": _to_plain_dict(response.usage)},
        )

    def describe(self) -> dict[str, Any]:
        return {"backend": self.backend, "model": self.model, "digest": None}


def _to_plain_dict(value: Any) -> Any:
    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    if isinstance(value, dict):
        return {str(key): _to_plain_dict(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_to_plain_dict(item) for item in value]
    if hasattr(value, "model_dump"):
        return value.model_dump()
    return str(value)


class ReplayProvider:
    """Deterministic provider used by tests and offline pipeline demonstrations."""

    backend = "rules"
    model = "fixture-replay"

    def __init__(self, responses: list[dict[str, Any] | str]) -> None:
        self.responses = list(responses)
        self.calls = 0

    def generate(
        self,
        *,
        system_prompt: str,
        user_prompt: str,
        response_schema: dict[str, Any],
        temperature: float,
    ) -> ProviderResult:
        if self.calls >= len(self.responses):
            raise RuntimeError("ReplayProvider has no response left")
        response = self.responses[self.calls]
        self.calls += 1
        text = response if isinstance(response, str) else json.dumps(response, ensure_ascii=False)
        return ProviderResult(text=text, duration_seconds=0.0, metadata={"fixture_index": self.calls - 1})

    def describe(self) -> dict[str, Any]:
        return {"backend": self.backend, "model": self.model, "digest": "test-fixture"}
