"""Configuration loading for the trading bot.

Reads non-secret settings from a YAML file and secrets (API keys, live
trading toggles) from environment variables / a .env file. Keeping the two
separate means the YAML file is safe to commit while credentials never are.
"""
from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path

import yaml
from dotenv import load_dotenv

load_dotenv()

# Exact string a user must set for LIVE_TRADING_CONFIRM before real orders
# can be placed. This is a deliberate second gate on top of LIVE_TRADING=true
# so that live trading can never be enabled by accident (e.g. a stray "true"
# left over from copy-pasting an example .env).
LIVE_CONFIRM_PHRASE = "I_ACCEPT_THE_RISK"


@dataclass
class ExchangeConfig:
    id: str = "binance"
    market_type: str = "spot"  # "spot" or "future"
    symbol: str = "BTC/USDT"
    timeframe: str = "1h"
    use_testnet: bool = True


@dataclass
class StrategyConfig:
    ema_fast: int = 12
    ema_slow: int = 26
    rsi_period: int = 14
    rsi_overbought: float = 70.0
    rsi_oversold: float = 30.0
    atr_period: int = 14
    atr_stop_mult: float = 2.0
    atr_target_mult: float = 3.0


@dataclass
class RiskConfig:
    risk_per_trade_pct: float = 1.0
    max_daily_loss_pct: float = 5.0
    max_open_positions: int = 1
    min_order_quote: float = 10.0
    taker_fee_pct: float = 0.1


@dataclass
class RuntimeConfig:
    poll_interval_seconds: int = 60
    dry_run: bool = True
    state_dir: str = "state"
    stop_file: str = "STOP"


@dataclass
class Settings:
    exchange: ExchangeConfig = field(default_factory=ExchangeConfig)
    strategy: StrategyConfig = field(default_factory=StrategyConfig)
    risk: RiskConfig = field(default_factory=RiskConfig)
    runtime: RuntimeConfig = field(default_factory=RuntimeConfig)

    api_key: str | None = None
    api_secret: str | None = None
    live_trading_requested: bool = False
    live_trading_confirmed: bool = False

    @property
    def live_trading_authorized(self) -> bool:
        """Both env gates must agree before any real order is ever placed."""
        return self.live_trading_requested and self.live_trading_confirmed

    @property
    def effective_dry_run(self) -> bool:
        # dry_run stays true unless the config explicitly turns it off AND
        # both live-trading env gates are satisfied.
        if self.runtime.dry_run:
            return True
        return not self.live_trading_authorized


def _load_yaml(path: Path) -> dict:
    if not path.exists():
        return {}
    with path.open("r", encoding="utf-8") as f:
        return yaml.safe_load(f) or {}


def load_settings(config_path: str | os.PathLike = "config/config.yaml") -> Settings:
    raw = _load_yaml(Path(config_path))

    exchange = ExchangeConfig(**raw.get("exchange", {}))
    strategy = StrategyConfig(**raw.get("strategy", {}))
    risk = RiskConfig(**raw.get("risk", {}))
    runtime = RuntimeConfig(**raw.get("runtime", {}))

    exchange_id = exchange.id.upper()
    api_key = os.getenv(f"{exchange_id}_API_KEY") or os.getenv("EXCHANGE_API_KEY")
    api_secret = os.getenv(f"{exchange_id}_API_SECRET") or os.getenv("EXCHANGE_API_SECRET")

    live_requested = os.getenv("LIVE_TRADING", "false").strip().lower() == "true"
    live_confirmed = os.getenv("LIVE_TRADING_CONFIRM", "") == LIVE_CONFIRM_PHRASE

    return Settings(
        exchange=exchange,
        strategy=strategy,
        risk=risk,
        runtime=runtime,
        api_key=api_key,
        api_secret=api_secret,
        live_trading_requested=live_requested,
        live_trading_confirmed=live_confirmed,
    )
