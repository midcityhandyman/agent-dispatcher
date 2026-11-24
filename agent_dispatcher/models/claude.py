"""Claude implementation of the Model interface, through the official Anthropic SDK.

The SDK is imported lazily so the package, the tests and the demo work without it.
Install with:  pip install "agent-dispatcher[claude]"   (or: pip install anthropic)
"""

from __future__ import annotations

import os
from typing import Any

from ..errors import ModelError
from .base import ModelRequest

DEFAULT_MODEL = "claude-sonnet-5-5"
FALLBACK_BETA = "server-side-fallback-2026-07-01"


class ClaudeModel:
    """One stateless Messages API call per request.

    No thinking or sampling parameters are sent: current models run adaptive thinking
    when the field is omitted and reject non default sampling values. Depth is
    controlled with `effort` if you set it.
    """

    def __init__(
        self,
        model: str | None = None,
        *,
        client: Any | None = None,
        effort: str | None = None,
        fallbacks: str | None = None,
    ) -> None:
        self.model = model or os.environ.get("AGENT_DISPATCHER_MODEL") or DEFAULT_MODEL
        self.effort = effort if effort is not None else (os.environ.get("AGENT_DISPATCHER_EFFORT") or None)
        self.fallbacks = (
            fallbacks if fallbacks is not None else (os.environ.get("AGENT_DISPATCHER_FALLBACKS") or None)
        )
        self.name = self.model
        self._client = client

    def _get_client(self) -> Any:
        if self._client is None:
            try:
                import anthropic
            except ImportError as exc:  # pragma: no cover - depends on the environment
                raise ModelError(
                    "the anthropic package is not installed; run: pip install anthropic"
                ) from exc
            # Credentials are resolved by the SDK (ANTHROPIC_API_KEY and its other sources).
            self._client = anthropic.Anthropic()
        return self._client

    def _params(self, request: ModelRequest) -> dict:
        params: dict[str, Any] = {
            "model": self.model,
            "max_tokens": request.max_tokens,
            "system": request.system,
            "messages": [{"role": "user", "content": request.prompt}],
        }
        if self.effort:
            params["output_config"] = {"effort": self.effort}
        return params

    def complete(self, request: ModelRequest) -> str:
        client = self._get_client()
        params = self._params(request)
        try:
            if self.fallbacks:
                response = client.beta.messages.create(
                    betas=[FALLBACK_BETA], fallbacks=self.fallbacks, **params
                )
            else:
                response = client.messages.create(**params)
        except Exception as exc:
            raise ModelError(_describe(exc)) from exc

        stop_reason = getattr(response, "stop_reason", None)
        if stop_reason == "refusal":
            details = getattr(response, "stop_details", None)
            category = getattr(details, "category", None)
            raise ModelError(f"request refused by the model (category: {category})")
        if stop_reason == "max_tokens":
            raise ModelError("reply cut off at max_tokens; raise the limit or shrink the task")

        text = "".join(
            block.text for block in getattr(response, "content", []) if getattr(block, "type", "") == "text"
        )
        if not text.strip():
            raise ModelError("reply contained no text")
        return text


def _describe(exc: Exception) -> str:
    """Name the failure class without depending on the SDK being importable."""
    try:
        import anthropic
    except ImportError:
        return f"{type(exc).__name__}: {exc}"
    if isinstance(exc, anthropic.AuthenticationError):
        return "authentication failed; check ANTHROPIC_API_KEY"
    if isinstance(exc, anthropic.NotFoundError):
        return f"model or endpoint not found: {exc}"
    if isinstance(exc, anthropic.RateLimitError):
        return "rate limited after the SDK's retries"
    if isinstance(exc, anthropic.APIStatusError):
        return f"API error {exc.status_code}: {exc}"
    if isinstance(exc, anthropic.APIConnectionError):
        return f"could not reach the API: {exc}"
    return f"{type(exc).__name__}: {exc}"
