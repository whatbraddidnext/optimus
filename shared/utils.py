# shared/utils.py — Stargaze Capital Shared Utilities
# Version: v2.001

import math


def atr_with_floor(atr_value, atr_avg_100, floor_pct=0.50):
    """Apply ATR floor at 50% of 100-bar average to prevent denominator collapse."""
    floor = atr_avg_100 * floor_pct
    return max(atr_value, floor)


def safe_divide(numerator, denominator, default=0.0):
    """Division with zero-denominator protection."""
    if denominator == 0 or denominator is None:
        return default
    return numerator / denominator


def clamp(value, min_val, max_val):
    """Clamp value to [min_val, max_val]."""
    return max(min_val, min(value, max_val))


def round_to_strike(price, tick_size=5):
    """Round a price to the nearest valid strike increment."""
    return round(price / tick_size) * tick_size


def pct_change(current, previous):
    """Calculate percentage change, safe against zero."""
    return safe_divide(current - previous, abs(previous), 0.0) * 100.0


def business_days_between(start_date, end_date):
    """Count business days between two dates (exclusive of start, inclusive of end).

    Simple weekday count — does not account for market holidays.
    For production, integrate with session_manager holiday calendar.
    """
    if end_date <= start_date:
        return 0
    count = 0
    current = start_date
    from datetime import timedelta
    while current < end_date:
        current += timedelta(days=1)
        if current.weekday() < 5:  # Mon=0 .. Fri=4
            count += 1
    return count


def format_currency(value, decimals=2):
    """Format a number as currency string."""
    if value >= 0:
        return f"${value:,.{decimals}f}"
    return f"-${abs(value):,.{decimals}f}"


def format_pct(value, decimals=1):
    """Format a number as percentage string."""
    return f"{value:.{decimals}f}%"
