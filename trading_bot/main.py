"""CLI entrypoint.

Usage:
    python -m trading_bot.main backtest --since 2023-01-01 --until 2024-01-01
    python -m trading_bot.main run --mode paper
    python -m trading_bot.main run --mode live
"""
from __future__ import annotations

import sys
from datetime import datetime, timezone

import click

from trading_bot.config import LIVE_CONFIRM_PHRASE, load_settings
from trading_bot.logger import get_logger

log = get_logger(__name__)


@click.group()
@click.option("--config", "config_path", default="config/config.yaml", show_default=True)
@click.pass_context
def cli(ctx: click.Context, config_path: str):
    ctx.ensure_object(dict)
    ctx.obj["settings"] = load_settings(config_path)


@cli.command()
@click.option("--since", required=True, help="Start date, e.g. 2023-01-01")
@click.option("--until", default=None, help="End date, e.g. 2024-01-01 (default: now)")
@click.option("--balance", default=1000.0, show_default=True, help="Initial paper balance in quote currency")
@click.option(
    "--symbol", default=None,
    help="Which configured instrument to backtest (see exchange.instruments in config.yaml). "
         "Defaults to the first one configured. The backtester tests one instrument at a time.",
)
@click.option(
    "--mode", default=None, type=click.Choice(["ema_rsi", "bollinger"]),
    help="Override strategy.mode for this run only",
)
@click.option("--ema-fast", default=None, type=int, help="Override strategy.ema_fast for this run only")
@click.option("--ema-slow", default=None, type=int, help="Override strategy.ema_slow for this run only")
@click.option("--rsi-overbought", default=None, type=float, help="Override strategy.rsi_overbought for this run only")
@click.option("--bb-period", default=None, type=int, help="Override strategy.bb_period for this run only (bollinger mode)")
@click.option("--bb-std-dev", default=None, type=float, help="Override strategy.bb_std_dev for this run only (bollinger mode)")
@click.option("--atr-stop-mult", default=None, type=float, help="Override strategy.atr_stop_mult for this run only")
@click.option("--atr-target-mult", default=None, type=float, help="Override strategy.atr_target_mult for this run only")
@click.pass_context
def backtest(
    ctx: click.Context, since: str, until: str | None, balance: float, symbol: str | None,
    mode: str | None, ema_fast: int | None, ema_slow: int | None, rsi_overbought: float | None,
    bb_period: int | None, bb_std_dev: float | None,
    atr_stop_mult: float | None, atr_target_mult: float | None,
):
    """Run the strategy against historical data - no orders, no API keys needed
    for public exchanges or for the trading212 provider (uses Yahoo Finance).

    The --mode/--ema-fast/--ema-slow/--rsi-overbought/--bb-*/--atr-*-mult
    options override config.yaml's strategy section for this run only, to
    compare parameter combinations without touching the live config."""
    from trading_bot.backtester import run_backtest
    from trading_bot.market_data import build_market_data

    settings = ctx.obj["settings"]
    if mode is not None:
        settings.strategy.mode = mode
    if ema_fast is not None:
        settings.strategy.ema_fast = ema_fast
    if ema_slow is not None:
        settings.strategy.ema_slow = ema_slow
    if rsi_overbought is not None:
        settings.strategy.rsi_overbought = rsi_overbought
    if bb_period is not None:
        settings.strategy.bb_period = bb_period
    if bb_std_dev is not None:
        settings.strategy.bb_std_dev = bb_std_dev
    if atr_stop_mult is not None:
        settings.strategy.atr_stop_mult = atr_stop_mult
    if atr_target_mult is not None:
        settings.strategy.atr_target_mult = atr_target_mult

    instruments = settings.exchange.effective_instruments()
    available_symbols = [i.symbol for i in instruments]
    if symbol is None:
        symbol = available_symbols[0]
    elif symbol not in available_symbols:
        click.echo(f"'{symbol}' isn't configured. Available: {', '.join(available_symbols)}", err=True)
        sys.exit(1)

    since_ms = int(datetime.fromisoformat(since).replace(tzinfo=timezone.utc).timestamp() * 1000)
    until_dt = datetime.fromisoformat(until).replace(tzinfo=timezone.utc) if until else datetime.now(timezone.utc)
    until_ms = int(until_dt.timestamp() * 1000)

    exchange_client = None
    if settings.exchange.provider == "ccxt":
        from trading_bot.exchange import ExchangeClient

        exchange_client = ExchangeClient(settings)
    market_data = build_market_data(settings, exchange_client)

    click.echo(f"Fetching {symbol} {settings.exchange.timeframe} history...")
    df = market_data.fetch_historical(symbol, settings.exchange.timeframe, since_ms, until_ms)
    if df.empty:
        click.echo("No historical data returned - check symbol/timeframe/date range.")
        sys.exit(1)

    click.echo(f"Got {len(df)} candles. Running backtest...")
    if settings.strategy.mode == "bollinger":
        click.echo(
            f"Strategy: mode=bollinger bb_period={settings.strategy.bb_period} "
            f"bb_std_dev={settings.strategy.bb_std_dev} "
            f"atr_stop_mult={settings.strategy.atr_stop_mult} atr_target_mult={settings.strategy.atr_target_mult}"
        )
    else:
        click.echo(
            f"Strategy: mode=ema_rsi ema={settings.strategy.ema_fast}/{settings.strategy.ema_slow} "
            f"rsi_overbought={settings.strategy.rsi_overbought} "
            f"atr_stop_mult={settings.strategy.atr_stop_mult} atr_target_mult={settings.strategy.atr_target_mult}"
        )
    result = run_backtest(df, settings.strategy, settings.risk, initial_balance=balance)
    click.echo(f"[{symbol}] {result.summary()}")


