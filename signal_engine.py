# signal_engine.py — Optimus v2.0-MVP
# Multi-gate entry system — all gates must pass before entry signal fires
# Deterministic: same inputs always produce same outputs

MODULE_VERSION = "1.0"


class GateResult:
    """Result of a single gate evaluation."""

    def __init__(self, gate_name, passed, reason=None):
        self.gate_name = gate_name
        self.passed = passed
        self.reason = reason

    def __repr__(self):
        status = "PASS" if self.passed else "FAIL"
        msg = f" ({self.reason})" if self.reason else ""
        return f"{self.gate_name}: {status}{msg}"


class EntrySignal:
    """Complete entry signal with gate audit trail."""

    def __init__(self, asset_key, passed, gates, call_delta=None, put_delta=None,
                 trend_score=None, iv_rank=None, regime=None):
        self.asset_key = asset_key
        self.passed = passed
        self.gates = gates
        self.call_delta = call_delta
        self.put_delta = put_delta
        self.trend_score = trend_score
        self.iv_rank = iv_rank
        self.regime = regime

    @property
    def rejection_reason(self):
        if self.passed:
            return None
        failed = [g for g in self.gates if not g.passed]
        return failed[0].reason if failed else "unknown"

    def summary(self):
        status = "ENTRY" if self.passed else "SKIP"
        gates_str = ", ".join(str(g) for g in self.gates)
        return f"{self.asset_key} {status}: [{gates_str}]"


