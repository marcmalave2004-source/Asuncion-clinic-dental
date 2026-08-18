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
    mode: str = "ema_rsi"  # "ema_rsi" (trend), "bollinger" (buy at the lower band, sell at the upper band), or "momentum" (buy any uptick, sell any downtick - no trend/RSI filter)

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
    # Once a position is showing a profit, exit as soon as price pulls back
    # this many percent from its peak since entry - locks in small gains
    # instead of holding out for the take-profit/opposite-signal exit.
    # 0.0 (default) disables this and only ever exits on stop-loss,
    # take-profit, or the strategy's own signal/session-close logic.
    trailing_stop_pct: float = 0.0


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


VALID_STRATEGY_MODES = ("ema_rsi", "bollinger", "momentum")
VALID_PROVIDERS = ("ccxt", "trading212")
VALID_T212_ENVIRONMENTS = ("demo", "live")


def _validate(settings: Settings) -> None:
    """Fail fast and loud on a nonsensical config, instead of the bot
    silently never trading (or misbehaving) because of a typo like
    strategy.mode: "momentun" or a negative trailing_stop_pct. Collects
    every problem found instead of stopping at the first one."""
    errors: list[str] = []

    if settings.exchange.provider not in VALID_PROVIDERS:
        errors.append(f"exchange.provider must be one of {VALID_PROVIDERS}, got {settings.exchange.provider!r}")
    if settings.exchange.provider == "trading212" and settings.exchange.t212_environment not in VALID_T212_ENVIRONMENTS:
        errors.append(
            f"exchange.t212_environment must be one of {VALID_T212_ENVIRONMENTS}, "
            f"got {settings.exchange.t212_environment!r}"
        )
    instruments = settings.exchange.effective_instruments()
    if not instruments:
        errors.append("exchange.instruments (or exchange.symbol) must configure at least one instrument")
    for instrument in instruments:
        if not instrument.symbol:
            errors.append("every instrument needs a non-empty symbol")
        if settings.exchange.provider == "trading212" and not instrument.t212_ticker:
            errors.append(f"instrument {instrument.symbol!r} needs a t212_ticker for the trading212 provider")

    if settings.strategy.mode not in VALID_STRATEGY_MODES:
        errors.append(f"strategy.mode must be one of {VALID_STRATEGY_MODES}, got {settings.strategy.mode!r}")
    if settings.strategy.ema_fast >= settings.strategy.ema_slow:
        errors.append(
            f"strategy.ema_fast ({settings.strategy.ema_fast}) must be less than "
            f"strategy.ema_slow ({settings.strategy.ema_slow})"
        )
    if not 0 < settings.strategy.rsi_overbought <= 100:
        errors.append(f"strategy.rsi_overbought must be between 0 and 100, got {settings.strategy.rsi_overbought}")
    if not 0 <= settings.strategy.rsi_oversold < 100:
        errors.append(f"strategy.rsi_oversold must be between 0 and 100, got {settings.strategy.rsi_oversold}")
    if settings.strategy.rsi_oversold >= settings.strategy.rsi_overbought:
        errors.append("strategy.rsi_oversold must be less than strategy.rsi_overbought")
    if settings.strategy.atr_period <= 0:
        errors.append(f"strategy.atr_period must be positive, got {settings.strategy.atr_period}")
    if settings.strategy.atr_stop_mult <= 0:
        errors.append(f"strategy.atr_stop_mult must be positive, got {settings.strategy.atr_stop_mult}")
    if settings.strategy.atr_target_mult <= 0:
        errors.append(f"strategy.atr_target_mult must be positive, got {settings.strategy.atr_target_mult}")
    if settings.strategy.bb_period <= 0:
        errors.append(f"strategy.bb_period must be positive, got {settings.strategy.bb_period}")
    if settings.strategy.bb_std_dev <= 0:
        errors.append(f"strategy.bb_std_dev must be positive, got {settings.strategy.bb_std_dev}")

    if not 0 < settings.risk.risk_per_trade_pct <= 100:
        errors.append(f"risk.risk_per_trade_pct must be between 0 and 100, got {settings.risk.risk_per_trade_pct}")
    if not 0 < settings.risk.max_daily_loss_pct <= 100:
        errors.append(f"risk.max_daily_loss_pct must be between 0 and 100, got {settings.risk.max_daily_loss_pct}")
    if settings.risk.max_open_positions < 1:
        errors.append(f"risk.max_open_positions must be at least 1, got {settings.risk.max_open_positions}")
    if settings.risk.min_order_quote < 0:
        errors.append(f"risk.min_order_quote cannot be negative, got {settings.risk.min_order_quote}")
    if settings.risk.taker_fee_pct < 0:
        errors.append(f"risk.taker_fee_pct cannot be negative, got {settings.risk.taker_fee_pct}")
    if settings.risk.trailing_stop_pct < 0:
        errors.append(f"risk.trailing_stop_pct cannot be negative, got {settings.risk.trailing_stop_pct}")

    if settings.runtime.poll_interval_seconds <= 0:
        errors.append(f"runtime.poll_interval_seconds must be positive, got {settings.runtime.poll_interval_seconds}")

    if settings.session.enabled:
        if settings.session.close_buffer_minutes < 0:
            errors.append(f"session.close_buffer_minutes cannot be negative, got {settings.session.close_buffer_minutes}")
        try:
            hour_str, minute_str = settings.session.close_time.split(":")
            if not (0 <= int(hour_str) <= 23 and 0 <= int(minute_str) <= 59):
                raise ValueError
        except ValueError:
            errors.append(f"session.close_time must be in HH:MM 24h format, got {settings.session.close_time!r}")

    if errors:
        details = "\n  - ".join(errors)
        raise ValueError(f"Invalid configuration ({len(errors)} problem(s)):\n  - {details}")


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

    settings = Settings(
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
    _validate(settings)
    return settings
