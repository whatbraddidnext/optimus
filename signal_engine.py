# signal_engine.py — Optimus Signal Engine
# Version: v2.001
#
# Multi-gate entry evaluation (HLD Section 4).
# All gates must pass for an entry signal. First failure stops the chain.
# Produces structured diagnostic output for every evaluation.

import config as cfg
from shared.constants import GateResult


class GateEvaluation:
    """Result of a single gate check."""

    def __init__(self, gate_name, result, detail, value=None, threshold=None):
        self.gate_name = gate_name
        self.result = result  # GateResult enum
        self.detail = detail
        self.value = value
        self.threshold = threshold

    @property
    def passed(self):
        return self.result == GateResult.PASS

    def to_log_line(self):
        """Format as a single diagnostic log line."""
        status = self.result.value
        return f"  {self.gate_name}: {self.detail} ({status})"


class EntrySignal:
    """Complete result of an entry evaluation cycle."""

    def __init__(self, underlying, date):
        self.underlying = underlying
        self.date = date
        self.gates = []
        self.triggered = False
        self.first_failure = None

    def add_gate(self, evaluation):
        self.gates.append(evaluation)
        if not evaluation.passed and self.first_failure is None:
            self.first_failure = evaluation.gate_name

    @property
    def all_passed(self):
        return all(g.passed for g in self.gates)

    def to_log(self):
        """Format the full entry evaluation for logging."""
        lines = [f"[ENTRY EVAL] {self.date} | {self.underlying}"]
        for gate in self.gates:
            lines.append(gate.to_log_line())
        if self.triggered:
            lines.append("  >>> SIGNAL: ENTRY TRIGGERED")
        elif self.first_failure:
            fail_gate = next(g for g in self.gates if g.gate_name == self.first_failure)
            lines.append(f"  >>> NO TRADE: {fail_gate.detail}")
            lines.append("  [Remaining gates not evaluated — first failure stops chain]")
        return "\n".join(lines)


