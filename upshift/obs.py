"""neatlogs instrumentation.

Everything degrades gracefully: if neatlogs is missing or unconfigured the
agent still runs, it just produces no traces.
"""
from __future__ import annotations

import contextlib
import functools
from typing import Any, Callable

from .config import CONFIG

_ENABLED = False

try:
    import neatlogs as _neatlogs
except ImportError:
    _neatlogs = None


def init(workflow_name: str = "upshift", tags: list[str] | None = None) -> bool:
    global _ENABLED
    if _neatlogs is None or not CONFIG.neatlogs_api_key:
        return False
    _neatlogs.init(
        api_key=CONFIG.neatlogs_api_key,
        endpoint=CONFIG.neatlogs_endpoint,
        workflow_name=workflow_name,
        tags=tags or [],
    )
    _ENABLED = True
    return True


def flush() -> None:
    if _ENABLED and _neatlogs is not None:
        _neatlogs.flush()
        _neatlogs.shutdown()


def span(kind: str = "TOOL", **span_kwargs: Any) -> Callable:
    """Decorator that becomes a no-op when neatlogs is unavailable."""
    def decorator(fn: Callable) -> Callable:
        @functools.wraps(fn)
        def wrapper(*args, **kwargs):
            if not _ENABLED or _neatlogs is None:
                return fn(*args, **kwargs)
            return _neatlogs.span(kind=kind, **span_kwargs)(fn)(*args, **kwargs)
        return wrapper
    return decorator


@contextlib.contextmanager
def trace(name: str, kind: str = "CHAIN", **attrs: Any):
    if not _ENABLED or _neatlogs is None:
        yield None
        return
    with _neatlogs.trace(name, kind=kind) as sp:
        for key, value in attrs.items():
            with contextlib.suppress(Exception):
                sp.set_attribute(f"upshift.{key}", value)
        yield sp
