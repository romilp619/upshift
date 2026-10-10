"""Claude client with token/cost accounting.

Pricing is per 1M tokens, Anthropic first-party rates.
"""
from __future__ import annotations

from dataclasses import dataclass

import anthropic

from .config import CONFIG

# USD per 1M tokens (input, output). First-party Anthropic rates, plus the
# Token Harbor gateway catalogue -- note its Claude rates match first-party,
# so routing Claude through the gateway saves nothing.
PRICING = {
    "claude-opus-5-5":   (4.00, 20.00),
    "claude-opus-5":     (5.00, 25.00),
    "claude-sonnet-5-5": (2.00, 10.00),
    "claude-haiku-5-5":  (0.10, 0.50),
    # Token Harbor gateway (prefix "tokenharbor/")
    "tokenharbor/claude-opus-5.5":   (4.00, 20.00),
    "tokenharbor/claude-sonnet-5.5": (2.00, 10.00),
    "tokenharbor/muse-spark-1-3":    (1.25,  4.25),
    "tokenharbor/glm-5.3":           (1.40,  4.40),
    "tokenharbor/grok-4.7":          (2.00,  6.00),
    "tokenharbor/qwen3.8-max":       (2.00,  6.00),
    "tokenharbor/kimi-k3":           (3.00, 15.00),
}

# Token Harbor returns bare model ids (no "tokenharbor/" prefix) from /v1/models.
# A ":free" suffix means the campaign/free-tier route, which is never billed.
GATEWAY_PRICING = {
    "deepseek-v4.1-flash": (0.28, 0.42),
    "deepseek-v4-flash":   (0.28, 0.42),
    "deepseek-v4-pro":     (1.00,  3.00),
    "deepseek-v3.2":       (0.28,  0.42),
    "gemini-3.8-flash":    (0.50,  3.00),
    "glm-5.3":             (1.40,  4.40),
    "grok-4.7":            (2.00,  6.00),
    "qwen3.8-max":         (2.00,  6.00),
    "muse-spark-1-3":      (1.25,  4.25),
}


def rates(model: str) -> tuple[float, float]:
    """(input, output) USD per 1M tokens for any model id we might be given."""
    if model.endswith(":free"):
        return (0.0, 0.0)          # campaign route - never billed
    key = model.removeprefix("tokenharbor/")
    if key in PRICING:
        return PRICING[key]
    if model in PRICING:
        return PRICING[model]
    if key in GATEWAY_PRICING:
        return GATEWAY_PRICING[key]
    return PRICING["claude-opus-5-5"]
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
    def __init__(self, model: str | None = None, base_url: str | None = None):
        self.model = model or CONFIG.model
        url = base_url if base_url is not None else CONFIG.base_url
        kwargs = {"api_key": CONFIG.anthropic_api_key or None}
        if url:
            kwargs["base_url"] = url
        self.client = anthropic.Anthropic(**kwargs)

    @property
    def is_claude(self) -> bool:
        return "claude" in self.model.lower()

    def _price(self, usage) -> float:
        inp, out = rates(self.model)
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
        # Prompt caching, adaptive thinking and effort are Claude features. A
        # gateway serving Qwen/GLM/Grok over an Anthropic-shaped endpoint will
        # reject or silently ignore them, so only send them to a Claude model.
        if cache_system and self.is_claude:
            system_blocks[0]["cache_control"] = {"type": "ephemeral"}

        params = dict(
            model=self.model,
            max_tokens=max_tokens,
            system=system_blocks,
            messages=[{"role": "user", "content": user}],
        )
        if self.is_claude:
            params["thinking"] = {"type": "adaptive"}
            params["output_config"] = {"effort": effort}

        with self.client.messages.stream(**params) as stream:
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
