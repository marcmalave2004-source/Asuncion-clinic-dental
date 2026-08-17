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
class InstrumentConfig:
    """One tradable instrument. `symbol` is what strategy/risk/logging use
    throughout the bot (a ccxt symbol, or a Yahoo Finance ticker for
    trading212); `t212_ticker` is only needed for the trading212 provider,
    to map that symbol to T212's own instrument code for order placement."""
    symbol: str
    t212_ticker: str | None = None
    data_symbol: str | None = None  # override the Yahoo Finance ticker if it differs from `symbol`


@dataclass
class ExchangeConfig:
    provider: str = "ccxt"  # "ccxt" (crypto exchanges) or "trading212" (stocks/ETFs)
    id: str = "binance"  # ccxt exchange id - ignored when provider is "trading212"
    market_type: str = "spot"  # "spot" or "future"
    symbol: str = "BTC/USDT"  # single-instrument shorthand - ignored if `instruments` is set
    timeframe: str = "1h"
    use_testnet: bool = True  # ccxt sandbox mode - ignored for trading212

    # trading212 provider only:
    t212_ticker: str | None = None  # single-instrument shorthand - ignored if `instruments` is set
    t212_environment: str = "demo"  # "demo" (paper, no real money) or "live"
    data_symbol: str | None = None  # single-instrument shorthand - ignored if `instruments` is set

    # Multiple instruments to trade in the same run, e.g.:
    #   instruments:
    #     - symbol: AAPL
    #       t212_ticker: AAPL_US_EQ
    #     - symbol: VOO
    #       t212_ticker: VOO_US_EQ
    # Leave empty to use the single symbol/t212_ticker/data_symbol fields
    # above instead (backwards compatible with existing configs).
    instruments: list[InstrumentConfig] = field(default_factory=list)

    def effective_instruments(self) -> list[InstrumentConfig]:
        if self.instruments:
            return self.instruments
        return [InstrumentConfig(symbol=self.symbol, t212_ticker=self.t212_ticker, data_symbol=self.data_symbol)]


@dataclass
class StrategyConfig:
    mode: str = "ema_rsi"  # "ema_rsi" (crossover) or "bollinger" (buy at the lower band, sell at the upper band)

    ema_fast: int = 12
    ema_slow: int = 26
    rsi_period: int = 14
    rsi_overbought: float = 70.0
    rsi_oversold: float = 30.0

    bb_period: int = 20      # bollinger mode only
    bb_std_dev: float = 2.0  # bollinger mode only - band width in standard deviations

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
class SessionConfig:
    """Forces any open position closed before the market closes, so a day
    trading strategy doesn't hold positions overnight where a stop-loss
    can't protect against a gap. Disabled by default - only meaningful for
    intraday strategies on markets that actually close (irrelevant for 24/7
    crypto)."""
    enabled: bool = False
    timezone: str = "America/New_York"  # IANA tz name, e.g. US equities trade in this timezone
    close_time: str = "16:00"  # HH:MM local time the market closes
    close_buffer_minutes: int = 15  # force-exit this many minutes before close, so the order has time to fill


@dataclass
class Settings:
    exchange: ExchangeConfig = field(default_factory=ExchangeConfig)
    strategy: StrategyConfig = field(default_factory=StrategyConfig)
    risk: RiskConfig = field(default_factory=RiskConfig)
    runtime: RuntimeConfig = field(default_factory=RuntimeConfig)
    session: SessionConfig = field(default_factory=SessionConfig)

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

    exchange_raw = dict(raw.get("exchange", {}))
    instruments_raw = exchange_raw.pop("instruments", None) or []
    exchange = ExchangeConfig(**exchange_raw)
    exchange.instruments = [InstrumentConfig(**instrument) for instrument in instruments_raw]

    strategy = StrategyConfig(**raw.get("strategy", {}))
    risk = RiskConfig(**raw.get("risk", {}))
    runtime = RuntimeConfig(**raw.get("runtime", {}))
    session = SessionConfig(**raw.get("session", {}))

    if exchange.provider == "trading212":
        api_key = os.getenv("TRADING212_API_KEY")
        api_secret = os.getenv("TRADING212_API_SECRET")  # only set if your key comes with a secret
    else:
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
        session=session,
        api_key=api_key,
        api_secret=api_secret,
        live_trading_requested=live_requested,
        live_trading_confirmed=live_confirmed,
    )