class SignalEngine:
    """Evaluates all entry gates for credit spread signals.

    Gate order (evaluated sequentially, stops on first failure):
        1. Market Regime
        2. IV Rank
        3. VIX Term Structure
        4. Trend (SPX > EMA)
        5. Oversold (BB touch within lookback)
        6. Mean Reversion Confirmation (close back above BB + up-closes)
        7. Momentum Confirmation (RSI rising)
        8. Capacity (open positions < max)
        9. Minimum Spacing (business days since last entry)
    """

    VERSION = "v2.001"

    def __init__(self, indicators, market_analyzer, regime_detector,
                 trade_tracker, session_manager):
        self.ind = indicators
        self.market = market_analyzer
        self.regime = regime_detector
        self.tracker = trade_tracker
        self.session = session_manager

    def evaluate(self, underlying, current_date):
        """Run all entry gates for a given underlying.

        Args:
            underlying: Ticker string (e.g. "SPX").
            current_date: Current trading date.

        Returns:
            EntrySignal with full gate evaluation results.
        """
        signal = EntrySignal(underlying, current_date)
        ucfg = cfg.UNDERLYING_CONFIG.get(underlying, {})

        # Gate 1: Market Regime
        regime_check = self.market.check_regime()
        gate = GateEvaluation(
            "Regime", GateResult.PASS if regime_check["passed"] else GateResult.FAIL,
            regime_check["detail"], regime_check["value"], regime_check["threshold"])
        signal.add_gate(gate)
        if not gate.passed:
            return signal

        # Gate 2: IV Rank
        iv_check = self.market.check_iv_rank()
        gate = GateEvaluation(
            "IV Rank", GateResult.PASS if iv_check["passed"] else GateResult.FAIL,
            iv_check["detail"], iv_check["value"], iv_check["threshold"])
        signal.add_gate(gate)
        if not gate.passed:
            return signal

        # Gate 3: VIX Term Structure
        vix_ts_check = self.market.check_vix_term_structure()
        gate = GateEvaluation(
            "VIX Term Structure",
            GateResult.PASS if vix_ts_check["passed"] else GateResult.FAIL,
            vix_ts_check["detail"], vix_ts_check["value"], vix_ts_check["threshold"])
        signal.add_gate(gate)
        if not gate.passed:
            return signal

        # Gate 4: Trend
        trend_check = self.market.check_trend()
        gate = GateEvaluation(
            "Trend", GateResult.PASS if trend_check["passed"] else GateResult.FAIL,
            trend_check["detail"], trend_check["value"], trend_check["threshold"])
        signal.add_gate(gate)
        if not gate.passed:
            return signal

        # Gate 5: Oversold (BB touch)
        touched, bars_ago = self.ind.spx_touched_lower_bb(
            ucfg.get("bb_touch_lookback", cfg.BB_TOUCH_LOOKBACK))
        lower_bb = self.ind.bb_lower()
        spx = self.ind.spx_price()
        if touched:
            detail = (f"Lower BB {lower_bb:,.2f}, touch detected "
                      f"{bars_ago} bar(s) ago")
        else:
            detail = (f"Lower BB {lower_bb:,.2f}, SPX {spx:,.2f} — "
                      f"no touch within {ucfg.get('bb_touch_lookback', cfg.BB_TOUCH_LOOKBACK)} bars")
        gate = GateEvaluation(
            "BB Touch", GateResult.PASS if touched else GateResult.FAIL,
            detail, spx, lower_bb)
        signal.add_gate(gate)
        if not gate.passed:
            return signal

        # Gate 6: Mean Reversion Confirmation
        above_bb = self.ind.spx_above_lower_bb()
        up_closes = self.ind.consecutive_up_closes()
        min_up = ucfg.get("min_consecutive_up_closes", cfg.MIN_CONSECUTIVE_UP_CLOSES)
        confirmed = above_bb and up_closes >= min_up
        detail = (f"Close {'above' if above_bb else 'below'} lower BB, "
                  f"{up_closes} consecutive up-close(s) (min: {min_up})")
        gate = GateEvaluation(
            "Mean Reversion", GateResult.PASS if confirmed else GateResult.FAIL,
            detail, up_closes, min_up)
        signal.add_gate(gate)
        if not gate.passed:
            return signal

        # Gate 7: Momentum Confirmation (RSI)
        rsi_val = self.ind.rsi_current()
        rsi_prev = self.ind.rsi_previous()
        rsi_rising = self.ind.rsi_is_rising()
        detail = (f"RSI {rsi_val:.1f}, prior {rsi_prev:.1f if rsi_prev else 'N/A'} "
                  f"({'rising' if rsi_rising else 'not rising'}, "
                  f"threshold >{cfg.RSI_OVERSOLD_THRESHOLD})")
        gate = GateEvaluation(
            "RSI Momentum", GateResult.PASS if rsi_rising else GateResult.FAIL,
            detail, round(rsi_val, 1), cfg.RSI_OVERSOLD_THRESHOLD)
        signal.add_gate(gate)
        if not gate.passed:
            return signal

        # Gate 8: Capacity
        open_count = self.tracker.open_position_count()
        max_total = cfg.MAX_CONCURRENT_TOTAL
        underlying_count = self.tracker.open_position_count_for(underlying)
        max_per = ucfg.get("max_concurrent", cfg.MAX_CONCURRENT_PER_UNDERLYING)
        capacity_ok = (open_count < max_total and underlying_count < max_per)
        detail = (f"{open_count}/{max_total} total, "
                  f"{underlying_count}/{max_per} {underlying}")
        gate = GateEvaluation(
            "Capacity", GateResult.PASS if capacity_ok else GateResult.FAIL,
            detail, open_count, max_total)
        signal.add_gate(gate)
        if not gate.passed:
            return signal

        # Gate 9: Minimum Spacing
        min_days = ucfg.get("min_days_between_entries", cfg.MIN_DAYS_BETWEEN_ENTRIES)
        days_since = self.tracker.business_days_since_last_entry(
            underlying, current_date)
        spacing_ok = days_since is None or days_since >= min_days
        if days_since is None:
            detail = f"No prior entries for {underlying}"
        else:
            detail = (f"{days_since} business day(s) since last entry "
                      f"(min: {min_days})")
        gate = GateEvaluation(
            "Spacing", GateResult.PASS if spacing_ok else GateResult.FAIL,
            detail, days_since, min_days)
        signal.add_gate(gate)
        if not gate.passed:
            return signal

        # All gates passed
        signal.triggered = True
        return signal
