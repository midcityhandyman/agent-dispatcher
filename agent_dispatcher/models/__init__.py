"""Model access. Agents depend on the Model protocol only, never on a vendor SDK."""

from .base import Model, ModelRequest
from .mock import MockModel, MockScript

__all__ = ["Model", "ModelRequest", "MockModel", "MockScript"]
