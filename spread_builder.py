# spread_builder.py — Optimus Spread Builder
# Version: v2.001
#
# Handles options chain filtering, strike selection, and spread construction.
# Isolates all options-specific logic from the signal engine.

import config as cfg
from shared.utils import safe_divide


class SpreadCandidate:
    """A fully constructed credit spread ready for execution."""

    def __init__(self, underlying, short_strike, long_strike, short_delta,
                 expiry, dte, short_bid, short_ask, long_bid, long_ask,
                 net_credit, spread_width, multiplier):
        self.underlying = underlying
        self.short_strike = short_strike
        self.long_strike = long_strike
        self.short_delta = short_delta
        self.expiry = expiry
        self.dte = dte
        self.short_bid = short_bid
        self.short_ask = short_ask
        self.long_bid = long_bid
        self.long_ask = long_ask
        self.net_credit = net_credit
        self.spread_width = spread_width
        self.multiplier = multiplier

    @property
    def max_loss_per_contract(self):
        """Maximum loss in dollars per contract."""
        return (self.spread_width - self.net_credit) * self.multiplier

    @property
    def max_profit_per_contract(self):
        """Maximum profit in dollars per contract."""
        return self.net_credit * self.multiplier

    @property
    def profit_target_price(self):
        """Price at which to close for profit target (50% of credit)."""
        return self.net_credit * (cfg.PROFIT_TARGET_PCT / 100.0)

    @property
    def stop_loss_price(self):
        """Spread value at which to close for stop loss."""
        return self.net_credit * cfg.STOP_LOSS_MULTIPLIER

    @property
    def bid_ask_quality(self):
        """Bid/ask spread as % of mid-market credit. Lower is better."""
        short_spread = self.short_ask - self.short_bid
        long_spread = self.long_ask - self.long_bid
        total_spread = short_spread + long_spread
        return safe_divide(total_spread, self.net_credit, 999.0) * 100.0

    def to_log(self, contracts, portfolio_equity, total_exposure_pct):
        """Format trade details for structured logging."""
        total_max_loss = self.max_loss_per_contract * contracts
        total_max_profit = self.max_profit_per_contract * contracts
        risk_pct = safe_divide(total_max_loss, portfolio_equity, 0) * 100
        rr_ratio = safe_divide(self.max_loss_per_contract,
                               self.max_profit_per_contract, 0)

        lines = [
            f"[TRADE OPENED] {self.underlying} Put Credit Spread",
            f"  Short Put: {self.underlying} {self.short_strike}P "
            f"(delta: {self.short_delta:.3f})",
            f"  Long Put: {self.underlying} {self.long_strike}P",
            f"  Net Credit: ${self.net_credit:.2f} "
            f"(${self.max_profit_per_contract:,.0f} per contract)",
            f"  Contracts: {contracts}",
            f"  Spread Width: {self.spread_width} points "
            f"(${self.spread_width * self.multiplier:,} per contract)",
            f"  Max Loss: ${self.max_loss_per_contract:,.0f}/contract "
            f"(${total_max_loss:,.0f} total)",
            f"  Max Profit: ${self.max_profit_per_contract:,.0f}/contract "
            f"(${total_max_profit:,.0f} total)",
            f"  Risk/Reward: {rr_ratio:.1f}:1",
            f"  DTE: {self.dte}",
            f"  Expiration: {self.expiry}",
            f"  Profit Target: Close at ${self.profit_target_price:.2f} "
            f"({cfg.PROFIT_TARGET_PCT}% of credit)",
            f"  Stop Loss: Close at ${self.stop_loss_price:.2f} "
            f"({cfg.STOP_LOSS_MULTIPLIER:.0f}x credit)",
            f"  Time Stop: {cfg.TIME_STOP_DTE} DTE",
            f"  Portfolio Risk: ${total_max_loss:,.0f} / "
            f"${portfolio_equity:,.0f} = {risk_pct:.1f}%",
            f"  Total Exposure: {total_exposure_pct:.1f}% of equity",
            f"  Bid/Ask Quality: {self.bid_ask_quality:.1f}%",
        ]
        return "\n".join(lines)


