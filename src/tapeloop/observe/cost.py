"""Turning tokens into money.

Prices change and models are added constantly, so nothing here is baked into code
paths. A price table is data, loaded from `prices.toml` if present, and a missing
entry produces `None` rather than a guess — a cost figure that is quietly wrong is
worse than one that is visibly absent.
"""

from __future__ import annotations

import tomllib
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, cast


@dataclass(frozen=True, slots=True)
class Price:
    """USD per million tokens."""

    input_per_m: float
    output_per_m: float
    cached_input_per_m: float | None = None


@dataclass(frozen=True, slots=True)
class Cost:
    usd: float | None
    priced: bool
    """False when the model has no entry. Callers must render that as unknown, not zero."""

    def __str__(self) -> str:
        """Significant digits rather than fixed decimals.

        A cheap run costs $0.000444 and a fixed four-decimal format renders that as
        $0.0004 — which collapses exactly the differences you compare runs on.
        """
        if not self.priced or self.usd is None:
            return "—"
        if self.usd >= 0.01:
            return f"${self.usd:,.2f}"
        return f"${self.usd:.3g}"


@dataclass(slots=True)
class PriceTable:
    prices: dict[str, Price] = field(default_factory=dict[str, Price])

    @classmethod
    def load(cls, path: Path | None = None) -> PriceTable:
        target = path or Path("prices.toml")
        if not target.exists():
            return cls()
        raw = tomllib.loads(target.read_text(encoding="utf-8"))
        prices: dict[str, Price] = {}
        for model, value in raw.items():
            if not isinstance(value, dict):
                continue
            entry = cast(dict[str, Any], value)
            cached = entry.get("cached_input")
            prices[model] = Price(
                input_per_m=float(entry["input"]),
                output_per_m=float(entry["output"]),
                cached_input_per_m=float(cached) if cached is not None else None,
            )
        return cls(prices=prices)

    def cost(self, model: str, *, input_tokens: int, output_tokens: int, cached: int = 0) -> Cost:
        price = self.prices.get(model)
        if price is None:
            return Cost(usd=None, priced=False)
        fresh_input = max(0, input_tokens - cached)
        cached_rate = (
            price.cached_input_per_m if price.cached_input_per_m is not None else price.input_per_m
        )
        total = (
            fresh_input * price.input_per_m
            + cached * cached_rate
            + output_tokens * price.output_per_m
        ) / 1_000_000
        return Cost(usd=total, priced=True)
