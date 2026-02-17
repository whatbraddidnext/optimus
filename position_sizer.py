# position_sizer.py — Optimus Position Sizer
# Version: v2.001
#
# Calculates position size from max loss, conviction, and drawdown.
# Never sizes by premium received — always by maximum possible loss.

import config as cfg
from shared.sizing import size_by_max_loss, drawdown_adjusted_risk, max_loss_for_spread
from shared.utils import safe_divide


class PositionSizer:
    """Determines the number of contracts for each trade.

    Sizing pipeline:
        1. Base risk % (from config, adjusted for drawdown)
        2. Conviction multiplier (from conviction scorer, 0.5x–1.5x)
        3. Regime allocation multiplier (from regime detector)
        4. Max loss per contract (from spread builder)
        5. Floor of (adjusted risk / max loss per contract)
    """

    VERSION = "v2.001"

    def __init__(self, algorithm, regime_detector):
        self.algo = algorithm
        self.regime = regime_detector

    def calculate(self, spread_candidate, conviction_result,
                  portfolio_equity, current_drawdown_pct):
        """Calculate the number of contracts.

        Args:
            spread_candidate: SpreadCandidate from spread_builder.
            conviction_result: dict from conviction_scorer.score().
            portfolio_equity: Current portfolio value.
            current_drawdown_pct: Current drawdown as positive decimal.

        Returns:
            dict: {
                contracts: int,
                risk_pct: float (adjusted),
                conviction: float,
                regime_mult: float,
                max_loss_per_contract: float,
                total_max_loss: float,
                detail: str,
            }
        """
        # Step 1: Drawdown-adjusted risk
        base_risk = cfg.RISK_PER_TRADE_PCT / 100.0
        adjusted_risk = drawdown_adjusted_risk(base_risk, current_drawdown_pct)

        # Step 2: Conviction multiplier
        conviction_mult = conviction_result["multiplier"]

        # Step 3: Regime allocation
        regime_mult = self.regime.allocation_multiplier()

        # Step 4: Max loss per contract
        mlpc = spread_candidate.max_loss_per_contract
        if mlpc <= 0:
            return self._result(0, adjusted_risk, conviction_mult, regime_mult,
                                mlpc, 0, portfolio_equity,
                                "Max loss per contract <= 0")

        # Step 5: Combined sizing
        effective_risk = adjusted_risk * conviction_mult * regime_mult
        max_risk_dollars = portfolio_equity * effective_risk
        contracts = int(max_risk_dollars / mlpc)
        contracts = max(contracts, 0)

        total_max_loss = contracts * mlpc
        detail = (f"Equity ${portfolio_equity:,.0f} x risk {adjusted_risk:.3f} "
                  f"x conviction {conviction_mult:.2f} x regime {regime_mult:.2f} "
                  f"= ${max_risk_dollars:,.0f} budget / "
                  f"${mlpc:,.0f} per contract = {contracts}")

        return self._result(contracts, adjusted_risk, conviction_mult,
                            regime_mult, mlpc, total_max_loss,
                            portfolio_equity, detail)

    @staticmethod
    def _result(contracts, risk_pct, conviction, regime_mult,
                max_loss_per_contract, total_max_loss, equity, detail):
        return {
            "contracts": contracts,
            "risk_pct": round(risk_pct, 4),
            "conviction": round(conviction, 3),
            "regime_mult": round(regime_mult, 3),
            "max_loss_per_contract": round(max_loss_per_contract, 2),
            "total_max_loss": round(total_max_loss, 2),
            "risk_of_equity_pct": round(
                safe_divide(total_max_loss, equity, 0) * 100, 2),
            "detail": detail,
        }
