# session_manager.py — Optimus Session Manager
# Version: v2.001
#
# Market hours awareness, business day logic, and expiration calendar.

from datetime import time, timedelta
import config as cfg


class SessionManager:
    """Manages market session awareness for SPX options.

    Responsibilities:
        - Determine if market is open
        - Check if current time is within execution window
        - Count business days
        - Provide expiration calendar awareness
    """

    VERSION = "v2.001"

    # US equity options market hours (Eastern Time)
    MARKET_OPEN = time(9, 30)
    MARKET_CLOSE = time(16, 0)

    # SPX options trade until 16:15 ET (PM settlement)
    SPX_CLOSE = time(16, 15)

    def __init__(self, algorithm):
        self.algo = algorithm

    def is_market_open(self):
        """Is the US equity market currently open?"""
        now = self.algo.time
        if now.weekday() >= 5:  # Saturday or Sunday
            return False
        current_time = now.time()
        return self.MARKET_OPEN <= current_time <= self.MARKET_CLOSE

    def is_execution_window(self):
        """Is the current time within the allowed execution window?

        Window: from execution_earliest_time until market close.
        """
        if not self.is_market_open():
            return False
        current_time = self.algo.time.time()
        earliest = time(cfg.EXECUTION_EARLIEST_HOUR, cfg.EXECUTION_EARLIEST_MINUTE)
        return current_time >= earliest

    def current_dte(self, expiry_date):
        """Calculate days to expiration from now."""
        today = self.algo.time.date()
        if hasattr(expiry_date, 'date'):
            expiry_date = expiry_date.date()
        return (expiry_date - today).days

    def is_expiration_week(self, expiry_date):
        """Is the given expiry within the current trading week?"""
        today = self.algo.time.date()
        if hasattr(expiry_date, 'date'):
            expiry_date = expiry_date.date()
        days_until = (expiry_date - today).days
        return 0 <= days_until <= (4 - today.weekday())

    def next_business_day(self, from_date=None):
        """Get the next business day after from_date."""
        if from_date is None:
            from_date = self.algo.time.date()
        next_day = from_date + timedelta(days=1)
        while next_day.weekday() >= 5:
            next_day += timedelta(days=1)
        return next_day

    def business_days_from_now(self, n_days):
        """Get the date N business days from now."""
        current = self.algo.time.date()
        count = 0
        while count < n_days:
            current += timedelta(days=1)
            if current.weekday() < 5:
                count += 1
        return current

    def today_str(self):
        """Current date as string."""
        return self.algo.time.strftime("%Y-%m-%d")

    def now_str(self):
        """Current datetime as string."""
        return self.algo.time.strftime("%Y-%m-%d %H:%M")
