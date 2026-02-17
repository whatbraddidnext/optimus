# market_analyzer.py — Optimus Market Analyzer
# Version: v2.001
#
# Performs the full market diagnosis pipeline (HLD Section 3):
#   3.1 Volatility Assessment
#   3.2 Market Sentiment & Direction (including GLD)
# Feeds into signal_engine.py for gate evaluation.

import config as cfg
from shared.constants import GldSignal


class MarketAnalyzer:
    """Analyses market conditions for options premium selling suitability.

    Produces structured pass/fail assessments for each market filter
    with full diagnostic detail for logging.
    """

    VERSION = "v2.001"

    def __init__(self, indicators, regime_detector):
        """Args:
            indicators: IndicatorEngine instance.
            regime_detector: RegimeDetector instance.
        """
        self.ind = indicators
        self.regime = regime_detector

    # -------------------------------------------------------------------------
    # 3.1 Volatility Assessment
    # -------------------------------------------------------------------------

    def check_iv_rank(self):
        """IV Rank must be above minimum threshold.

        Returns:
            dict: {passed, value, threshold, detail}
        """
        iv_rank = self.ind.iv_rank()
        threshold = cfg.MIN_IV_RANK
        if iv_rank is None:
            return self._result(False, None, threshold,
                                "IV Rank unavailable (insufficient history)")
        passed = iv_rank >= threshold
        return self._result(passed, round(iv_rank, 1), threshold,
                            f"IV Rank {iv_rank:.1f}% vs threshold {threshold}%")

    def check_vix_term_structure(self):
        """VIX term structure must not be in steep backwardation.

        Returns:
            dict: {passed, value, threshold, detail}
        """
        ratio = self.ind.vix_term_structure_ratio()
        threshold = cfg.VIX_TERM_STRUCTURE_THRESHOLD
        if ratio is None:
            return self._result(True, None, threshold,
                                "VIX term structure data unavailable — passing by default")
        passed = ratio < threshold
        state = "contango" if ratio < 1.0 else "backwardation"
        return self._result(passed, round(ratio, 3), threshold,
                            f"VIX term ratio {ratio:.3f} ({state}), "
                            f"threshold <{threshold}")

    def check_iv_hv_ratio(self):
        """Implied volatility should exceed historical volatility.

        Returns:
            dict: {passed, value, threshold, detail}
        """
        current_iv = self.ind.current_iv()
        # HV approximation: we use the std dev from BB as a proxy
        if current_iv is None:
            return self._result(True, None, None,
                                "IV/HV check skipped — no IV data")
        # For now, IV > 0 is a soft check; full HV comparison needs realized vol calc
        return self._result(True, current_iv, None,
                            f"IV {current_iv:.1f} — HV comparison deferred to v2.002")

    # -------------------------------------------------------------------------
    # 3.2 Market Sentiment & Direction
    # -------------------------------------------------------------------------

    def check_trend(self):
        """SPX must be above its trend EMA.

        Returns:
            dict: {passed, value, threshold, detail}
        """
        spx = self.ind.spx_price()
        ema = self.ind.spx_ema()
        if spx is None or ema is None or ema == 0:
            return self._result(False, None, None,
                                "SPX or EMA data unavailable")
        passed = spx > ema
        distance = self.ind.spx_ema_distance_pct()
        return self._result(passed, round(spx, 2), round(ema, 2),
                            f"SPX {spx:,.2f} vs {cfg.TREND_EMA_PERIOD} EMA "
                            f"{ema:,.2f} ({distance:+.1f}%)")

    def check_regime(self):
        """Market regime must be tradeable.

        Returns:
            dict: {passed, value, threshold, detail}
        """
        regime_status = self.regime.get_status()
        passed = self.regime.is_tradeable()
        return self._result(passed, regime_status["regime"], "Tradeable",
                            f"Regime: {regime_status['regime']} "
                            f"(tradeable={passed})")

    # -------------------------------------------------------------------------
    # GLD Signal
    # -------------------------------------------------------------------------

    def assess_gld_signal(self):
        """Assess GLD inverse correlation signal for conviction scoring.

        Returns:
            dict: {signal: GldSignal, conviction_adj: float, detail: str}
        """
        gld_daily = self.ind.gld_daily_change_pct()
        gld_roc = self.ind.gld_roc()
        spx_closes = list(self.ind._spx_closes)
        correlation = self.ind.gld_spx_correlation()

        # Weight adjustment based on correlation strength
        corr_weight = 1.0
        if correlation is not None:
            if correlation > -0.1:
                # Inverse relationship weak/broken — reduce signal weight
                corr_weight = 0.3
            elif correlation > -0.3:
                corr_weight = 0.7

        if gld_daily is None:
            return {
                "signal": GldSignal.NEUTRAL,
                "conviction_adj": 0.0,
                "detail": "GLD data unavailable",
                "correlation": correlation,
                "corr_weight": corr_weight,
            }

        # Is SPX recovering? (latest close > prior close)
        spx_recovering = (len(spx_closes) >= 2
                          and spx_closes[-1] > spx_closes[-2])

        # GLD surging while SPX falling — flight to safety
        if (gld_daily >= cfg.GLD_SURGE_THRESHOLD and not spx_recovering):
            adj = cfg.GLD_CONVICTION_PENALTY_SEVERE * corr_weight
            return self._gld_result(GldSignal.FLIGHT_TO_SAFETY, adj,
                                    f"GLD surging +{gld_daily:.1f}% while SPX falling",
                                    correlation, corr_weight)

        # GLD rising while SPX recovering — caution
        if gld_daily > 0.3 and spx_recovering:
            adj = cfg.GLD_CONVICTION_PENALTY_MILD * corr_weight
            return self._gld_result(GldSignal.CAUTION, adj,
                                    f"GLD rising +{gld_daily:.1f}% during SPX bounce",
                                    correlation, corr_weight)

        # GLD falling while SPX recovering — risk-on rotation
        if gld_daily < -0.3 and spx_recovering:
            adj = cfg.GLD_CONVICTION_BOOST * corr_weight
            return self._gld_result(GldSignal.RISK_ON_ROTATION, adj,
                                    f"GLD falling {gld_daily:.1f}% during SPX bounce "
                                    f"— risk-on rotation",
                                    correlation, corr_weight)

        # Neutral
        return self._gld_result(GldSignal.NEUTRAL, 0.0,
                                f"GLD {gld_daily:+.1f}%, no strong signal",
                                correlation, corr_weight)

    # -------------------------------------------------------------------------
    # Full Assessment
    # -------------------------------------------------------------------------

    def full_assessment(self):
        """Run all market checks and return structured results.

        Returns:
            dict with keys for each check and an overall 'all_passed' flag.
        """
        checks = {
            "regime": self.check_regime(),
            "iv_rank": self.check_iv_rank(),
            "vix_term_structure": self.check_vix_term_structure(),
            "trend": self.check_trend(),
            "gld": self.assess_gld_signal(),
        }
        # All hard gates must pass (GLD is conviction, not a gate)
        gate_checks = ["regime", "iv_rank", "vix_term_structure", "trend"]
        checks["all_passed"] = all(checks[k]["passed"] for k in gate_checks)
        checks["first_failure"] = None
        for k in gate_checks:
            if not checks[k]["passed"]:
                checks["first_failure"] = k
                break
        return checks

    # -------------------------------------------------------------------------
    # Helpers
    # -------------------------------------------------------------------------

    @staticmethod
    def _result(passed, value, threshold, detail):
        return {
            "passed": passed,
            "value": value,
            "threshold": threshold,
            "detail": detail,
        }

    @staticmethod
    def _gld_result(signal, conviction_adj, detail, correlation, corr_weight):
        return {
            "signal": signal,
            "conviction_adj": round(conviction_adj, 3),
            "detail": detail,
            "correlation": round(correlation, 3) if correlation is not None else None,
            "corr_weight": round(corr_weight, 2),
            "passed": True,  # GLD is never a hard gate
        }
