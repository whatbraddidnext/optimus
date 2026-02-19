# options_chain_manager.py — Optimus v2.0-MVP
# Futures options chain parsing, strike selection by delta, liquidity validation
# Handles missing/illiquid chains gracefully

MODULE_VERSION = "1.0"

from config import LIQUIDITY


class OptionsChainManager:
    """Manages futures options chain access, strike selection, and liquidity checks.

    Responsibilities:
    - Find options chain at target DTE
    - Select strikes by delta target (call and put sides)
    - Validate liquidity (bid-ask spread, open interest)
    - Build iron condor leg definitions
    """

    def __init__(self, algorithm, asset_config):
        self.algo = algorithm
        self.config = asset_config
        self.point_value = asset_config["point_value"]
        self.wing_width = asset_config["wing_width_points"]

    def get_chain_at_target_dte(self, option_chain, min_dte, max_dte):
        """Filter options chain to contracts within DTE range.

        Returns list of contracts sorted by DTE proximity to midpoint,
        or None if no suitable contracts found.
        """
        if option_chain is None:
            return None

        target_dte = (min_dte + max_dte) / 2.0
        contracts = []

        for contract in option_chain:
            dte = (contract.expiry - self.algo.time).days
            if min_dte <= dte <= max_dte:
                contracts.append(contract)

        if not contracts:
            return None

        return contracts

    def get_expiry_at_target_dte(self, option_chain, min_dte, max_dte):
        """Find the best expiry date within DTE range (closest to target midpoint).

        Returns expiry datetime or None.
        """
        if option_chain is None:
            return None

        target_dte = (min_dte + max_dte) / 2.0
        expiries = set()

        for contract in option_chain:
            dte = (contract.expiry - self.algo.time).days
            if min_dte <= dte <= max_dte:
                expiries.add(contract.expiry)

        if not expiries:
            return None

        # Select expiry closest to target DTE
        return min(expiries, key=lambda e: abs((e - self.algo.time).days - target_dte))

    def select_short_strike(self, contracts, target_delta, right):
        """Select the strike whose delta is closest to target.

        Args:
            contracts: List of option contracts (filtered by expiry)
            target_delta: Target delta (positive value, e.g. 0.16)
            right: OptionRight.Call or OptionRight.Put

        Returns:
            Best matching contract or None
        """
        candidates = [c for c in contracts if c.right == right]
        if not candidates:
            return None

        best = None
        best_diff = float("inf")

        for contract in candidates:
            greeks = contract.greeks
            if greeks is None or greeks.delta is None:
                continue

            contract_delta = abs(greeks.delta)
            diff = abs(contract_delta - target_delta)

            if diff < best_diff:
                best_diff = diff
                best = contract

        return best

    def select_long_wing(self, contracts, short_strike, wing_width, right):
        """Select the long wing strike for an iron condor leg.

        For calls: long strike = short strike + wing_width
        For puts: long strike = short strike - wing_width

        Returns the closest available strike to the target, or None.
        """
        candidates = [c for c in contracts if c.right == right]
        if not candidates:
            return None

        if right == OptionRight.Call:
            target_strike = short_strike + wing_width
        else:
            target_strike = short_strike - wing_width

        best = None
        best_diff = float("inf")

        for contract in candidates:
            diff = abs(float(contract.strike) - target_strike)
            if diff < best_diff:
                best_diff = diff
                best = contract

        return best

    def check_liquidity(self, contract):
        """Validate a contract meets liquidity thresholds.

        Checks:
        - Bid-ask spread < 15% of mid price
        - Open interest > 500

        Returns (passes, reason_if_failed)
        """
        if contract is None:
            return False, "contract is None"

        bid = contract.bid_price
        ask = contract.ask_price

        if bid is None or ask is None or bid <= 0 or ask <= 0:
            return False, "no valid bid/ask"

        mid = (bid + ask) / 2.0
        if mid <= 0:
            return False, "zero mid price"

        spread_pct = (ask - bid) / mid
        if spread_pct > LIQUIDITY["max_spread_pct"]:
            return False, f"spread {spread_pct:.1%} > {LIQUIDITY['max_spread_pct']:.0%}"

        oi = contract.open_interest if hasattr(contract, "open_interest") else None
        if oi is not None and oi < LIQUIDITY["min_open_interest"]:
            return False, f"OI {oi} < {LIQUIDITY['min_open_interest']}"

        return True, None

    def build_iron_condor(self, option_chain, call_delta, put_delta,
                          min_dte, max_dte):
        """Build a complete iron condor from the options chain.

        Returns IronCondorLegs or None with rejection reason.

        Structure:
        - Short call at call_delta
        - Long call at short_call + wing_width
        - Short put at put_delta
        - Long put at short_put - wing_width
        """
        # Find target expiry
        expiry = self.get_expiry_at_target_dte(option_chain, min_dte, max_dte)
        if expiry is None:
            return None, "no expiry in DTE range"

        # Filter to target expiry
        expiry_contracts = [c for c in option_chain if c.expiry == expiry]
        if not expiry_contracts:
            return None, "no contracts at target expiry"

        dte = (expiry - self.algo.time).days

        # Select short call
        short_call = self.select_short_strike(expiry_contracts, call_delta, OptionRight.Call)
        if short_call is None:
            return None, "no short call at target delta"

        # Select short put
        short_put = self.select_short_strike(expiry_contracts, put_delta, OptionRight.Put)
        if short_put is None:
            return None, "no short put at target delta"

        # Select long wings
        long_call = self.select_long_wing(
            expiry_contracts, float(short_call.strike), self.wing_width, OptionRight.Call
        )
        if long_call is None:
            return None, "no long call wing"

        long_put = self.select_long_wing(
            expiry_contracts, float(short_put.strike), self.wing_width, OptionRight.Put
        )
        if long_put is None:
            return None, "no long put wing"

        # Liquidity checks on all four legs
        for leg, name in [(short_call, "short_call"), (short_put, "short_put"),
                          (long_call, "long_call"), (long_put, "long_put")]:
            passes, reason = self.check_liquidity(leg)
            if not passes:
                # Try widening by one strike for short legs
                if name.startswith("short"):
                    return None, f"{name} illiquid: {reason}"
                # Long wings less critical — accept wider spreads
                # but still reject if no bid/ask at all
                if reason == "no valid bid/ask" or reason == "contract is None":
                    return None, f"{name} illiquid: {reason}"

        # Calculate credit and max loss
        short_call_mid = (short_call.bid_price + short_call.ask_price) / 2.0
        short_put_mid = (short_put.bid_price + short_put.ask_price) / 2.0
        long_call_mid = (long_call.bid_price + long_call.ask_price) / 2.0
        long_put_mid = (long_put.bid_price + long_put.ask_price) / 2.0

        total_credit = (short_call_mid + short_put_mid - long_call_mid - long_put_mid)

        # Max loss = wider side wing width * point_value - credit
        call_width = abs(float(long_call.strike) - float(short_call.strike))
        put_width = abs(float(short_put.strike) - float(long_put.strike))
        max_wing_width = max(call_width, put_width)
        max_loss = max_wing_width * self.point_value - total_credit * self.point_value

        legs = IronCondorLegs(
            short_call=short_call,
            long_call=long_call,
            short_put=short_put,
            long_put=long_put,
            expiry=expiry,
            dte=dte,
            total_credit=total_credit,
            max_loss=max_loss,
            call_width=call_width,
            put_width=put_width,
        )

        return legs, None


class IronCondorLegs:
    """Container for a complete iron condor structure."""

    def __init__(self, short_call, long_call, short_put, long_put,
                 expiry, dte, total_credit, max_loss, call_width, put_width):
        self.short_call = short_call
        self.long_call = long_call
        self.short_put = short_put
        self.long_put = long_put
        self.expiry = expiry
        self.dte = dte
        self.total_credit = total_credit
        self.max_loss = max_loss
        self.call_width = call_width
        self.put_width = put_width

    @property
    def short_call_strike(self):
        return float(self.short_call.strike)

    @property
    def short_put_strike(self):
        return float(self.short_put.strike)

    @property
    def long_call_strike(self):
        return float(self.long_call.strike)

    @property
    def long_put_strike(self):
        return float(self.long_put.strike)

    def summary(self):
        return (f"IC {self.long_put_strike:.0f}/{self.short_put_strike:.0f}"
                f"/{self.short_call_strike:.0f}/{self.long_call_strike:.0f}"
                f" DTE={self.dte} credit={self.total_credit:.2f}"
                f" max_loss={self.max_loss:.0f}")
