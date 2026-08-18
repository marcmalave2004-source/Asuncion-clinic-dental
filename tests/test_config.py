import pytest

from trading_bot.config import (
    ExchangeConfig,
    InstrumentConfig,
    RiskConfig,
    RuntimeConfig,
    SessionConfig,
    Settings,
    StrategyConfig,
    _validate,
)


def _settings(**overrides) -> Settings:
    base = Settings(
        exchange=ExchangeConfig(provider="trading212", instruments=[InstrumentConfig(symbol="AAPL", t212_ticker="AAPL_US_EQ")]),
    )
    for key, value in overrides.items():
        setattr(base, key, value)
    return base


def test_default_settings_are_valid():
    _validate(_settings())  # should not raise


def test_rejects_unknown_strategy_mode():
    settings = _settings(strategy=StrategyConfig(mode="momentun"))
    with pytest.raises(ValueError, match="strategy.mode"):
        _validate(settings)


def test_rejects_ema_fast_not_less_than_ema_slow():
    settings = _settings(strategy=StrategyConfig(ema_fast=26, ema_slow=12))
    with pytest.raises(ValueError, match="ema_fast"):
        _validate(settings)


def test_rejects_rsi_overbought_out_of_range():
    settings = _settings(strategy=StrategyConfig(rsi_overbought=150))
    with pytest.raises(ValueError, match="rsi_overbought"):
        _validate(settings)


def test_rejects_negative_trailing_stop_pct():
    settings = _settings(risk=RiskConfig(trailing_stop_pct=-1.0))
    with pytest.raises(ValueError, match="trailing_stop_pct"):
        _validate(settings)


def test_rejects_risk_per_trade_pct_out_of_range():
    settings = _settings(risk=RiskConfig(risk_per_trade_pct=0.0))
    with pytest.raises(ValueError, match="risk_per_trade_pct"):
        _validate(settings)


def test_rejects_max_open_positions_below_one():
    settings = _settings(risk=RiskConfig(max_open_positions=0))
    with pytest.raises(ValueError, match="max_open_positions"):
        _validate(settings)


def test_rejects_non_positive_poll_interval():
    settings = _settings(runtime=RuntimeConfig(poll_interval_seconds=0))
    with pytest.raises(ValueError, match="poll_interval_seconds"):
        _validate(settings)


def test_rejects_malformed_session_close_time_when_enabled():
    settings = _settings(session=SessionConfig(enabled=True, close_time="not-a-time"))
    with pytest.raises(ValueError, match="close_time"):
        _validate(settings)


def test_ignores_malformed_session_close_time_when_disabled():
    settings = _settings(session=SessionConfig(enabled=False, close_time="not-a-time"))
    _validate(settings)  # should not raise - session is disabled


def test_rejects_trading212_instrument_missing_ticker():
    settings = _settings(exchange=ExchangeConfig(provider="trading212", instruments=[InstrumentConfig(symbol="AAPL")]))
    with pytest.raises(ValueError, match="t212_ticker"):
        _validate(settings)


def test_rejects_empty_instrument_list():
    settings = _settings(exchange=ExchangeConfig(provider="trading212", instruments=[]))
    with pytest.raises(ValueError, match="instrument"):
        _validate(settings)


def test_collects_multiple_errors_at_once():
    settings = _settings(
        strategy=StrategyConfig(mode="bogus", rsi_overbought=200),
        risk=RiskConfig(max_open_positions=0),
    )
    with pytest.raises(ValueError) as exc_info:
        _validate(settings)
    message = str(exc_info.value)
    assert "strategy.mode" in message
    assert "rsi_overbought" in message
    assert "max_open_positions" in message