class SignalEngine:
    """Multi-gate entry evaluation for a single underlying.

    Gates (evaluated sequentially, short-circuit on failure):
    1. Regime — must be RANGING or LOW_VOL (TRENDING conditional)
    2. IV Rank — within [min, max] per asset
    3. DTE Availability — chain exists in DTE range
    4. Margin Available — below margin cap
    5. Concurrent Limit — below max_concurrent
    6. Stagger Check — existing position old enough
    7. Trend Score Valid — not in suppression zone
    8. Risk State — not in any halt state
    """

    def __init__(self, global_config):
        self.config = global_config

    def evaluate(self, asset_key, asset_config, regime_detector, trend_engine,
                 iv_rank, has_chain, risk_manager, margin_used_pct,
                 open_positions_on_asset, youngest_position_age_days):
        """Evaluate all entry gates for a single asset.

        Args:
            asset_key: e.g. "ES"
            asset_config: Per-asset config dict
            regime_detector: RegimeDetector instance for this asset
            trend_engine: TrendGradientEngine instance
            iv_rank: Current IV Rank (0-100) or None
            has_chain: Whether options chain is available in DTE range
            risk_manager: RiskManager instance
            margin_used_pct: Current margin utilisation (0-1)
            open_positions_on_asset: Count of open positions on this asset
            youngest_position_age_days: Age of newest position on this asset (or None)

        Returns:
            EntrySignal with pass/fail and gate audit trail
        """
        gates = []
        trend_score = trend_engine.trend_score if trend_engine.is_ready else 0.0

        # Gate 1: Regime
        gate = self._check_regime(regime_detector, trend_score)
        gates.append(gate)
        if not gate.passed:
            return self._signal(asset_key, False, gates, trend_score, iv_rank,
                                regime_detector.current_regime)

        # Gate 2: IV Rank
        gate = self._check_iv_rank(iv_rank, asset_config)
        gates.append(gate)
        if not gate.passed:
            return self._signal(asset_key, False, gates, trend_score, iv_rank,
                                regime_detector.current_regime)

        # Gate 3: DTE Availability
        gate = self._check_chain(has_chain)
        gates.append(gate)
        if not gate.passed:
            return self._signal(asset_key, False, gates, trend_score, iv_rank,
                                regime_detector.current_regime)

        # Gate 4: Risk State
        gate = self._check_risk_state(risk_manager, margin_used_pct)
        gates.append(gate)
        if not gate.passed:
            return self._signal(asset_key, False, gates, trend_score, iv_rank,
                                regime_detector.current_regime)

        # Gate 5: Concurrent Limit
        gate = self._check_concurrent(open_positions_on_asset, asset_config)
        gates.append(gate)
        if not gate.passed:
            return self._signal(asset_key, False, gates, trend_score, iv_rank,
                                regime_detector.current_regime)

        # Gate 6: Stagger Check
        gate = self._check_stagger(youngest_position_age_days, open_positions_on_asset)
        gates.append(gate)
        if not gate.passed:
            return self._signal(asset_key, False, gates, trend_score, iv_rank,
                                regime_detector.current_regime)

        # Gate 7: Trend Score Valid
        gate = self._check_trend_suppress(trend_engine, iv_rank)
        gates.append(gate)
        if not gate.passed:
            return self._signal(asset_key, False, gates, trend_score, iv_rank,
                                regime_detector.current_regime)

        # All gates passed — calculate delta targets
        call_delta, put_delta = trend_engine.get_delta_targets(asset_config)

        return self._signal(asset_key, True, gates, trend_score, iv_rank,
                            regime_detector.current_regime, call_delta, put_delta)

    def _check_regime(self, regime_detector, trend_score):
        """Gate 1: Regime must allow entry."""
        if regime_detector.allows_entry:
            return GateResult("Regime", True)
        if regime_detector.allows_conditional_entry:
            # TRENDING: allow only if trend score is moderate (skew can handle it)
            if abs(trend_score) < 0.8:
                return GateResult("Regime", True, "TRENDING with moderate skew")
            return GateResult("Regime", False,
                              f"TRENDING with extreme score {trend_score:.2f}")
        return GateResult("Regime", False,
                          f"regime={regime_detector.current_regime}")

    def _check_iv_rank(self, iv_rank, asset_config):
        """Gate 2: IV Rank within asset's min/max range."""
        if iv_rank is None:
            return GateResult("IV Rank", False, "IV rank not available")
        min_iv = asset_config["min_iv_rank"]
        max_iv = asset_config["max_iv_rank"]
        if min_iv <= iv_rank <= max_iv:
            return GateResult("IV Rank", True)
        return GateResult("IV Rank", False,
                          f"IV rank {iv_rank:.0f} outside [{min_iv}, {max_iv}]")

    def _check_chain(self, has_chain):
        """Gate 3: Options chain available in DTE range."""
        if has_chain:
            return GateResult("DTE Chain", True)
        return GateResult("DTE Chain", False, "no chain in DTE range")

    def _check_risk_state(self, risk_manager, margin_used_pct):
        """Gate 4: Risk state and margin allow new entry."""
        allowed, reason = risk_manager.can_enter_new_trade(margin_used_pct)
        return GateResult("Risk/Margin", allowed, reason)

    def _check_concurrent(self, open_count, asset_config):
        """Gate 5: Below max concurrent positions for this asset."""
        max_concurrent = asset_config["max_concurrent"]
        if open_count < max_concurrent:
            return GateResult("Concurrent", True)
        return GateResult("Concurrent", False,
                          f"{open_count}/{max_concurrent} positions on asset")

    def _check_stagger(self, youngest_age, open_count):
        """Gate 6: Existing position old enough for staggering."""
        if open_count == 0:
            return GateResult("Stagger", True, "no existing positions")
        min_age = self.config["stagger_min_days"]
        if youngest_age is None:
            return GateResult("Stagger", False, "position age unknown")
        if youngest_age >= min_age:
            return GateResult("Stagger", True)
        return GateResult("Stagger", False,
                          f"youngest position {youngest_age}d < {min_age}d minimum")

    def _check_trend_suppress(self, trend_engine, iv_rank):
        """Gate 7: Trend not too strong with too little premium."""
        suppress_threshold = self.config["trend_score_suppress"]
        iv_threshold = self.config["trend_score_suppress_iv"]
        if trend_engine.should_suppress_entry(iv_rank, suppress_threshold, iv_threshold):
            score = trend_engine.trend_score
            return GateResult("Trend Suppress", False,
                              f"score {score:.2f} with IV rank {iv_rank:.0f}")
        return GateResult("Trend Suppress", True)

    def _signal(self, asset_key, passed, gates, trend_score, iv_rank, regime,
                call_delta=None, put_delta=None):
        return EntrySignal(
            asset_key=asset_key,
            passed=passed,
            gates=gates,
            call_delta=call_delta,
            put_delta=put_delta,
            trend_score=trend_score,
            iv_rank=iv_rank,
            regime=regime,
        )