class SpreadBuilder:
    """Builds put credit spreads from options chain data.

    Strike selection logic (HLD Section 5.2):
        1. Get options chain for target expiration
        2. Filter for put options
        3. Find strike with delta closest to target
        4. Long put = short put - spread width
        5. Validate both strikes exist with acceptable bid/ask
    """

    VERSION = "v2.001"

    def __init__(self, algorithm):
        """Args:
            algorithm: QCAlgorithm instance for options chain access.
        """
        self.algo = algorithm

    def build_put_credit_spread(self, underlying, chain):
        """Attempt to build a put credit spread from the options chain.

        Args:
            underlying: Ticker string (e.g. "SPX").
            chain: QuantConnect OptionChain object.

        Returns:
            SpreadCandidate or None if no suitable spread found.
        """
        ucfg = cfg.UNDERLYING_CONFIG.get(underlying, {})
        target_delta = ucfg.get("target_delta", cfg.TARGET_DELTA)
        spread_width = ucfg.get("spread_width", cfg.SPREAD_WIDTH)
        target_dte = ucfg.get("target_dte", cfg.TARGET_DTE)
        min_dte = ucfg.get("min_dte", cfg.MIN_DTE_ENTRY)
        max_dte = ucfg.get("max_dte", cfg.MAX_DTE_ENTRY)
        multiplier = ucfg.get("multiplier", 100)

        # Step 1: Find best expiration
        expiry = self._select_expiration(chain, target_dte, min_dte, max_dte)
        if expiry is None:
            self.algo.log(f"[SPREAD BUILDER] No suitable expiration for "
                          f"{underlying} (target {target_dte} DTE, "
                          f"range {min_dte}-{max_dte})")
            return None

        # Step 2: Filter puts for this expiration
        puts = [c for c in chain
                if c.right == 1  # Put = 1 in QC
                and c.expiry == expiry
                and c.greeks is not None
                and c.greeks.delta is not None]

        if not puts:
            self.algo.log(f"[SPREAD BUILDER] No puts with Greeks for "
                          f"{underlying} expiry {expiry}")
            return None

        # Step 3: Find short strike (closest to target delta)
        short_contract = self._select_short_strike(puts, target_delta)
        if short_contract is None:
            self.algo.log(f"[SPREAD BUILDER] No suitable short strike for "
                          f"{underlying} at delta {target_delta}")
            return None

        short_strike = short_contract.strike

        # Step 4: Find long strike (spread_width below short)
        long_strike = short_strike - spread_width
        long_contract = next(
            (c for c in puts if c.strike == long_strike), None)

        if long_contract is None:
            self.algo.log(f"[SPREAD BUILDER] Long strike {long_strike} not "
                          f"available for {underlying}")
            return None

        # Step 5: Calculate net credit
        short_mid = (short_contract.bid_price + short_contract.ask_price) / 2
        long_mid = (long_contract.bid_price + long_contract.ask_price) / 2
        net_credit = short_mid - long_mid

        if net_credit <= 0:
            self.algo.log(f"[SPREAD BUILDER] Non-positive credit "
                          f"({net_credit:.2f}) for {underlying} "
                          f"{short_strike}/{long_strike}")
            return None

        # Step 6: Validate bid/ask quality
        dte = (expiry - self.algo.time.date()).days if hasattr(expiry, 'date') else (expiry.date() - self.algo.time.date()).days

        candidate = SpreadCandidate(
            underlying=underlying,
            short_strike=short_strike,
            long_strike=long_strike,
            short_delta=short_contract.greeks.delta,
            expiry=expiry,
            dte=dte,
            short_bid=short_contract.bid_price,
            short_ask=short_contract.ask_price,
            long_bid=long_contract.bid_price,
            long_ask=long_contract.ask_price,
            net_credit=net_credit,
            spread_width=spread_width,
            multiplier=multiplier,
        )

        if candidate.bid_ask_quality > cfg.MAX_BID_ASK_SPREAD_PCT:
            self.algo.log(f"[SPREAD BUILDER] Bid/ask quality poor "
                          f"({candidate.bid_ask_quality:.1f}%) for "
                          f"{underlying} {short_strike}/{long_strike} — "
                          f"flagged but proceeding")

        return candidate

    def _select_expiration(self, chain, target_dte, min_dte, max_dte):
        """Find the expiration closest to target DTE within acceptable range."""
        today = self.algo.time.date()
        best_expiry = None
        best_diff = float('inf')

        seen_expiries = set()
        for contract in chain:
            exp = contract.expiry
            if exp in seen_expiries:
                continue
            seen_expiries.add(exp)

            exp_date = exp.date() if hasattr(exp, 'date') else exp
            dte = (exp_date - today).days
            if min_dte <= dte <= max_dte:
                diff = abs(dte - target_dte)
                if diff < best_diff:
                    best_diff = diff
                    best_expiry = exp

        return best_expiry

    def _select_short_strike(self, puts, target_delta):
        """Find the put with delta closest to target.

        Delta for puts is negative. target_delta is negative (e.g. -0.16).
        """
        best = None
        best_diff = float('inf')

        for contract in puts:
            delta = contract.greeks.delta
            if delta is None:
                continue
            diff = abs(delta - target_delta)
            if diff < best_diff:
                best_diff = diff
                best = contract

        return best
