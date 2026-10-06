"""Error raised when overlapping session invocations are detected."""


class ConcurrentSessionInvocationError(RuntimeError):
    """A second invocation attempted to mutate the active session goal."""
