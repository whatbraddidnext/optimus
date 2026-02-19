# indicators.py — Optimus v2.0-MVP
# IV Rank, ATR, ADX indicator wrappers for futures options
# Pure calculation — no side effects

MODULE_VERSION = "1.0"

from collections import deque
import numpy as np


class IVRankTracker:
    """Tracks implied volatility and calculates IV Rank over a 252-day window.

    IV Rank = (current_iv - 52_week_low) / (52_week_high - 52_week_low) * 100
    Uses ATM option IV from the options chain.
    """

    def __init__(self, lookback=252):
        self.lookback = lookback
        self.iv_history = deque(maxlen=lookback)
        self.current_iv = None

    @property
    def is_ready(self):
        return len(self.iv_history) >= self.lookback

    def update(self, atm_iv):
        """Update with current ATM implied volatility."""
        if atm_iv is not None and atm_iv > 0:
            self.current_iv = atm_iv
            self.iv_history.append(atm_iv)

    @property
    def iv_rank(self):
        """IV Rank as percentage (0-100)."""
        if not self.is_ready or self.current_iv is None:
            return None
        iv_high = max(self.iv_history)
        iv_low = min(self.iv_history)
        if iv_high == iv_low:
            return 50.0  # Flat vol — neutral
        return (self.current_iv - iv_low) / (iv_high - iv_low) * 100.0


class ATRCalculator:
    """Average True Range with configurable floor.

    ATR floor at 50% of 100-bar average prevents denominator collapse
    in low-volatility periods (Design Pattern #6).
    """

    def __init__(self, period=14, floor_pct=0.50, floor_lookback=100):
        self.period = period
        self.floor_pct = floor_pct
        self.floor_lookback = floor_lookback
        self.tr_values = deque(maxlen=max(period, floor_lookback))
        self.prev_close = None

    @property
    def is_ready(self):
        return len(self.tr_values) >= self.period

    def update(self, high, low, close):
        """Update with new bar data. Call once per bar."""
        if self.prev_close is not None:
            true_range = max(
                high - low,
                abs(high - self.prev_close),
                abs(low - self.prev_close)
            )
        else:
            true_range = high - low
        self.tr_values.append(true_range)
        self.prev_close = close

    @property
    def value(self):
        """Current ATR value with floor applied."""
        if not self.is_ready:
            return None
        recent = list(self.tr_values)
        raw_atr = np.mean(recent[-self.period:])

        # Apply floor: 50% of longer-term average
        if len(recent) >= self.floor_lookback:
            long_avg = np.mean(recent[-self.floor_lookback:])
            floor = long_avg * self.floor_pct
            return max(raw_atr, floor)
        return raw_atr

    @property
    def raw_value(self):
        """ATR without floor — for diagnostics only."""
        if not self.is_ready:
            return None
        return np.mean(list(self.tr_values)[-self.period:])


class ADXCalculator:
    """Average Directional Index — measures trend strength.

    ADX < 20: weak trend (range)
    ADX 20-25: developing trend
    ADX > 25: strong trend
    """

    def __init__(self, period=14):
        self.period = period
        self.prev_high = None
        self.prev_low = None
        self.prev_close = None
        self.plus_dm_values = deque(maxlen=period * 3)
        self.minus_dm_values = deque(maxlen=period * 3)
        self.tr_values = deque(maxlen=period * 3)
        self._smoothed_plus_dm = None
        self._smoothed_minus_dm = None
        self._smoothed_tr = None
        self._adx_values = deque(maxlen=period)
        self._count = 0

    @property
    def is_ready(self):
        return self._count >= self.period * 2

    def update(self, high, low, close):
        """Update with new bar data."""
        if self.prev_high is None:
            self.prev_high = high
            self.prev_low = low
            self.prev_close = close
            return

        # Directional movement
        plus_dm = max(high - self.prev_high, 0) if (high - self.prev_high) > (self.prev_low - low) else 0
        minus_dm = max(self.prev_low - low, 0) if (self.prev_low - low) > (high - self.prev_high) else 0

        # True range
        tr = max(
            high - low,
            abs(high - self.prev_close),
            abs(low - self.prev_close)
        )

        self.plus_dm_values.append(plus_dm)
        self.minus_dm_values.append(minus_dm)
        self.tr_values.append(tr)
        self._count += 1

        # Need at least period bars for initial smoothing
        if self._count < self.period:
            self.prev_high = high
            self.prev_low = low
            self.prev_close = close
            return

        if self._count == self.period:
            # Initial smoothing — simple sum
            self._smoothed_plus_dm = sum(list(self.plus_dm_values)[-self.period:])
            self._smoothed_minus_dm = sum(list(self.minus_dm_values)[-self.period:])
            self._smoothed_tr = sum(list(self.tr_values)[-self.period:])
        else:
            # Wilder smoothing
            self._smoothed_plus_dm = self._smoothed_plus_dm - (self._smoothed_plus_dm / self.period) + plus_dm
            self._smoothed_minus_dm = self._smoothed_minus_dm - (self._smoothed_minus_dm / self.period) + minus_dm
            self._smoothed_tr = self._smoothed_tr - (self._smoothed_tr / self.period) + tr

        # Calculate DI+ and DI-
        if self._smoothed_tr > 0:
            plus_di = (self._smoothed_plus_dm / self._smoothed_tr) * 100
            minus_di = (self._smoothed_minus_dm / self._smoothed_tr) * 100
        else:
            plus_di = 0
            minus_di = 0

        # DX
        di_sum = plus_di + minus_di
        if di_sum > 0:
            dx = abs(plus_di - minus_di) / di_sum * 100
        else:
            dx = 0

        self._adx_values.append(dx)

        self.prev_high = high
        self.prev_low = low
        self.prev_close = close

    @property
    def value(self):
        """Current ADX value."""
        if not self.is_ready or len(self._adx_values) < self.period:
            return None
        return np.mean(list(self._adx_values)[-self.period:])


