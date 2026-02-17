# regime_detector.py — Optimus Market Regime Detector
# Version: v2.001
#
# Classifies the current market into one of five regimes.
# GLD acts as a tiebreaker for borderline conditions.
# Regime determines allocation level and entry permissions.

import config as cfg
from shared.constants import Regime, GldSignal


class RegimeDetector:
    """Classifies market regime from VIX, trend, and GLD signals.

    Regimes (ordered from most to least favourable for put credit spreads):
        1. Bullish Calm   — full allocation
        2. Elevated Vol   — full allocation, richer premium
        3. High Vol       — reduced allocation (50-75%)
        4. Crisis         — halt new entries
        5. Bear Trend     — halt new entries
    """

    VERSION = "v2.001"

    def __init__(self, indicators):
        """Args:
            indicators: IndicatorEngine instance.
        """
        self.ind = indicators
        self._current_regime = None
        self._previous_regime = None

    @property
    def current_regime(self):
        return self._current_regime

    @property
    def previous_regime(self):
        return self._previous_regime

    def regime_changed(self):
        """Did the regime change on the last update?"""
        return (self._previous_regime is not None
                and self._current_regime != self._previous_regime)

    def is_tradeable(self):
        """Is the current regime permissive for new entries?"""
        return self._current_regime in (
            Regime.BULLISH_CALM,
            Regime.ELEVATED_VOL,
            Regime.HIGH_VOL,
        )

    def allocation_multiplier(self):
        """Position size multiplier based on regime.

        Returns:
            float: 1.0 for full, 0.5-0.75 for reduced, 0.0 for halted.
        """
        multipliers = {
            Regime.BULLISH_CALM: 1.0,
            Regime.ELEVATED_VOL: 1.0,
            Regime.HIGH_VOL: 0.625,  # midpoint of 50-75%
            Regime.CRISIS: 0.0,
            Regime.BEAR_TREND: 0.0,
        }
        return multipliers.get(self._current_regime, 0.0)

    def update(self):
        """Reclassify the current market regime.

        Returns:
            Regime: The new regime classification.
        """
        self._previous_regime = self._current_regime
        self._current_regime = self._classify()
        return self._current_regime

    def _classify(self):
        """Core regime classification logic."""
        vix = self.ind.vix_level()
        term_ratio = self.ind.vix_term_structure_ratio()
        above_ema = self.ind.spx_above_ema()
        gld_daily = self.ind.gld_daily_change_pct()
        gld_above_trend = self.ind.gld_above_trend_ema()

        # Crisis takes priority — checked first
        if self._is_crisis(vix, term_ratio, gld_daily):
            return Regime.CRISIS

        # Bear Trend — SPX below trend EMA
        if not above_ema:
            return self._evaluate_bear_trend(gld_above_trend)

        # Remaining: SPX above EMA — classify by VIX level
        if vix is None:
            return Regime.ELEVATED_VOL  # conservative default

        # Borderline VIX — use GLD as tiebreaker
        gld_bias = self._gld_regime_bias(gld_daily, gld_above_trend)

        if vix >= cfg.VIX_HIGH_VOL_THRESHOLD:
            return Regime.HIGH_VOL
        elif vix >= cfg.VIX_ELEVATED_THRESHOLD:
            # VIX 18-25: borderline area where GLD can tip the scale
            if gld_bias > 0:
                return Regime.HIGH_VOL  # GLD rising — lean restrictive
            return Regime.ELEVATED_VOL
        else:
            # VIX < 18
            if gld_bias > 0:
                return Regime.ELEVATED_VOL  # GLD rising — slight caution
            return Regime.BULLISH_CALM

    def _is_crisis(self, vix, term_ratio, gld_daily):
        """Check for crisis conditions."""
        if vix is not None and vix >= cfg.VIX_CRISIS_THRESHOLD:
            return True
        if (term_ratio is not None
                and term_ratio >= cfg.VIX_TERM_STRUCTURE_THRESHOLD):
            return True
        # GLD surging confirms crisis when VIX is borderline high
        if (vix is not None and vix >= cfg.VIX_HIGH_VOL_THRESHOLD
                and gld_daily is not None
                and gld_daily >= cfg.GLD_SURGE_THRESHOLD):
            return True
        return False

    def _evaluate_bear_trend(self, gld_above_trend):
        """Classify bear trend severity.

        GLD in sustained uptrend adds confirmation of risk-off environment.
        """
        # GLD above its own 50 EMA while SPX below 200 EMA = confirmed bear
        return Regime.BEAR_TREND

    def _gld_regime_bias(self, gld_daily, gld_above_trend):
        """Compute GLD bias for regime tiebreaking.

        Returns:
            int: +1 = lean restrictive, -1 = lean permissive, 0 = neutral.
        """
        if gld_daily is None:
            return 0

        # GLD surging — lean restrictive
        if gld_daily >= cfg.GLD_SURGE_THRESHOLD:
            return 1

        # GLD rising moderately and above trend — mild caution
        if gld_daily > 0.3 and gld_above_trend:
            return 1

        # GLD falling — risk-on signal
        if gld_daily < -0.3:
            return -1

        return 0

    def get_status(self):
        """Return a diagnostic dict of current regime state."""
        return {
            "regime": self._current_regime.value if self._current_regime else "UNKNOWN",
            "previous_regime": self._previous_regime.value if self._previous_regime else None,
            "regime_changed": self.regime_changed(),
            "is_tradeable": self.is_tradeable(),
            "allocation_multiplier": self.allocation_multiplier(),
            "vix": self.ind.vix_level(),
            "vix_term_ratio": self.ind.vix_term_structure_ratio(),
            "spx_above_ema": self.ind.spx_above_ema(),
            "gld_daily_pct": self.ind.gld_daily_change_pct(),
            "gld_above_trend": self.ind.gld_above_trend_ema(),
        }
