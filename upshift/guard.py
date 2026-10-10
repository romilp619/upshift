"""Lazy-fix guard.

A migration that deletes the test, skips it, or guts an assertion will make
the suite green while destroying the thing the suite was for. The verifier
rejects those patches before they are ever counted as a success.
"""
from __future__ import annotations

import re

_SKIP_MARKERS = (
    "@pytest.mark.skip",
    "@pytest.mark.xfail",
    "pytest.skip(",
    "unittest.skip",
    "@unittest.skip",
)


def _count(pattern: str, text: str) -> int:
    return len(re.findall(pattern, text))


def check(original: str, migrated: str) -> tuple[bool, str]:
    """Return (ok, reason). ok=False means reject the patch."""
    if not migrated.strip():
        return False, "patch emptied the file"

    # Added a skip/xfail that was not there before
    for marker in _SKIP_MARKERS:
        if migrated.count(marker) > original.count(marker):
            return False, f"patch introduced {marker}"

    # Dropped assertions
    before_asserts = _count(r"\bassert\b", original)
    after_asserts = _count(r"\bassert\b", migrated)
    if after_asserts < before_asserts:
        return False, f"patch dropped assertions ({before_asserts} -> {after_asserts})"

    # Dropped test or model definitions
    before_defs = _count(r"^\s*(def|class)\s+\w+", original)
    after_defs = _count(r"^\s*(def|class)\s+\w+", migrated)
    if after_defs < before_defs:
        return False, f"patch removed definitions ({before_defs} -> {after_defs})"

    # Gutted the file
    if len(migrated) < len(original) * 0.5:
        return False, "patch removed more than half the file"

    return True, ""
