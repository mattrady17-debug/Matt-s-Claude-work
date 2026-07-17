"""Load config.yaml and tickers.txt."""

from dataclasses import dataclass, field
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parent.parent


@dataclass
class Config:
    recipient_email: str
    from_email: str
    price_move_threshold_pct: float
    sec_user_agent: str
    anthropic_model: str
    press_release_feeds: dict[str, list[str]] = field(default_factory=dict)
    tickers: list[str] = field(default_factory=list)


def load_config(root: Path = ROOT) -> Config:
    raw = yaml.safe_load((root / "config.yaml").read_text())
    tickers = [
        line.strip().upper()
        for line in (root / "tickers.txt").read_text().splitlines()
        if line.strip() and not line.strip().startswith("#")
    ]
    return Config(
        recipient_email=raw["recipient_email"],
        from_email=raw["from_email"],
        price_move_threshold_pct=float(raw.get("price_move_threshold_pct", 5.0)),
        sec_user_agent=raw["sec_user_agent"],
        anthropic_model=raw.get("anthropic_model", "claude-haiku-4-5"),
        press_release_feeds=raw.get("press_release_feeds") or {},
        tickers=tickers,
    )
