"""A cooperative boundary between serialized archive work and provider I/O."""

from dataclasses import dataclass


@dataclass(frozen=True)
class ProviderStep:
    stream: object
    flush_pending: bool = False


@dataclass(frozen=True)
class ProviderFlush:
    """Timer tick, not a model event; never archive this marker."""


def next_provider(stream):
    """Never propagate StopIteration through an executor Future."""
    try:
        return True, next(stream)
    except StopIteration:
        return False, None
