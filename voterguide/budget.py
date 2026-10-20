"""Monthly API spend cap. State lives in state/budget.json, keyed by calendar month (UTC)."""
from __future__ import annotations

import threading
from datetime import datetime, timezone

# $ per 1M tokens (input, output). Haiku 5.5 is priced for prompts up to 100K tokens.
PRICES = {
    "claude-opus-5-5": (4.00, 20.00),
    "claude-sonnet-5-5": (2.00, 10.00),
    "claude-haiku-5-5": (0.10, 0.50),
    "claude-fable-5-1": (10.00, 50.00),
}
DEFAULT_CAP = 20.00
ASSUMED_OUTPUT_TOKENS = 4000


def cost(model: str, tokens_in: int, tokens_out: int) -> float:
    pin, pout = PRICES.get(model, PRICES["claude-opus-5-5"])   # unknown model: price as Opus (conservative)
    return tokens_in / 1e6 * pin + tokens_out / 1e6 * pout


class Budget:
    def __init__(self, state: dict | None = None, cap: float = DEFAULT_CAP, now: datetime | None = None):
        now = now or datetime.now(timezone.utc)
        self.month = now.strftime("%Y-%m")
        self.cap = cap
        state = state or {}
        if state.get("month") == self.month:
            self.spent = float(state.get("spent_usd", 0.0))
            self.calls = int(state.get("calls", 0))
            self.alerted = bool(state.get("alerted", False))
        else:   # new month: counter resets
            self.spent, self.calls, self.alerted = 0.0, 0, False
        self._lock = threading.Lock()

    def estimate(self, model: str, input_tokens: int) -> float:
        return cost(model, input_tokens, ASSUMED_OUTPUT_TOKENS)

    def allow(self, model: str, input_tokens: int) -> bool:
        """True if one more call of about this size fits under the cap."""
        with self._lock:
            return self.spent + self.estimate(model, input_tokens) <= self.cap

    def charge(self, model: str, tokens_in: int, tokens_out: int) -> float:
        c = cost(model, tokens_in, tokens_out)
        with self._lock:
            self.spent += c
            self.calls += 1
        return c

    @property
    def remaining(self) -> float:
        return max(0.0, self.cap - self.spent)

    def to_state(self) -> dict:
        return {"month": self.month, "spent_usd": round(self.spent, 4), "calls": self.calls,
                "cap_usd": self.cap, "alerted": self.alerted}
