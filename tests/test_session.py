from datetime import datetime
from zoneinfo import ZoneInfo

from trading_bot.config import SessionConfig
from trading_bot.session import is_near_session_close

NY = ZoneInfo("America/New_York")


def _cfg(**overrides):
    return SessionConfig(enabled=True, timezone="America/New_York", close_time="16:00", close_buffer_minutes=15, **overrides)


def test_disabled_session_never_forces_close():
    cfg = SessionConfig(enabled=False)
    friday_at_close = datetime(2026, 8, 14, 16, 0, tzinfo=NY)  # a Friday
    assert is_near_session_close(cfg, now=friday_at_close) is False


def test_well_before_close_does_not_trigger():
    cfg = _cfg()
    mid_morning = datetime(2026, 8, 14, 10, 0, tzinfo=NY)
    assert is_near_session_close(cfg, now=mid_morning) is False


def test_inside_buffer_window_triggers():
    cfg = _cfg()
    just_inside_buffer = datetime(2026, 8, 14, 15, 50, tzinfo=NY)  # 10 min before close, buffer is 15
    assert is_near_session_close(cfg, now=just_inside_buffer) is True


def test_exactly_at_cutoff_triggers():
    cfg = _cfg()
    exact_cutoff = datetime(2026, 8, 14, 15, 45, tzinfo=NY)  # close_time - buffer
    assert is_near_session_close(cfg, now=exact_cutoff) is True


def test_after_market_close_still_triggers():
    cfg = _cfg()
    after_close = datetime(2026, 8, 14, 18, 0, tzinfo=NY)
    assert is_near_session_close(cfg, now=after_close) is True


def test_weekend_never_triggers_even_within_window():
    cfg = _cfg()
    saturday_at_close = datetime(2026, 8, 15, 15, 50, tzinfo=NY)  # Saturday
    assert is_near_session_close(cfg, now=saturday_at_close) is False


def test_converts_from_other_timezones():
    cfg = _cfg()
    # 19:50 UTC == 15:50 America/New_York during EDT (UTC-4) in August - inside the buffer window
    utc_time = datetime(2026, 8, 14, 19, 50, tzinfo=ZoneInfo("UTC"))
    assert is_near_session_close(cfg, now=utc_time) is True
