"""Counting tokens, and being honest about how (ADR-0019).

The number itself matters less than knowing what kind of number it is. A budget
decision made on an estimate and one made on an exact count are different decisions,
and downstream code must be able to tell them apart.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from functools import lru_cache
from typing import Any, Protocol, cast


class Method(StrEnum):
    EXACT = "exact"
    """tiktoken, with an encoding it actually knows for this model."""

    APPROXIMATE = "approximate"
    """tiktoken, falling back to a default encoding for an unknown model."""

    ESTIMATED = "estimated"
    """No tiktoken. Calibrated character heuristic; error band asserted by a test."""


@dataclass(frozen=True, slots=True)
class TokenCount:
    tokens: int
    method: Method

    @property
    def trustworthy(self) -> bool:
        return self.method is not Method.ESTIMATED

    def __int__(self) -> int:
        return self.tokens


# Calibrated against the M6 baseline: 105 real runs of gpt-5.4-mini, comparing
# rendered-payload characters to the provider's own reported input_tokens.
# tests/test_context.py asserts this stays inside its band; when it drifts the
# test fails, which is what separates an estimate from a guess.
CHARS_PER_TOKEN = 3.6


class Encoder(Protocol):
    """The one method we need from tiktoken. Typed here so the optional import
    does not leak `Unknown` through the rest of the package."""

    def encode(self, text: str, /) -> list[int]: ...


@lru_cache(maxsize=8)
def _encoding(model: str) -> tuple[Encoder | None, bool]:
    """(encoder, knows_this_model). Cached: building an encoder is not cheap."""
    try:
        import tiktoken  # pyright: ignore[reportMissingImports]
    except ImportError:
        return None, False

    # tiktoken ships no stubs, so everything it returns is Unknown. Contain that
    # here by taking the two functions as Any once, rather than at each use.
    for_model = cast(Any, tiktoken).encoding_for_model
    by_name = cast(Any, tiktoken).get_encoding
    try:
        return cast(Encoder, for_model(model)), True
    except Exception:
        try:
            return cast(Encoder, by_name("o200k_base")), False
        except Exception:
            return None, False


def count_text(text: str, *, model: str = "") -> TokenCount:
    encoder, known = _encoding(model)
    if encoder is not None:
        return TokenCount(len(encoder.encode(text)), Method.EXACT if known else Method.APPROXIMATE)
    return TokenCount(max(1, round(len(text) / CHARS_PER_TOKEN)), Method.ESTIMATED)
