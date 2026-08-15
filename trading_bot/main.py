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
@click.pass_context
def backtest(ctx: click.Context, since: str, until: str | None, balance: float):
    """Run the strategy against historical data - no orders, no API keys needed
    for public exchanges or for the trading212 provider (uses Yahoo Finance)."""
    from trading_bot.backtester import run_backtest
    from trading_bot.market_data import build_market_data

    settings = ctx.obj["settings"]
    since_ms = int(datetime.fromisoformat(since).replace(tzinfo=timezone.utc).timestamp() * 1000)
    until_dt = datetime.fromisoformat(until).replace(tzinfo=timezone.utc) if until else datetime.now(timezone.utc)
    until_ms = int(until_dt.timestamp() * 1000)

    exchange_client = None
    if settings.exchange.provider == "ccxt":
        from trading_bot.exchange import ExchangeClient

        exchange_client = ExchangeClient(settings)
    market_data = build_market_data(settings, exchange_client)

    click.echo(f"Fetching {settings.exchange.symbol} {settings.exchange.timeframe} history...")
    df = market_data.fetch_historical(settings.exchange.symbol, settings.exchange.timeframe, since_ms, until_ms)
    if df.empty:
        click.echo("No historical data returned - check symbol/timeframe/date range.")
        sys.exit(1)

    click.echo(f"Got {len(df)} candles. Running backtest...")
    result = run_backtest(df, settings.strategy, settings.risk, initial_balance=balance)
    click.echo(result.summary())


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
