"""Exception types. Everything the dispatcher expects to handle derives from DispatchError."""


class DispatchError(Exception):
    pass


class ModelError(DispatchError):
    """The model call failed, was refused, or was cut off."""


class ParseError(DispatchError):
    """A model reply did not contain the JSON object the role contract asks for."""


class PlanError(DispatchError):
    """The lead produced a plan the dispatcher will not run."""


class AgentError(DispatchError):
    """A worker could not produce a usable result for this attempt."""
