"""The one interface every agent talks to."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol, runtime_checkable


@dataclass(frozen=True)
class ModelRequest:
    """A single stateless call. There is no conversation handle on purpose:
    an agent cannot carry context from one call to the next through the model."""

    role: str  # "lead" | "worker" | "verifier"
    system: str
    prompt: str
    max_tokens: int = 16000


@runtime_checkable
class Model(Protocol):
    name: str

    def complete(self, request: ModelRequest) -> str:
        """Return the model's text reply, or raise ModelError."""
        ...
