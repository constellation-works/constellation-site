"""Award cadence for the UTC date of a frozen weekly rankings note."""
from datetime import date


def award_period(day):
    # Keep historical notes and the November 23 draft reproducible.
    if day <= date(2026, 11, 23):
        return "week"
    if day.weekday() == 0 and day.day <= 7:
        return "month"
    return None
