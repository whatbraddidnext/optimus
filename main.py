# main.py — Optimus Core Algorithm
# Version: v2.001
#
# Systematic options premium selling strategy.
# Sells put credit spreads on SPX using Bollinger Band mean reversion
# entry timing with multi-gate confirmation.
#
# QuantConnect (LEAN) + Interactive Brokers
# Stargaze Capital — Phase 2

from AlgorithmImports import *
import config as cfg
from indicators import IndicatorEngine
from regime_detector import RegimeDetector
from market_analyzer import MarketAnalyzer
from signal_engine import SignalEngine
from spread_builder import SpreadBuilder
from conviction_scorer import ConvictionScorer
from position_sizer import PositionSizer
from risk_manager import RiskManager
from execution_manager import ExecutionManager
from trade_tracker import TradeTracker
from session_manager import SessionManager
from notifications import NotificationManager
from diagnostics import Diagnostics
from shared.constants import Regime, ExitReason


class Optimus(QCAlgorithm):
    """Optimus — Systematic Options Premium Selling Algorithm.

    Strategy: Sell put credit spreads on SPX when market is oversold
    (Bollinger Band touch) and confirmed recovering (mean reversion).
    Mechanical exits at 50% profit, 200% stop loss, or 21 DTE.
    """

    VERSION = cfg.STRATEGY_VERSION

    def initialize(self):
        """QuantConnect initialisation — runs once at start."""
        self.set_start_date(2020, 1, 1)
        self.set_end_date(2025, 12, 31)
        self.set_cash(500_000)
        self.set_brokerage_model(BrokerageName.INTERACTIVE_BROKERS_BROKERAGE,
                                 AccountType.MARGIN)

        self.log(f"[INIT] {cfg.STRATEGY_NAME} {cfg.STRATEGY_VERSION} initialising")

        # -------------------------------------------------------------------
        # Data subscriptions
        # -------------------------------------------------------------------
        self._spx = self.add_index("SPX", Resolution.DAILY)
        self._spx.symbol_name = "SPX"

        # SPX options
        self._spx_option = self.add_index_option("SPX", Resolution.DAILY)
        self._spx_option.set_filter(self._option_filter)

        # VIX for regime detection
        self._vix = self.add_data(CBOE, "VIX", Resolution.DAILY)

        # GLD for inverse correlation signal
        self._gld = self.add_equity("GLD", Resolution.DAILY)

        # -------------------------------------------------------------------
        # Indicators (registered with QC for automatic updates)
        # Note: QC methods .BB(), .RSI(), .EMA() return indicator objects.
        # We store them with distinct names to avoid shadowing the methods.
        # -------------------------------------------------------------------
        self.bb = self.BB(
            self._spx.symbol, cfg.BB_PERIOD, cfg.BB_STD_DEV,
            MovingAverageType.SIMPLE, Resolution.DAILY)

        self.rsi = self.RSI(
            self._spx.symbol, cfg.RSI_PERIOD, MovingAverageType.WILDERS,
            Resolution.DAILY)

        self.spx_ema = self.EMA(
            self._spx.symbol, cfg.TREND_EMA_PERIOD, Resolution.DAILY)

        self.gld_ema = self.EMA(
            self._gld.symbol, cfg.GLD_TREND_EMA, Resolution.DAILY)

        # -------------------------------------------------------------------
        # Internal state
        # -------------------------------------------------------------------
        self._prev_rsi = None
        self._current_vix = None
        self._vix_term_ratio = None
        self._peak_equity = self.portfolio.total_portfolio_value
        self._entry_pending = False  # Signal fired, waiting for execution window

        # -------------------------------------------------------------------
        # Module initialisation
        # -------------------------------------------------------------------
        self._indicators = IndicatorEngine(self)
        self._regime = RegimeDetector(self._indicators)
        self._market = MarketAnalyzer(self._indicators, self._regime)
        self._tracker = TradeTracker(self)
        self._session = SessionManager(self)
        self._signal = SignalEngine(
            self._indicators, self._market, self._regime,
            self._tracker, self._session)
        self._builder = SpreadBuilder(self)
        self._conviction = ConvictionScorer(
            self._indicators, self._market, self._tracker)
        self._sizer = PositionSizer(self, self._regime)
        self._risk = RiskManager(self, self._tracker, self._regime,
                                 self._indicators)
        self._execution = ExecutionManager(self)
        self._notifications = NotificationManager(self)
        self._diagnostics = Diagnostics(
            self, self._indicators, self._regime, self._tracker, self._risk)

        # -------------------------------------------------------------------
        # Warmup
        # -------------------------------------------------------------------
        self.set_warm_up(timedelta(days=cfg.WARMUP_PERIOD_DAYS))

        # -------------------------------------------------------------------
        # Scheduled events
        # -------------------------------------------------------------------
        # Daily entry evaluation after market open
        self.schedule.on(
            self.date_rules.every_day(self._spx.symbol),
            self.time_rules.after_market_open(self._spx.symbol, 31),
            self._on_daily_evaluation)

        # Daily exit check
        self.schedule.on(
            self.date_rules.every_day(self._spx.symbol),
            self.time_rules.after_market_open(self._spx.symbol, 5),
            self._on_daily_exit_check)

        # End of day dashboard
        self.schedule.on(
            self.date_rules.every_day(self._spx.symbol),
            self.time_rules.before_market_close(self._spx.symbol, 5),
            self._on_end_of_day)

        self.log(f"[INIT] {cfg.STRATEGY_NAME} {cfg.STRATEGY_VERSION} "
                 f"initialisation complete")

    # =========================================================================
    # OPTION CHAIN FILTER
    # =========================================================================

    def _option_filter(self, universe):
        """Filter option chain for relevant strikes and expirations."""
        return (universe
                .strikes(-30, 0)  # OTM puts only (below current price)
                .expiration(timedelta(days=cfg.MIN_DTE_ENTRY),
                            timedelta(days=cfg.MAX_DTE_ENTRY))
                .include_weeklys())

    # =========================================================================
    # DATA EVENT HANDLERS
    # =========================================================================

    def on_data(self, data):
        """Called on every data event. Updates indicators and state."""
        if self.is_warming_up:
            bars = self._indicators.bars_until_ready()
            if bars > 0 and bars % 50 == 0:
                self.log(f"[WARMUP] Indicators not ready, "
                         f"~{bars} bars remaining")
            return

        # Mark warmup complete on first real bar
        if not self._indicators._warmup_complete:
            self._indicators.mark_warmup_complete()
            self.log("[WARMUP] Complete — trading enabled")

        # Update SPX price history
        if data.contains_key(self._spx.symbol):
            bar = data[self._spx.symbol]
            self._indicators.update_spx_close(bar.close)
            self._indicators.update_spx_return()

        # Update VIX
        if data.contains_key("VIX"):
            self._current_vix = data["VIX"].value

        # Update GLD
        if data.contains_key(self._gld.symbol):
            gld_bar = data[self._gld.symbol]
            self._indicators.update_gld_close(gld_bar.close)

        # Update IV from options chain (use ATM put IV as proxy)
        chain = data.option_chains.get(self._spx_option.symbol)
        if chain:
            self._update_iv_from_chain(chain)
            self._update_position_greeks(chain)

        # Store previous RSI for momentum check
        if self.rsi.is_ready:
            prev = self._prev_rsi
            self._prev_rsi = self.rsi.current.value

        # Check for pending execution
        if self._entry_pending and self._session.is_execution_window():
            self._execute_pending_entry(data)

    def _update_iv_from_chain(self, chain):
        """Extract current IV from options chain (ATM put)."""
        spx_price = self._indicators.spx_price()
        if spx_price is None:
            return

        best_contract = None
        best_diff = float('inf')
        for contract in chain:
            if contract.right == 1:  # Put
                diff = abs(contract.strike - spx_price)
                if diff < best_diff:
                    best_diff = diff
                    best_contract = contract

        if best_contract and best_contract.implied_volatility:
            self._indicators.update_iv(
                best_contract.implied_volatility * 100)

    def _update_position_greeks(self, chain):
        """Update Greeks for open positions from live chain data."""
        for pos in self._tracker.open_positions():
            short_strike = pos["short_strike"]
            expiry = pos["expiry"]

            for contract in chain:
                if (contract.strike == short_strike
                        and contract.expiry == expiry
                        and contract.right == 1):
                    current_mid = (contract.bid_price + contract.ask_price) / 2
                    # Find the long leg value
                    long_strike = pos["long_strike"]
                    for lc in chain:
                        if (lc.strike == long_strike
                                and lc.expiry == expiry
                                and lc.right == 1):
                            long_mid = (lc.bid_price + lc.ask_price) / 2
                            spread_value = current_mid - long_mid
                            dte = self._session.current_dte(expiry)
                            self._tracker.update_position(
                                pos["id"],
                                current_spread_value=max(spread_value, 0),
                                dte_remaining=dte,
                                current_delta=contract.greeks.delta if contract.greeks else None,
                                current_theta=contract.greeks.theta if contract.greeks else None,
                            )
                            break
                    break

    # =========================================================================
    # SCHEDULED EVENT: DAILY ENTRY EVALUATION
    # =========================================================================

    def _on_daily_evaluation(self):
        """Daily entry signal evaluation — runs after market open."""
        if self.is_warming_up:
            return

        if not self._indicators.is_ready():
            self.log("[EVAL] Indicators not ready — skipping")
            return

        # Update regime
        self._regime.update()

        # Check for regime change notification
        if self._regime.regime_changed():
            self._notifications.notify_regime_shift(
                self._regime.previous_regime.value,
                self._regime.current_regime.value)

        # Evaluate entry for each configured underlying
        for underlying in cfg.UNDERLYING_CONFIG:
            self._evaluate_entry(underlying)

        # Log daily dashboard
        if cfg.LOG_DAILY_DASHBOARD:
            dashboard = self._diagnostics.daily_dashboard()
            self.log(dashboard)

    def _evaluate_entry(self, underlying):
        """Evaluate entry gates for a single underlying."""
        current_date = self.time.date()
        signal = self._signal.evaluate(underlying, current_date)

        # Log the evaluation
        if cfg.LOG_ENTRY_EVALS:
            self.log(self._diagnostics.log_entry_eval(signal))

        if signal.triggered:
            self._entry_pending = True
            self._pending_underlying = underlying
            self._pending_signal = signal
            self.log(f"[SIGNAL] Entry triggered for {underlying} — "
                     f"awaiting execution window")

            # If already in execution window, execute immediately
            if self._session.is_execution_window():
                self._execute_pending_entry(None)
        else:
            # Log unfavourable conditions
            no_trade_log = self._diagnostics.log_no_trade(
                underlying, signal)
            if cfg.LOG_ENTRY_EVALS:
                self.log(no_trade_log)

    # =========================================================================
    # TRADE EXECUTION
    # =========================================================================

    def _execute_pending_entry(self, data):
        """Execute a pending entry signal."""
        if not self._entry_pending:
            return

        underlying = self._pending_underlying
        self._entry_pending = False

        # Get options chain
        chain = None
        if data and data.option_chains:
            chain = data.option_chains.get(self._spx_option.symbol)
        if chain is None:
            # Try to get from slice
            chain = self.current_slice.option_chains.get(
                self._spx_option.symbol) if hasattr(self, 'current_slice') else None
        if chain is None:
            self.log(f"[EXEC] No options chain available for {underlying} "
                     f"— skipping execution")
            return

        # Build spread
        spread = self._builder.build_put_credit_spread(underlying, chain)
        if spread is None:
            self.log(f"[EXEC] Could not build spread for {underlying}")
            return

        # Score conviction
        conviction = self._conviction.score()
        self.log(self._conviction.to_log(conviction))

        # Size position
        equity = self.portfolio.total_portfolio_value
        drawdown = self._risk.current_drawdown()
        sizing = self._sizer.calculate(spread, conviction, equity, drawdown)

        if sizing["contracts"] <= 0:
            self.log(f"[EXEC] Position size is 0 — {sizing['detail']}")
            return

        # Risk manager approval (final gate)
        approval = self._risk.approve_entry(sizing, self.time.date())
        if not approval["approved"]:
            self.log(f"[RISK VETO] {approval['reason']}")
            self._notifications.notify_risk_veto(approval["reason"])
            return

        # Open position in tracker
        position_id = self._tracker.open_position(
            spread, sizing["contracts"], sizing, conviction, self.time.date())

        # Submit orders
        result = self._execution.open_spread(
            spread, sizing["contracts"], position_id)

        if result["success"]:
            # Log trade details
            total_heat = self._tracker.total_portfolio_heat()
            heat_pct = (total_heat / equity * 100) if equity > 0 else 0
            trade_log = spread.to_log(sizing["contracts"], equity, heat_pct)
            self.log(trade_log)
            self._notifications.notify_trade_opened(
                trade_log, self._conviction.to_log(conviction))
        else:
            self.log(f"[EXEC] Order failed — {result['detail']}")
            # Remove from tracker since order didn't go through
            self._tracker._open_positions.pop(position_id, None)

    # =========================================================================
    # SCHEDULED EVENT: DAILY EXIT CHECK
    # =========================================================================

    def _on_daily_exit_check(self):
        """Check all open positions for exit conditions."""
        if self.is_warming_up:
            return

        exits = self._risk.evaluate_exits(self.time.date())

        for exit_info in exits:
            position = None
            for pos in self._tracker.open_positions():
                if pos["id"] == exit_info["position_id"]:
                    position = pos
                    break

            if position is None:
                continue

            # Execute close
            close_result = self._execution.close_spread(
                position, exit_info["reason"])

            if close_result["success"]:
                # Estimate exit credit from current spread value
                exit_credit = position.get("current_spread_value", 0)
                trade = self._tracker.close_position(
                    position["id"], exit_info["reason"],
                    exit_credit, self.time.date())

                if trade:
                    # Log the close
                    trade_log = self._tracker.log_trade_closed(trade)
                    self.log(trade_log)
                    self._notifications.notify_trade_closed(trade_log)

                    # Record for circuit breaker
                    self._risk.record_trade_result(
                        exit_info["reason"], self.time.date())

                    # Check circuit breaker activation
                    if self._risk.circuit_breaker_active:
                        self._notifications.notify_circuit_breaker(
                            f"Circuit breaker activated after "
                            f"{self._risk.consecutive_max_losses} "
                            f"consecutive max losses")
            else:
                self.log(f"[EXIT] Close failed for {position['id']} — "
                         f"{close_result['detail']}")

    # =========================================================================
    # SCHEDULED EVENT: END OF DAY
    # =========================================================================

    def _on_end_of_day(self):
        """End of day processing — dashboard and housekeeping."""
        if self.is_warming_up:
            return

        # Update peak equity for drawdown tracking
        equity = self.portfolio.total_portfolio_value
        if equity > self._peak_equity:
            self._peak_equity = equity

        # Check for pending order fills
        self._execution.check_pending_orders()

    # =========================================================================
    # ORDER EVENT
    # =========================================================================

    def on_order_event(self, order_event):
        """Handle order fill events."""
        if order_event.status == OrderStatus.FILLED:
            self.log(f"[ORDER] Filled: {order_event.symbol} "
                     f"Qty: {order_event.fill_quantity} "
                     f"@ ${order_event.fill_price:.2f}")
        elif order_event.status == OrderStatus.CANCELED:
            self.log(f"[ORDER] Cancelled: {order_event.symbol}")
        elif order_event.status == OrderStatus.INVALID:
            self.log(f"[ORDER] Invalid: {order_event.symbol} "
                     f"— {order_event.message}")

    # =========================================================================
    # END OF ALGORITHM
    # =========================================================================

    def on_end_of_algorithm(self):
        """Final summary when backtest/live session ends."""
        summary = self._diagnostics.performance_summary()
        self.log(summary)
        self.log(f"[END] {cfg.STRATEGY_NAME} {cfg.STRATEGY_VERSION} complete")
