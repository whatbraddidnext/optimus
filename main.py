# main.py — Optimus v2.0-MVP
# QC Algorithm orchestration: warmup, data subscriptions, event handlers
# /ES Iron Condors only. All modules wired together here.

# region imports
from AlgorithmImports import *

from config import ASSET_CONFIG, GLOBAL, ACTIVE_ASSETS
from indicators import (
    IVRankTracker, ATRCalculator, ADXCalculator,
    RealisedVolCalculator, SMACalculator, BandwidthTracker,
)
from trend_gradient import TrendGradientEngine
from regime_detector import RegimeDetector
from options_chain_manager import OptionsChainManager
from signal_engine import SignalEngine
from position_sizer import PositionSizer
from risk_manager import RiskManager
from execution_manager import ExecutionManager
from position_manager import PositionManager
from trade_tracker import TradeTracker
# endregion

ALGORITHM_VERSION = "v2.0-MVP"


class Optimus(QCAlgorithm):
    """Systematic futures options premium selling — iron condors on /ES.

    Core loop:
    1. Daily 15:00 ET: scan for entry signals (all gates must pass)
    2. Twice daily (10:00, 15:00 ET): manage open positions (exit evaluation)
    3. Continuous: indicator updates, regime detection
    """

    def initialize(self):
        self.set_start_date(2021, 1, 1)
        self.set_end_date(2024, 12, 31)
        self.set_cash(GLOBAL["initial_capital"])
        self.set_brokerage_model(BrokerageName.InteractiveBrokersBrokerage, AccountType.Margin)

        self.debug(f"[INIT] Optimus {ALGORITHM_VERSION} initialising")

        # ── Data subscriptions ──────────────────────────────────────
        self._futures = {}
        self._future_options = {}
        self._option_chains = {}
        self._vix = None

        for asset_key in ACTIVE_ASSETS:
            cfg = ASSET_CONFIG[asset_key]

            # Subscribe to the continuous futures contract
            future = self.add_future(
                cfg["future_ticker"],
                resolution=Resolution.DAILY,
                data_normalization_mode=DataNormalizationMode.BACKWARDS_RATIO,
                data_mapping_mode=DataMappingMode.OPEN_INTEREST,
                contract_depth_offset=0,
            )
            future.set_filter(lambda u: u.front_month())
            self._futures[asset_key] = future

            self.debug(f"[INIT] Subscribed to {asset_key} futures: {future.symbol}")

        # VIX for ES crisis detection
        self._vix = self.add_data(CBOE, "VIX", Resolution.DAILY).symbol

        # ── Indicator instances (per asset) ─────────────────────────
        self._indicators = {}
        for asset_key in ACTIVE_ASSETS:
            cfg = ASSET_CONFIG[asset_key]
            self._indicators[asset_key] = {
                "iv_rank": IVRankTracker(lookback=252),
                "atr": ATRCalculator(
                    period=14,
                    floor_pct=GLOBAL["atr_floor_pct"],
                    floor_lookback=100,
                ),
                "adx": ADXCalculator(period=14),
                "rv": RealisedVolCalculator(short_window=5, long_window=20, extended_window=60),
                "sma": SMACalculator(period=20),
                "bandwidth": BandwidthTracker(period=20, std_dev=2.0, percentile_lookback=252),
                "trend": TrendGradientEngine(
                    primary_lookback=cfg["trend_lookback_days"],
                    confirm_lookback=cfg["trend_confirm_lookback_days"],
                    scaling_factor=GLOBAL["trend_scaling_factor"],
                ),
            }

        # ── Strategy modules ────────────────────────────────────────
        self._regime_detectors = {}
        for asset_key in ACTIVE_ASSETS:
            self._regime_detectors[asset_key] = RegimeDetector(
                asset_key, ASSET_CONFIG[asset_key], GLOBAL
            )

        self._chain_managers = {}
        for asset_key in ACTIVE_ASSETS:
            self._chain_managers[asset_key] = OptionsChainManager(
                self, ASSET_CONFIG[asset_key]
            )

        self._signal_engine = SignalEngine(GLOBAL)
        self._position_sizer = PositionSizer(GLOBAL)
        self._risk_manager = RiskManager(GLOBAL)
        self._execution_manager = ExecutionManager(self)
        self._position_manager = PositionManager(GLOBAL)
        self._trade_tracker = TradeTracker(self)

        # ── Warmup ──────────────────────────────────────────────────
        self.set_warmup(timedelta(days=GLOBAL["warmup_days"]))

        # ── Scheduled events ────────────────────────────────────────
        # Entry scan: daily at 15:00 ET
        self.schedule.on(
            self.date_rules.every_day(),
            self.time_rules.at(GLOBAL["entry_scan_hour"], 0),
            self._on_entry_scan,
        )

        # Management scan: 10:00 ET
        self.schedule.on(
            self.date_rules.every_day(),
            self.time_rules.at(GLOBAL["management_hours"][0], 0),
            self._on_management_scan,
        )

        # Management scan: 15:00 ET (runs before entry scan in same hour)
        self.schedule.on(
            self.date_rules.every_day(),
            self.time_rules.at(GLOBAL["management_hours"][1], 0),
            self._on_management_scan,
        )

        # Daily summary at 16:00 ET
        self.schedule.on(
            self.date_rules.every_day(),
            self.time_rules.at(16, 0),
            self._on_daily_summary,
        )

        # Track session open price for catastrophic stop
        self._session_open = {}

        # Track mapped contract symbols for futures options subscription
        self._mapped_contracts = {}

        self.debug(f"[INIT] Optimus {ALGORITHM_VERSION} initialisation complete")

    def on_data(self, data):
        """Process incoming data — update indicators, subscribe to options."""
        if self.is_warming_up:
            self._update_indicators(data)
            return

        self._update_indicators(data)

        # Subscribe to futures options when we get a mapped contract
        for asset_key in ACTIVE_ASSETS:
            future = self._futures[asset_key]
            mapped = future.mapped
            if mapped is None:
                continue

            if asset_key not in self._mapped_contracts or self._mapped_contracts[asset_key] != mapped:
                self._mapped_contracts[asset_key] = mapped
                # Add futures options for the current front-month contract
                option = self.add_future_option(
                    mapped,
                    lambda u: u.strikes(-50, 50)
                              .expiration(
                                  ASSET_CONFIG[asset_key]["min_dte_entry"],
                                  ASSET_CONFIG[asset_key]["max_dte_entry"] + 10,
                              ),
                )
                self._future_options[asset_key] = option
                self.debug(f"[DATA] Subscribed to {asset_key} options on {mapped}")

    def _update_indicators(self, data):
        """Update all indicators with latest bar data."""
        for asset_key in ACTIVE_ASSETS:
            future = self._futures[asset_key]
            mapped = future.mapped

            if mapped is None or not data.contains_key(mapped):
                continue

            bar = data[mapped]
            if bar is None:
                continue

            close = float(bar.close)
            high = float(bar.high)
            low = float(bar.low)

            ind = self._indicators[asset_key]

            # Update core indicators
            ind["atr"].update(high, low, close)
            ind["adx"].update(high, low, close)
            ind["rv"].update(close)
            ind["sma"].update(close)
            ind["bandwidth"].update(close)

            # Update trend gradient (needs ATR)
            atr_val = ind["atr"].value
            ind["trend"].update(close, atr_val)

            # Track session open for catastrophic stop
            self._session_open[asset_key] = float(bar.open)

            # Update IV rank from options chain if available
            self._update_iv_rank(asset_key, data)

            # Update regime detector
            self._update_regime(asset_key, data, close)

    def _update_iv_rank(self, asset_key, data):
        """Extract ATM IV from options chain and update IV rank tracker."""
        if asset_key not in self._future_options:
            return

        chain = self._get_option_chain(asset_key)
        if chain is None or len(list(chain)) == 0:
            return

        # Find ATM option (closest strike to current price)
        future = self._futures[asset_key]
        if future.mapped is None:
            return
        security = self.securities.get(future.mapped)
        if security is None:
            return
        current_price = float(security.price)
        if current_price <= 0:
            return

        # Get ATM call IV
        best_contract = None
        best_diff = float("inf")
        for contract in chain:
            if contract.right != OptionRight.Call:
                continue
            diff = abs(float(contract.strike) - current_price)
            if diff < best_diff:
                best_diff = diff
                best_contract = contract

        if best_contract is not None and best_contract.greeks is not None:
            iv = best_contract.greeks.implied_volatility
            if iv is not None and iv > 0:
                self._indicators[asset_key]["iv_rank"].update(iv)

    def _update_regime(self, asset_key, data, current_price):
        """Update regime detector with current indicator values."""
        ind = self._indicators[asset_key]

        adx = ind["adx"].value
        atr = ind["atr"].value
        sma = ind["sma"].value
        bandwidth = ind["bandwidth"].value
        bandwidth_pctl_20 = ind["bandwidth"].percentile(20)
        rv_short = ind["rv"].short_rv
        rv_long = ind["rv"].long_rv
        rv_extended = ind["rv"].extended_rv

        # Session move for HIGH_VOL detection
        session_move_pct = None
        if asset_key in self._session_open and self._session_open[asset_key] > 0:
            session_move_pct = ((current_price - self._session_open[asset_key])
                                / self._session_open[asset_key] * 100)

        # VIX for ES crisis detection
        vix = None
        if asset_key == "ES" and self._vix is not None:
            vix_data = self.securities.get(self._vix)
            if vix_data is not None and vix_data.price > 0:
                vix = float(vix_data.price)

        self._regime_detectors[asset_key].update(
            adx=adx, atr=atr, sma=sma,
            bandwidth=bandwidth, bandwidth_pctl_20=bandwidth_pctl_20,
            current_price=current_price,
            rv_short=rv_short, rv_long=rv_long, rv_extended=rv_extended,
            session_move_pct=session_move_pct, vix=vix,
        )

    def _get_option_chain(self, asset_key):
        """Get current options chain for an asset. Returns iterable or None."""
        if asset_key not in self._future_options:
            return None
        option = self._future_options[asset_key]
        chain = self.option_chain(option.symbol)
        if chain is None:
            return None
        return chain

    # ── Scheduled Event Handlers ────────────────────────────────────

    def _on_entry_scan(self):
        """Daily entry scan at 15:00 ET. Evaluate all assets for new trades."""
        if self.is_warming_up:
            return

        for asset_key in ACTIVE_ASSETS:
            self._evaluate_entry(asset_key)

    def _evaluate_entry(self, asset_key):
        """Run the multi-gate entry system for one asset."""
        cfg = ASSET_CONFIG[asset_key]
        ind = self._indicators[asset_key]

        # Check indicators are ready
        if not all([
            ind["atr"].is_ready,
            ind["adx"].is_ready,
            ind["trend"].is_ready,
        ]):
            self.debug(f"[ENTRY] {asset_key}: indicators not ready, skipping")
            return

        # Check if options chain is available
        chain = self._get_option_chain(asset_key)
        has_chain = chain is not None and len(list(chain)) > 0
        # Re-fetch chain since we consumed the iterator
        if has_chain:
            chain = self._get_option_chain(asset_key)

        # Current state
        iv_rank = ind["iv_rank"].iv_rank
        open_count = self._position_manager.get_open_count(asset_key)
        youngest_age = self._position_manager.get_youngest_position_age(
            asset_key, self.time
        )

        # Estimate margin utilisation (simplified for MVP)
        equity = self.portfolio.total_portfolio_value
        margin_used = self.portfolio.total_margin_used if hasattr(self.portfolio, "total_margin_used") else 0
        margin_pct = margin_used / equity if equity > 0 else 0

        # Evaluate all gates
        signal = self._signal_engine.evaluate(
            asset_key=asset_key,
            asset_config=cfg,
            regime_detector=self._regime_detectors[asset_key],
            trend_engine=ind["trend"],
            iv_rank=iv_rank,
            has_chain=has_chain,
            risk_manager=self._risk_manager,
            margin_used_pct=margin_pct,
            open_positions_on_asset=open_count,
            youngest_position_age_days=youngest_age,
        )

        if not signal.passed:
            self._trade_tracker.log_skip(signal)
            return

        # Build iron condor
        ic_legs, reject_reason = self._chain_managers[asset_key].build_iron_condor(
            option_chain=chain,
            call_delta=signal.call_delta,
            put_delta=signal.put_delta,
            min_dte=cfg["min_dte_entry"],
            max_dte=cfg["max_dte_entry"],
        )

        if ic_legs is None:
            self.debug(f"[ENTRY] {asset_key}: IC construction failed: {reject_reason}")
            return

        # Size the position
        aggregate_risk = self._position_manager.get_aggregate_risk()
        total_positions = self._position_manager.get_open_count()

        contracts, size_reason = self._position_sizer.size_iron_condor(
            equity=equity,
            max_loss_per_contract=ic_legs.max_loss,
            current_aggregate_risk=aggregate_risk,
            current_position_count=total_positions,
        )

        if contracts == 0:
            self.debug(f"[ENTRY] {asset_key}: sizing rejected: {size_reason}")
            return

        # Submit orders
        tickets = self._execution_manager.submit_iron_condor_entry(ic_legs, contracts)
        if tickets is None:
            self.debug(f"[ENTRY] {asset_key}: order submission failed")
            return

        # Create position record
        pos_id = self._position_manager.create_position(
            asset_key=asset_key,
            asset_config=cfg,
            ic_legs=ic_legs,
            contracts=contracts,
            trend_score=signal.trend_score,
            iv_rank=signal.iv_rank,
            regime=signal.regime,
            current_time=self.time,
        )

        # Log the trade
        position_state = self._position_manager.positions[pos_id]
        self._trade_tracker.log_entry(position_state, signal)

    def _on_management_scan(self):
        """Twice-daily position management at 10:00 and 15:00 ET."""
        if self.is_warming_up:
            return

        if self._position_manager.get_open_count() == 0:
            return

        equity = self.portfolio.total_portfolio_value

        # Update risk manager P&L
        unrealised_pnl = self._position_manager.get_aggregate_unrealised_pnl(self)
        self._risk_manager.update_pnl(self.time, 0.0, unrealised_pnl)
        self._risk_manager.evaluate_risk_state(equity)

        # Get ATR and session data for catastrophic stop
        for asset_key in ACTIVE_ASSETS:
            ind = self._indicators[asset_key]
            atr_val = ind["atr"].value
            session_open = self._session_open.get(asset_key)

            future = self._futures[asset_key]
            current_price = None
            if future.mapped is not None:
                security = self.securities.get(future.mapped)
                if security is not None:
                    current_price = float(security.price)

            # Evaluate exits
            exits = self._position_manager.evaluate_exits(
                algorithm=self,
                risk_manager=self._risk_manager,
                current_time=self.time,
                atr_value=atr_val,
                session_open_price=session_open,
                current_price=current_price,
            )

            # Execute exits
            for pos_id, reason, details in exits:
                position = self._position_manager.positions.get(pos_id)
                if position is None:
                    continue

                # Calculate realised P&L before closing
                pnl_info = self._position_manager._calculate_pnl(self, position)
                realised_pnl = pnl_info["unrealised_pnl"] if pnl_info else 0.0

                # Submit close orders
                self._execution_manager.submit_iron_condor_exit(position)

                # Update records
                closed_pos = self._position_manager.close_position(pos_id, reason, details)
                if closed_pos:
                    self._trade_tracker.log_exit(closed_pos, reason, realised_pnl, self.time)

                    # Update risk manager with realised P&L
                    self._risk_manager.update_pnl(self.time, realised_pnl, 0.0)
                    self._risk_manager.evaluate_risk_state(equity)

    def _on_daily_summary(self):
        """End-of-day summary at 16:00 ET."""
        if self.is_warming_up:
            return

        equity = self.portfolio.total_portfolio_value
        open_count = self._position_manager.get_open_count()
        margin_used = self.portfolio.total_margin_used if hasattr(self.portfolio, "total_margin_used") else 0
        margin_pct = margin_used / equity if equity > 0 else 0

        self._trade_tracker.log_daily_summary(
            equity=equity,
            open_position_count=open_count,
            margin_pct=margin_pct,
            risk_state=self._risk_manager.state,
        )

        # Log regime and trend info
        for asset_key in ACTIVE_ASSETS:
            ind = self._indicators[asset_key]
            regime = self._regime_detectors[asset_key].current_regime
            trend_score = ind["trend"].trend_score if ind["trend"].is_ready else None
            iv_rank = ind["iv_rank"].iv_rank
            self.debug(
                f"[DAILY] {asset_key}: regime={regime} "
                f"trend={trend_score:.2f if trend_score else 'N/A'} "
                f"IVR={iv_rank:.0f if iv_rank else 'N/A'}"
            )

    def on_end_of_algorithm(self):
        """Final summary at algorithm end."""
        self.debug(f"[FINAL] Optimus {ALGORITHM_VERSION} complete")
        self.debug(f"[FINAL] {self._trade_tracker.summary()}")
        self.debug(f"[FINAL] Final equity: ${self.portfolio.total_portfolio_value:,.0f}")

        # Log exit reason breakdown
        reasons = {}
        for trade in self._trade_tracker.closed_trades:
            reason = trade["exit_reason"]
            reasons[reason] = reasons.get(reason, 0) + 1
        self.debug(f"[FINAL] Exit reasons: {reasons}")
