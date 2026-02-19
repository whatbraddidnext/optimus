# trend_gradient.py — Optimus v2.0-MVP
# Trend score calculation and delta skew mapping
# Pure calculation — no side effects, deterministic

MODULE_VERSION = "1.0"

from collections import deque
import numpy as np


class TrendGradientEngine:
    """Measures prevailing price drift and maps it to call/put delta targets.

    The trend score aligns strike placement with the direction price is
    most likely to drift over the DTE window. This is not a directional bet —
    it is probabilistic alignment that improves win rate by 1-3%.

    Trend Score range: -1.0 (strong downtrend) to +1.0 (strong uptrend)
    """

    def __init__(self, primary_lookback=30, confirm_lookback=10, scaling_factor=0.5):
        self.primary_lookback = primary_lookback
        self.confirm_lookback = confirm_lookback
        self.scaling_factor = scaling_factor
        self.closes = deque(maxlen=max(primary_lookback, confirm_lookback) + 5)
        self.atr_values = deque(maxlen=primary_lookback + 5)

    @property
    def is_ready(self):
        return (len(self.closes) >= self.primary_lookback and
                len(self.atr_values) >= self.primary_lookback)

    def update(self, close, atr_value):
        """Update with daily close and current ATR value."""
        self.closes.append(close)
        if atr_value is not None and atr_value > 0:
            self.atr_values.append(atr_value)

    def _linear_regression_slope(self, values):
        """Ordinary least squares slope."""
        n = len(values)
        if n < 2:
            return 0.0
        x = np.arange(n, dtype=float)
        y = np.array(values, dtype=float)
        x_mean = np.mean(x)
        y_mean = np.mean(y)
        numerator = np.sum((x - x_mean) * (y - y_mean))
        denominator = np.sum((x - x_mean) ** 2)
        if denominator == 0:
            return 0.0
        return numerator / denominator

    @property
    def trend_score(self):
        """Calculate trend score: -1.0 to +1.0.

        Step 1: Primary slope (linear regression over lookback)
        Step 2: Normalise to daily percentage
        Step 3: ATR-normalise and clip
        Step 4: Confirmation filter (secondary slope must agree)
        """
        if not self.is_ready:
            return 0.0

        closes = list(self.closes)
        current_price = closes[-1]
        if current_price <= 0:
            return 0.0

        # Step 1: Primary slope
        primary_data = closes[-self.primary_lookback:]
        primary_slope = self._linear_regression_slope(primary_data)

        # Step 2: Normalise to daily percentage
        normalised_slope = (primary_slope / current_price) * 100

        # Step 3: ATR-normalise
        atr_list = list(self.atr_values)
        avg_atr = np.mean(atr_list[-self.primary_lookback:])
        if avg_atr <= 0 or current_price <= 0:
            return 0.0
        daily_atr_pct = (avg_atr / current_price) * 100
        if daily_atr_pct * self.scaling_factor == 0:
            return 0.0
        raw_score = normalised_slope / (daily_atr_pct * self.scaling_factor)
        score = max(-1.0, min(1.0, raw_score))

        # Step 4: Confirmation filter
        if len(closes) >= self.confirm_lookback:
            confirm_data = closes[-self.confirm_lookback:]
            confirm_slope = self._linear_regression_slope(confirm_data)
            # If primary and confirmation disagree in direction, force symmetric
            if (primary_slope > 0 and confirm_slope < 0) or (primary_slope < 0 and confirm_slope > 0):
                return 0.0

        return round(score, 4)

    def get_delta_targets(self, asset_config):
        """Map trend score to call/put delta targets.

        Returns (call_delta, put_delta) based on trend score and asset config.

        Trend Score > +0.3: uptrend — give calls more room (lower delta),
                            lean into puts (higher delta)
        Trend Score < -0.3: downtrend — mirror
        Between -0.3 and +0.3: symmetric (default delta both sides)
        """
        score = self.trend_score
        default_delta = asset_config["default_short_delta"]
        min_delta = asset_config["min_skew_delta"]
        max_delta = asset_config["max_skew_delta"]

        if abs(score) <= 0.3:
            return default_delta, default_delta

        if score > 0.3:
            # Uptrend: calls get more room (lower delta), puts tighter (higher delta)
            skew_factor = (score - 0.3) / 0.7
            call_delta = default_delta - skew_factor * (default_delta - min_delta)
            put_delta = default_delta + skew_factor * (max_delta - default_delta)
        else:
            # Downtrend: puts get more room (lower delta), calls tighter (higher delta)
            skew_factor = (abs(score) - 0.3) / 0.7
            call_delta = default_delta + skew_factor * (max_delta - default_delta)
            put_delta = default_delta - skew_factor * (default_delta - min_delta)

        # Clamp to asset bounds
        call_delta = max(min_delta, min(max_delta, round(call_delta, 4)))
        put_delta = max(min_delta, min(max_delta, round(put_delta, 4)))

        return call_delta, put_delta

    def should_suppress_entry(self, iv_rank, suppress_threshold=0.9, iv_threshold=30):
        """Check if trend is too strong with too little premium to trade.

        Strong trend (>0.9) + low IV rank (<30) = thin premium, likely breach.
        """
        return abs(self.trend_score) >= suppress_threshold and (iv_rank is not None and iv_rank < iv_threshold)
