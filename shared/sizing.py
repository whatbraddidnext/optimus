# shared/sizing.py — Stargaze Capital Shared Position Sizing
# Version: v2.001

import math
from shared.utils import safe_divide, clamp


def size_by_max_loss(portfolio_equity, risk_pct, max_loss_per_contract,
                     conviction_multiplier=1.0, min_contracts=0):
    """Calculate position size based on maximum loss per contract.

    Args:
        portfolio_equity: Current portfolio equity value.
        risk_pct: Maximum risk per trade as decimal (e.g. 0.02 for 2%).
        max_loss_per_contract: Max loss in dollars for one contract.
        conviction_multiplier: Scaling factor from conviction scorer (0.5-1.5).
        min_contracts: Minimum contracts (0 = skip trade if too small).

    Returns:
        Number of contracts (int). Returns 0 if sizing is below minimum.
    """
    if max_loss_per_contract <= 0 or portfolio_equity <= 0:
        return 0

    max_risk_dollars = portfolio_equity * risk_pct
    scaled_risk = max_risk_dollars * conviction_multiplier
    contracts = math.floor(scaled_risk / max_loss_per_contract)

    return max(contracts, min_contracts)


def drawdown_adjusted_risk(base_risk_pct, current_drawdown_pct):
    """Reduce risk percentage based on current drawdown.

    Args:
        base_risk_pct: Normal risk per trade (e.g. 0.02).
        current_drawdown_pct: Current drawdown as positive decimal (e.g. 0.12 for 12%).

    Returns:
        Adjusted risk percentage.
    """
    if current_drawdown_pct >= 0.20:
        return 0.01  # 1% at 20%+ drawdown
    elif current_drawdown_pct >= 0.10:
        return 0.015  # 1.5% at 10-20% drawdown
    return base_risk_pct


def max_loss_for_spread(spread_width, premium_received, multiplier=100):
    """Calculate maximum loss for a credit spread.

    Args:
        spread_width: Distance between strikes in points.
        premium_received: Net credit received per share.
        multiplier: Contract multiplier (100 for SPX).

    Returns:
        Maximum loss in dollars per contract.
    """
    return (spread_width - premium_received) * multiplier
