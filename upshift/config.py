"""Configuration loaded from .env / environment."""
from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def _load_dotenv(path: Path = ROOT / ".env") -> None:
    """Minimal .env loader so we don't add a dependency for three keys."""
    if not path.exists():
        return
    for line in path.read_text().splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        os.environ.setdefault(key.strip(), value.strip().strip('"').strip("'"))


_load_dotenv()


@dataclass
class Config:
    neatlogs_api_key: str = field(default_factory=lambda: os.environ.get("NEATLOGS_API_KEY", ""))
    anthropic_api_key: str = field(default_factory=lambda: os.environ.get("ANTHROPIC_API_KEY", ""))
    model: str = field(default_factory=lambda: os.environ.get("UPSHIFT_MODEL", "claude-sonnet-5-5"))
    neatlogs_endpoint: str = field(
        default_factory=lambda: os.environ.get("NEATLOGS_ENDPOINT", "https://ingest.neatlogs.com")
    )

    # agent limits
    max_attempts_per_file: int = 3
    full_suite_every: int = 10

    def missing(self) -> list[str]:
        out = []
        if not self.neatlogs_api_key:
            out.append("NEATLOGS_API_KEY")
        if not self.anthropic_api_key:
            out.append("ANTHROPIC_API_KEY")
        return out


CONFIG = Config()
