"""Market-session helpers, used to force-close open positions before the
market closes so a day trading strategy doesn't hold positions overnight,
where a stop-loss can't protect against a gap (the market can reopen far
past the stop price with no order filled in between).

Does not account for market holidays - a position opened right before a
holiday may stay open an extra day since no new candles get produced to
trigger a check in the first place. Acceptable for this bot's scope; a
missed holiday just means one extra day of overnight exposure, not a crash.
"""
from __future__ import annotations

from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

from trading_bot.config import SessionConfig


def is_near_session_close(cfg: SessionConfig, now: datetime | None = None) -> bool:
    if not cfg.enabled:
        return False

    tz = ZoneInfo(cfg.timezone)
    now_local = (now or datetime.now(tz)).astimezone(tz)

    if now_local.weekday() >= 5:  # Saturday/Sunday - market's closed, nothing to force
        return False

    close_hour, close_minute = (int(part) for part in cfg.close_time.split(":"))
    close_dt = now_local.replace(hour=close_hour, minute=close_minute, second=0, microsecond=0)
    cutoff_dt = close_dt - timedelta(minutes=cfg.close_buffer_minutes)

    return now_local >= cutoff_dt
