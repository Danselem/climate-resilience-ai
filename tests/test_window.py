"""Analysis window resolution: dynamic in intent, pinned in the record."""

from __future__ import annotations

from datetime import date

from climate_resilience.config import Settings, resolve_history_end


def test_unset_end_resolves_to_the_last_complete_year() -> None:
    assert resolve_history_end(None, today=date(2026, 11, 20)) == "2025-12-31"


def test_the_current_year_is_never_included_automatically() -> None:
    assert resolve_history_end(None, today=date(2026, 1, 1)) == "2025-12-31"
    assert resolve_history_end(None, today=date(2026, 12, 31)) == "2025-12-31"


def test_a_leap_year_end_resolves_to_its_own_calendar_year() -> None:
    assert resolve_history_end(None, today=date(2025, 3, 1)) == "2024-12-31"


def test_an_explicit_end_is_kept_verbatim() -> None:
    assert resolve_history_end("2024-06-30", today=date(2026, 11, 20)) == "2024-06-30"


def test_settings_default_to_the_unset_window() -> None:
    assert Settings().history_end is None