class RealisedVolCalculator:
    """Realised volatility over configurable windows.

    Used for regime detection (comparing short-term vs long-term RV)
    and crisis detection (absolute RV thresholds).
    """

    def __init__(self, short_window=5, long_window=20, extended_window=60):
        self.short_window = short_window
        self.long_window = long_window
        self.extended_window = extended_window
        self.returns = deque(maxlen=extended_window + 1)
        self.prev_close = None

    @property
    def is_ready(self):
        return len(self.returns) >= self.long_window

    def update(self, close):
        """Update with new close price."""
        if self.prev_close is not None and self.prev_close > 0:
            daily_return = (close - self.prev_close) / self.prev_close
            self.returns.append(daily_return)
        self.prev_close = close

    def _rv(self, window):
        """Realised vol as daily std dev (not annualised)."""
        vals = list(self.returns)
        if len(vals) < window:
            return None
        return float(np.std(vals[-window:]))

    @property
    def short_rv(self):
        """5-day realised vol (daily %)."""
        return self._rv(self.short_window)

    @property
    def long_rv(self):
        """20-day realised vol (daily %)."""
        return self._rv(self.long_window)

    @property
    def extended_rv(self):
        """60-day realised vol (daily %)."""
        return self._rv(self.extended_window)

    @property
    def rv_ratio(self):
        """Short/long RV ratio — spike detection."""
        s = self.short_rv
        l = self.long_rv
        if s is None or l is None or l == 0:
            return None
        return s / l


class SMACalculator:
    """Simple Moving Average for regime detection."""

    def __init__(self, period=20):
        self.period = period
        self.values = deque(maxlen=period)

    @property
    def is_ready(self):
        return len(self.values) >= self.period

    def update(self, value):
        self.values.append(value)

    @property
    def value(self):
        if not self.is_ready:
            return None
        return np.mean(list(self.values))


class BandwidthTracker:
    """Bollinger Bandwidth for squeeze detection.

    Bandwidth = (Upper - Lower) / Middle * 100
    Low bandwidth = squeeze = potential breakout
    """

    def __init__(self, period=20, std_dev=2.0, percentile_lookback=252):
        self.period = period
        self.std_dev = std_dev
        self.values = deque(maxlen=period)
        self.bandwidth_history = deque(maxlen=percentile_lookback)

    @property
    def is_ready(self):
        return len(self.values) >= self.period

    def update(self, close):
        self.values.append(close)
        if self.is_ready:
            bw = self._bandwidth()
            if bw is not None:
                self.bandwidth_history.append(bw)

    def _bandwidth(self):
        vals = list(self.values)
        middle = np.mean(vals)
        if middle == 0:
            return None
        std = np.std(vals)
        upper = middle + self.std_dev * std
        lower = middle - self.std_dev * std
        return (upper - lower) / middle * 100

    @property
    def value(self):
        """Current bandwidth."""
        if not self.is_ready:
            return None
        return self._bandwidth()

    def percentile(self, pct):
        """Return the Nth percentile of historical bandwidth."""
        if len(self.bandwidth_history) < 60:
            return None
        return float(np.percentile(list(self.bandwidth_history), pct))
