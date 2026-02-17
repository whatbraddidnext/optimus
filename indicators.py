# indicators.py — Optimus Indicator Engine
# Version: v2.001
#
# All indicator computation lives here. No calculations in signal logic.
# Wraps QuantConnect built-in indicators with Optimus-specific logic.

from collections import deque
import config as cfg
from shared.utils import safe_divide, pct_change


class IndicatorEngine:
    """Computes and stores all technical indicators for Optimus.

    Indicators:
        - Bollinger Bands (BB) on SPX
        - RSI on SPX
        - EMA (trend) on SPX
        - IV Rank (52-week percentile)
        - GLD EMA and rate of change
        - GLD/SPX rolling correlation
        - VIX term structure ratio
    """

    VERSION = "v2.001"

    def __init__(self, algorithm):
        """Initialise indicators using QuantConnect algorithm instance.

        Args:
            algorithm: The QCAlgorithm instance (provides self.bb, self.rsi, etc.)
        """
        self.algo = algorithm
        self._iv_history = deque(maxlen=252)  # 52 weeks of daily IV values
        self._spx_closes = deque(maxlen=max(cfg.BB_TOUCH_LOOKBACK + 5, 30))
        self._gld_returns = deque(maxlen=cfg.GLD_SPX_CORRELATION_PERIOD)
        self._spx_returns = deque(maxlen=cfg.GLD_SPX_CORRELATION_PERIOD)
        self._gld_closes = deque(maxlen=cfg.GLD_ROC_PERIOD + 1)
        self._warmup_complete = False
        self._bars_received = 0

    def is_ready(self):
        """Check if all indicators have sufficient data."""
        if not self._warmup_complete:
            return False
        return (
            self.algo.bb.is_ready
            and self.algo.rsi.is_ready
            and self.algo.spx_ema.is_ready
            and len(self._iv_history) >= 252
        )

    def bars_until_ready(self):
        """Estimate bars remaining until warmup completes."""
        return max(0, cfg.WARMUP_PERIOD_DAYS - self._bars_received)

    def mark_warmup_complete(self):
        """Called by main.py when QC warmup period ends."""
        self._warmup_complete = True

    # -------------------------------------------------------------------------
    # Price history tracking
    # -------------------------------------------------------------------------

    def update_spx_close(self, close_price):
        """Record a new SPX daily close."""
        self._spx_closes.append(close_price)
        self._bars_received += 1

    def update_gld_close(self, close_price):
        """Record a new GLD daily close."""
        prev = self._gld_closes[-1] if self._gld_closes else None
        self._gld_closes.append(close_price)
        if prev is not None and prev > 0:
            gld_ret = (close_price - prev) / prev
            self._gld_returns.append(gld_ret)

    def update_spx_return(self):
        """Compute and store latest SPX daily return."""
        if len(self._spx_closes) >= 2:
            prev = self._spx_closes[-2]
            curr = self._spx_closes[-1]
            if prev > 0:
                self._spx_returns.append((curr - prev) / prev)

    def update_iv(self, current_iv):
        """Record daily implied volatility for IV Rank calculation."""
        if current_iv is not None and current_iv > 0:
            self._iv_history.append(current_iv)

    # -------------------------------------------------------------------------
    # Bollinger Band readings
    # -------------------------------------------------------------------------

    def bb_upper(self):
        """Current upper Bollinger Band value."""
        return self.algo.bb.upper_band.current.value

    def bb_middle(self):
        """Current middle Bollinger Band (SMA) value."""
        return self.algo.bb.middle_band.current.value

    def bb_lower(self):
        """Current lower Bollinger Band value."""
        return self.algo.bb.lower_band.current.value

    def bb_bandwidth(self):
        """Bollinger Band bandwidth (upper - lower) / middle."""
        mid = self.bb_middle()
        return safe_divide(self.bb_upper() - self.bb_lower(), mid, 0.0)

    def spx_touched_lower_bb(self, lookback=None):
        """Check if SPX touched or closed below lower BB within lookback bars.

        Returns:
            (bool, int|None): (touched, bars_ago) — bars_ago is 0 for most recent bar.
        """
        lookback = lookback or cfg.BB_TOUCH_LOOKBACK
        lower = self.bb_lower()
        closes = list(self._spx_closes)

        for i in range(1, min(lookback + 1, len(closes) + 1)):
            idx = len(closes) - i
            if idx >= 0 and closes[idx] <= lower:
                return True, i - 1
        return False, None

    def spx_above_lower_bb(self):
        """Check if current SPX close is above lower BB (recovery)."""
        if not self._spx_closes:
            return False
        return self._spx_closes[-1] > self.bb_lower()

    # -------------------------------------------------------------------------
    # RSI readings
    # -------------------------------------------------------------------------

    def rsi_current(self):
        """Current RSI value."""
        return self.algo.rsi.current.value

    def rsi_previous(self):
        """Previous bar RSI value (stored by main.py)."""
        return getattr(self.algo, '_prev_rsi', None)

    def rsi_is_rising(self):
        """RSI is above threshold and rising."""
        prev = self.rsi_previous()
        if prev is None:
            return False
        return (self.rsi_current() > cfg.RSI_OVERSOLD_THRESHOLD
                and self.rsi_current() > prev)

    # -------------------------------------------------------------------------
    # Trend (EMA)
    # -------------------------------------------------------------------------

    def spx_ema(self):
        """Current SPX trend EMA value."""
        return self.algo.spx_ema.current.value

    def spx_above_ema(self):
        """Is SPX trading above its trend EMA?"""
        if not self._spx_closes:
            return False
        return self._spx_closes[-1] > self.spx_ema()

    def spx_ema_distance_pct(self):
        """How far SPX is above/below EMA as a percentage."""
        if not self._spx_closes:
            return 0.0
        return pct_change(self._spx_closes[-1], self.spx_ema())

    # -------------------------------------------------------------------------
    # IV Rank
    # -------------------------------------------------------------------------

    def iv_rank(self):
        """Calculate IV Rank as 52-week percentile.

        IV Rank = % of days in last 252 where IV was below current IV.
        This is the percentile method, not the simple (current-min)/(max-min).
        """
        if len(self._iv_history) < 20:
            return None
        current_iv = self._iv_history[-1]
        below_count = sum(1 for iv in self._iv_history if iv < current_iv)
        return (below_count / len(self._iv_history)) * 100.0

    def current_iv(self):
        """Most recent IV reading."""
        return self._iv_history[-1] if self._iv_history else None

    # -------------------------------------------------------------------------
    # Consecutive up closes
    # -------------------------------------------------------------------------

    def consecutive_up_closes(self):
        """Count consecutive higher closes from most recent bar backwards."""
        closes = list(self._spx_closes)
        if len(closes) < 2:
            return 0
        count = 0
        for i in range(len(closes) - 1, 0, -1):
            if closes[i] > closes[i - 1]:
                count += 1
            else:
                break
        return count

    # -------------------------------------------------------------------------
    # GLD indicators
    # -------------------------------------------------------------------------

    def gld_roc(self):
        """GLD rate of change over configured period (percentage)."""
        if len(self._gld_closes) < cfg.GLD_ROC_PERIOD + 1:
            return None
        old = self._gld_closes[-(cfg.GLD_ROC_PERIOD + 1)]
        new = self._gld_closes[-1]
        return pct_change(new, old)

    def gld_daily_change_pct(self):
        """GLD single-day percentage change."""
        if len(self._gld_closes) < 2:
            return None
        return pct_change(self._gld_closes[-1], self._gld_closes[-2])

    def gld_above_trend_ema(self):
        """Is GLD above its trend EMA?"""
        if not hasattr(self.algo, 'gld_ema') or not self.algo.gld_ema.is_ready:
            return None
        if not self._gld_closes:
            return None
        return self._gld_closes[-1] > self.algo.gld_ema.current.value

    def gld_spx_correlation(self):
        """Rolling correlation between GLD and SPX daily returns.

        Returns:
            float or None if insufficient data.
        """
        n = cfg.GLD_SPX_CORRELATION_PERIOD
        if len(self._gld_returns) < n or len(self._spx_returns) < n:
            return None

        gld = list(self._gld_returns)[-n:]
        spx = list(self._spx_returns)[-n:]

        mean_g = sum(gld) / n
        mean_s = sum(spx) / n

        cov = sum((g - mean_g) * (s - mean_s) for g, s in zip(gld, spx)) / n
        std_g = (sum((g - mean_g) ** 2 for g in gld) / n) ** 0.5
        std_s = (sum((s - mean_s) ** 2 for s in spx) / n) ** 0.5

        denom = std_g * std_s
        if denom == 0:
            return 0.0
        return cov / denom

    # -------------------------------------------------------------------------
    # VIX readings (values fed from main.py)
    # -------------------------------------------------------------------------

    def vix_level(self):
        """Current VIX level (stored by main.py)."""
        return getattr(self.algo, '_current_vix', None)

    def vix_term_structure_ratio(self):
        """VIX front-month / second-month ratio (stored by main.py).

        < 1.0 = contango (normal), > 1.0 = backwardation (stress).
        """
        return getattr(self.algo, '_vix_term_ratio', None)

    # -------------------------------------------------------------------------
    # Current SPX price
    # -------------------------------------------------------------------------

    def spx_price(self):
        """Most recent SPX close."""
        return self._spx_closes[-1] if self._spx_closes else None
