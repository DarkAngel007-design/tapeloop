"""Canonical JSON: one representation per value, or nothing downstream works.

Every property this project sells rests on two identical runs producing identical
bytes. That makes serialization load-bearing in a way it usually is not, and the
failure mode is nasty: a false cache miss looks exactly like "replay is broken",
with nothing to point at.

Four hazards, each handled explicitly. See docs/reference/transcript-format.md.
"""

from __future__ import annotations

import hashlib
import json
import unicodedata
from typing import Any, cast


class NonCanonical(ValueError):
    """A value that cannot be represented deterministically."""


def normalize(value: Any) -> Any:
    """Recursively NFC-normalize strings and reject values with no stable form.

    ``é`` can be one code point or two. Same string to a human, different bytes to
    a hash — so a model that emits one form and a tape that stored the other will
    never agree. NFC is the composed form and the web's default.
    """
    if isinstance(value, str):
        return unicodedata.normalize("NFC", value)
    if isinstance(value, bool) or value is None or isinstance(value, int):
        return value
    if isinstance(value, float):
        # NaN and Infinity are not JSON. Python emits them anyway by default,
        # producing a file no other parser will read.
        if value != value or value in (float("inf"), float("-inf")):
            raise NonCanonical(f"{value!r} has no JSON representation")
        return value
    if isinstance(value, dict):
        out: dict[str, Any] = {}
        for key, item in cast(dict[Any, Any], value).items():
            if not isinstance(key, str):
                raise NonCanonical(f"object keys must be strings, got {type(key).__name__}")
            out[unicodedata.normalize("NFC", key)] = normalize(item)
        return out
    if isinstance(value, list | tuple):
        sequence = cast("list[Any] | tuple[Any, ...]", value)
        return [normalize(item) for item in sequence]
    raise NonCanonical(f"{type(value).__name__} is not JSON-serializable")


def canonical_json(value: Any) -> str:
    """Serialize deterministically.

    ``sort_keys`` because dict insertion order is not semantic. Compact separators
    because incidental whitespace is a difference that means nothing. Non-ASCII
    stays literal so tapes remain greppable (ADR-0003).
    """
    return json.dumps(
        normalize(value),
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
        allow_nan=False,
    )


def digest(value: Any) -> str:
    """The content address of a value: sha256 over its canonical form."""
    return hashlib.sha256(canonical_json(value).encode("utf-8")).hexdigest()