@cli.command(name="check-broker")
@click.pass_context
def check_broker(ctx: click.Context):
    """Read-only sanity check: confirms broker credentials/auth work by
    fetching your account's free cash balance. Places no orders - safe to
    run against a live API key."""
    from trading_bot.broker import build_broker

    settings = ctx.obj["settings"]
    exchange_client = None
    if settings.exchange.provider == "ccxt":
        from trading_bot.exchange import ExchangeClient

        exchange_client = ExchangeClient(settings)

    broker = build_broker(settings, exchange_client)

    if settings.exchange.provider == "trading212":
        # Print the raw response too: the exact field name for free cash in
        # /equity/account/summary wasn't shown in the docs excerpt this
        # client was built from, so this lets you eyeball it directly if
        # fetch_free_balance() can't find a matching key.
        raw = broker.client.get_account_summary()
        click.echo(f"Raw account summary: {raw}")

    balance = broker.fetch_free_balance()
    click.echo(f"Connected OK via provider={settings.exchange.provider}. Free balance: {balance}")


@cli.command()
@click.option("--mode", type=click.Choice(["paper", "live"]), default="paper", show_default=True)
@click.option("--iterations", default=None, type=int, help="Stop after N loop iterations (mainly for testing)")
@click.option(
    "--yes", is_flag=True, default=False,
    help="Skip the interactive live-trading confirmation prompt. For non-interactive "
         "automation (e.g. a GitHub Actions workflow) where there's no terminal to "
         "answer y/N. Does NOT skip the LIVE_TRADING/LIVE_TRADING_CONFIRM env var gates.",
)
@click.pass_context
def run(ctx: click.Context, mode: str, iterations: int | None, yes: bool):
    """Run the bot continuously against live market data."""
    from trading_bot.runner import run_loop

    settings = ctx.obj["settings"]

    if mode == "live":
        settings.runtime.dry_run = False
        if not settings.live_trading_authorized:
            click.echo(
                "Refusing to start live mode: set both environment variables\n"
                "  LIVE_TRADING=true\n"
                f"  LIVE_TRADING_CONFIRM={LIVE_CONFIRM_PHRASE}\n"
                "and set runtime.dry_run: false in your config.yaml.\n"
                "This project can lose real money - these gates exist on purpose.",
                err=True,
            )
            sys.exit(1)
        if not yes:
            click.confirm(
                "You are about to start LIVE trading with real funds. Continue?",
                abort=True,
            )

    run_loop(settings, max_iterations=iterations)


if __name__ == "__main__":
    cli(obj={})
