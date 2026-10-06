"""Error raised when provider evidence exceeds a governed limit."""


class CapabilityEvidenceLimitExceededError(ValueError):
    """Indicate that complete provider evidence cannot be exposed safely."""
