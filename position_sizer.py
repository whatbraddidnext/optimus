# position_sizer.py — Optimus v2.0-MVP
# Max-loss based position sizing for iron condors
# Size by what you can lose, not what you collect

MODULE_VERSION = "1.0"

import math


class PositionSizer:
    """Calculate contract quantity for iron condors based on maximum loss.

    Core principle: size by max_loss, not premium received.
    A $1,000 credit on 50-point wings on /ES risks $1,500.
    Size to the $1,500.

    contracts = floor(max_risk_per_trade / max_loss_per_ic)
    max_risk_per_trade = equity * risk_pct_per_trade
    """

    def __init__(self, global_config):
        self.risk_pct = global_config["risk_pct_per_trade"]
        self.aggregate_max_loss_pct = global_config["aggregate_max_loss_pct"]
        self.max_total_positions = global_config["max_total_positions"]

    def size_iron_condor(self, equity, max_loss_per_contract, current_aggregate_risk,
                         current_position_count):
        """Calculate number of contracts for an iron condor.

        Args:
            equity: Current portfolio equity
            max_loss_per_contract: Max loss for 1 IC (wing_width * point_value - credit)
            current_aggregate_risk: Sum of max losses across all open positions
            current_position_count: Number of currently open positions

        Returns:
            (contracts, reason) — contracts >= 1 or 0 with rejection reason
        """
        if equity <= 0:
            return 0, "zero equity"

        if max_loss_per_contract <= 0:
            return 0, "invalid max loss"

        # Check position count limit
        if current_position_count >= self.max_total_positions:
            return 0, f"at position limit ({self.max_total_positions})"

        # Max risk for this trade
        max_risk = equity * self.risk_pct

        # Check aggregate limit
        remaining_risk_budget = (equity * self.aggregate_max_loss_pct) - current_aggregate_risk
        if remaining_risk_budget <= 0:
            return 0, "aggregate risk budget exhausted"

        # Use the smaller of per-trade limit and remaining budget
        effective_risk = min(max_risk, remaining_risk_budget)

        # Calculate contracts
        contracts = math.floor(effective_risk / max_loss_per_contract)

        if contracts < 1:
            return 0, f"max loss ${max_loss_per_contract:.0f} > risk budget ${effective_risk:.0f}"

        return contracts, None

    def validate_sizing(self, contracts, max_loss_per_contract, equity):
        """Post-check: verify total risk is within bounds."""
        total_risk = contracts * max_loss_per_contract
        risk_pct = total_risk / equity if equity > 0 else 1.0
        return {
            "contracts": contracts,
            "total_risk": total_risk,
            "risk_pct": risk_pct,
            "within_limits": risk_pct <= self.risk_pct * 1.01,  # tiny float tolerance
        }
