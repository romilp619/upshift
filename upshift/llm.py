"""Claude client with token/cost accounting.

Pricing is per 1M tokens, Anthropic first-party rates.
"""
from __future__ import annotations

from dataclasses import dataclass

import anthropic

from .config import CONFIG

PRICING = {
    "claude-opus-5-5":   (4.00, 20.00),
    "claude-opus-5":     (5.00, 25.00),
    "claude-sonnet-5-5": (2.00, 10.00),
    "claude-haiku-5-5":  (0.10, 0.50),
}
CACHE_READ_DISCOUNT = 0.05   # cache reads bill at $0.20/MTok on opus-5-5
CACHE_WRITE_MULTIPLIER = 1.25


@dataclass
class LLMResult:
    text: str
    input_tokens: int = 0
    output_tokens: int = 0
    cache_read_tokens: int = 0
    cache_write_tokens: int = 0
    cost_usd: float = 0.0
    stop_reason: str = ""


class Claude:
    def __init__(self, model: str | None = None):
        self.model = model or CONFIG.model
        self.client = anthropic.Anthropic(api_key=CONFIG.anthropic_api_key or None)

    def _price(self, usage) -> float:
        inp, out = PRICING.get(self.model, PRICING["claude-opus-5-5"])
        fresh = getattr(usage, "input_tokens", 0) or 0
        cread = getattr(usage, "cache_read_input_tokens", 0) or 0
        cwrite = getattr(usage, "cache_creation_input_tokens", 0) or 0
        output = getattr(usage, "output_tokens", 0) or 0
        return round(
            (fresh * inp
             + cread * inp * CACHE_READ_DISCOUNT
             + cwrite * inp * CACHE_WRITE_MULTIPLIER
             + output * out) / 1_000_000,
            6,
        )

    def ask(
        self,
        system: str,
        user: str,
        effort: str = "high",
        max_tokens: int = 32000,
        cache_system: bool = True,
    ) -> LLMResult:
        """One streamed request. Streaming avoids HTTP timeouts on big files.

        The system prompt is cached: it is identical for every file in a run,
        so files 2..N read it from cache instead of paying for it again.
        """
        system_blocks = [{"type": "text", "text": system}]
        if cache_system:
            system_blocks[0]["cache_control"] = {"type": "ephemeral"}

        with self.client.messages.stream(
            model=self.model,
            max_tokens=max_tokens,
            system=system_blocks,
            thinking={"type": "adaptive"},
            output_config={"effort": effort},
            messages=[{"role": "user", "content": user}],
        ) as stream:
            message = stream.get_final_message()

        text = "".join(b.text for b in message.content if b.type == "text")
        usage = message.usage
        return LLMResult(
            text=text,
            input_tokens=getattr(usage, "input_tokens", 0) or 0,
            output_tokens=getattr(usage, "output_tokens", 0) or 0,
            cache_read_tokens=getattr(usage, "cache_read_input_tokens", 0) or 0,
            cache_write_tokens=getattr(usage, "cache_creation_input_tokens", 0) or 0,
            cost_usd=self._price(usage),
            stop_reason=message.stop_reason or "",
        )
