# regime_detector.py — Optimus v2.0-MVP
# Per-asset regime classification with confirmation rules
# Regimes gate entry: only RANGING and LOW_VOL allow new trades

MODULE_VERSION = "1.0"


class Regime:
    RANGING = "RANGING"
    LOW_VOL = "LOW_VOL"
    TRENDING = "TRENDING"
    HIGH_VOL = "HIGH_VOL"
    CRISIS = "CRISIS"


# Which regimes allow new entries
ENTRY_ALLOWED = {Regime.RANGING, Regime.LOW_VOL}
# TRENDING allows entry only with strong skew (handled in signal_engine)
ENTRY_CONDITIONAL = {Regime.TRENDING}


class RegimeDetector:
    """Classifies market regime for a single underlying.

    Regime definitions (HLD Section 11.2):
    - RANGING: ADX < 25, price within 1.5 ATR of SMA, bandwidth > 20th pct
    - LOW_VOL: ADX < 20, bandwidth < 20th pct (squeeze)
    - TRENDING: ADX >= 25, price > 1.5 ATR from SMA
    - HIGH_VOL: RV(20) > 2x RV(60) OR session move > 3%
    - CRISIS: VIX > 35 (ES) or per-asset RV threshold

    Transitions require 2 consecutive daily confirmations.
    Return to RANGING from HIGH_VOL requires 5 days declining RV.
    """

    def __init__(self, asset_key, asset_config, global_config):
        self.asset_key = asset_key
        self.config = asset_config
        self.global_config = global_config

        self.current_regime = Regime.RANGING
        self._pending_regime = None
        self._confirmation_count = 0
        self._declining_rv_days = 0
        self._prev_rv = None

        self.confirm_days = global_config.get("regime_confirm_days", 2)
        self.recovery_days = global_config.get("regime_recovery_days", 5)

    def update(self, adx, atr, sma, bandwidth, bandwidth_pctl_20,
               current_price, rv_short, rv_long, rv_extended,
               session_move_pct=None, vix=None):
        """Evaluate regime based on current indicator values.

        Args:
            adx: ADX(14) value
            atr: ATR(14) value (floored)
            sma: 20-day SMA
            bandwidth: Current Bollinger bandwidth
            bandwidth_pctl_20: 20th percentile of bandwidth history
            current_price: Current underlying price
            rv_short: 5-day realised vol
            rv_long: 20-day realised vol
            rv_extended: 60-day realised vol
            session_move_pct: Intraday move as percentage (optional)
            vix: Current VIX level (for /ES crisis detection)

        Returns:
            Current regime string
        """
        if any(v is None for v in [adx, atr, sma, current_price]):
            return self.current_regime

        raw_regime = self._classify(
            adx, atr, sma, bandwidth, bandwidth_pctl_20,
            current_price, rv_short, rv_long, rv_extended,
            session_move_pct, vix
        )

        # Apply confirmation rules
        self._apply_transition(raw_regime, rv_long)

        return self.current_regime

    def _classify(self, adx, atr, sma, bandwidth, bandwidth_pctl_20,
                  current_price, rv_short, rv_long, rv_extended,
                  session_move_pct, vix):
        """Raw regime classification without confirmation."""
        cfg = self.config

        # CRISIS takes priority
        if self._is_crisis(rv_short, session_move_pct, vix):
            return Regime.CRISIS

        # HIGH_VOL
        if self._is_high_vol(rv_long, rv_extended, session_move_pct):
            return Regime.HIGH_VOL

        # TRENDING
        adx_threshold = cfg.get("adx_trending_threshold", 25)
        atr_distance = cfg.get("atr_distance_threshold", 1.5)
        if adx is not None and adx >= adx_threshold:
            if sma is not None and atr is not None and atr > 0:
                distance_from_sma = abs(current_price - sma) / atr
                if distance_from_sma > atr_distance:
                    return Regime.TRENDING

        # LOW_VOL (squeeze)
        adx_low_threshold = cfg.get("adx_low_vol_threshold", 20)
        if adx is not None and adx < adx_low_threshold:
            if bandwidth is not None and bandwidth_pctl_20 is not None:
                if bandwidth < bandwidth_pctl_20:
                    return Regime.LOW_VOL

        # RANGING (default if nothing else triggers)
        return Regime.RANGING

    def _is_crisis(self, rv_short, session_move_pct, vix):
        """Check per-asset crisis thresholds."""
        # ES uses VIX
        if self.asset_key == "ES" and vix is not None:
            if vix > self.global_config.get("vix_crisis", 35):
                return True

        # Per-asset RV threshold
        crisis_threshold = self.config.get("crisis_rv_threshold")
        if crisis_threshold is not None and rv_short is not None:
            if rv_short > crisis_threshold:
                return True

        return False

    def _is_high_vol(self, rv_long, rv_extended, session_move_pct):
        """HIGH_VOL: RV(20) > 2x RV(60) OR big session move."""
        multiplier = self.config.get("high_vol_rv_multiplier", 2.0)
        move_threshold = self.config.get("high_vol_session_move_pct", 3.0)

        if rv_long is not None and rv_extended is not None and rv_extended > 0:
            if rv_long > multiplier * rv_extended:
                return True

        if session_move_pct is not None and abs(session_move_pct) > move_threshold:
            return True

        return False

    def _apply_transition(self, raw_regime, rv_long):
        """Apply confirmation rules for regime transitions.

        - Normal transitions: 2 consecutive days confirming new regime
        - HIGH_VOL -> RANGING: requires 5 days of declining RV
        - CRISIS: immediate (no confirmation delay)
        """
        # CRISIS is immediate — no confirmation needed
        if raw_regime == Regime.CRISIS:
            self.current_regime = Regime.CRISIS
            self._pending_regime = None
            self._confirmation_count = 0
            return

        # Special recovery from HIGH_VOL: need declining RV
        if self.current_regime == Regime.HIGH_VOL and raw_regime in ENTRY_ALLOWED:
            if rv_long is not None:
                if self._prev_rv is not None and rv_long < self._prev_rv:
                    self._declining_rv_days += 1
                else:
                    self._declining_rv_days = 0
                self._prev_rv = rv_long

                if self._declining_rv_days >= self.recovery_days:
                    self.current_regime = raw_regime
                    self._declining_rv_days = 0
                    self._pending_regime = None
                    self._confirmation_count = 0
            return

        # Standard confirmation: 2 consecutive days
        if raw_regime != self.current_regime:
            if raw_regime == self._pending_regime:
                self._confirmation_count += 1
                if self._confirmation_count >= self.confirm_days:
                    self.current_regime = raw_regime
                    self._pending_regime = None
                    self._confirmation_count = 0
                    self._declining_rv_days = 0
            else:
                self._pending_regime = raw_regime
                self._confirmation_count = 1
        else:
            # Regime confirmed — reset pending
            self._pending_regime = None
            self._confirmation_count = 0

    @property
    def allows_entry(self):
        """Whether current regime allows new trade entries."""
        return self.current_regime in ENTRY_ALLOWED

    @property
    def allows_conditional_entry(self):
        """TRENDING allows entry only with strong trend-adjusted skew."""
        return self.current_regime in ENTRY_CONDITIONAL

    @property
    def tighten_profit_target(self):
        """In TRENDING regime, tighten profit targets to 40%."""
        return self.current_regime == Regime.TRENDING
