# trade_tracker.py — Optimus Trade Tracker
# Version: v2.001
#
# Complete audit trail for every trade. Records entries, exits, P/L,
# and running performance statistics. Every decision is logged.

from datetime import datetime
import config as cfg
from shared.constants import ExitReason, TradeResult
from shared.utils import safe_divide, business_days_between, format_currency


class TradeTracker:
    """Tracks all open and closed positions with full audit trail.

    Provides:
        - Open position management
        - P/L tracking
        - Running statistics (win rate, profit factor, etc.)
        - Portfolio heat calculation
        - Aggregate Greeks
    """

    VERSION = "v2.001"

    def __init__(self, algorithm):
        self.algo = algorithm
        self._open_positions = {}   # id -> position dict
        self._closed_trades = []    # list of completed trade dicts
        self._next_id = 1

    # -------------------------------------------------------------------------
    # Position Management
    # -------------------------------------------------------------------------

    def open_position(self, spread_candidate, contracts, sizing_result,
                      conviction_result, entry_date):
        """Record a new position.

        Args:
            spread_candidate: SpreadCandidate from spread_builder.
            contracts: Number of contracts.
            sizing_result: dict from position_sizer.
            conviction_result: dict from conviction_scorer.
            entry_date: Date of entry.

        Returns:
            str: Position ID.
        """
        pos_id = f"OPT-{self._next_id:04d}"
        self._next_id += 1

        position = {
            "id": pos_id,
            "underlying": spread_candidate.underlying,
            "short_strike": spread_candidate.short_strike,
            "long_strike": spread_candidate.long_strike,
            "short_delta": spread_candidate.short_delta,
            "spread_width": spread_candidate.spread_width,
            "contracts": contracts,
            "entry_credit": spread_candidate.net_credit,
            "entry_date": entry_date,
            "expiry": spread_candidate.expiry,
            "dte_at_entry": spread_candidate.dte,
            "max_loss_per_contract": spread_candidate.max_loss_per_contract,
            "max_profit_per_contract": spread_candidate.max_profit_per_contract,
            "total_max_loss": spread_candidate.max_loss_per_contract * contracts,
            "total_max_profit": spread_candidate.max_profit_per_contract * contracts,
            "conviction": conviction_result["multiplier"],
            "risk_of_equity_pct": sizing_result["risk_of_equity_pct"],
            # Live tracking (updated daily)
            "current_spread_value": spread_candidate.net_credit,
            "current_pnl": 0.0,
            "dte_remaining": spread_candidate.dte,
            "current_delta": spread_candidate.short_delta,
            "current_theta": None,
            # Symbols for closing
            "short_symbol": None,  # Set after fill
            "long_symbol": None,
        }
        self._open_positions[pos_id] = position
        return pos_id

    def close_position(self, position_id, exit_reason, exit_credit, exit_date):
        """Record a position close.

        Args:
            position_id: Position ID string.
            exit_reason: ExitReason enum.
            exit_credit: Debit paid to close (positive = cost).
            exit_date: Date of exit.

        Returns:
            dict: Closed trade record.
        """
        pos = self._open_positions.pop(position_id, None)
        if pos is None:
            self.algo.log(f"[TRACKER] Position {position_id} not found for close")
            return None

        pnl_per_contract = (pos["entry_credit"] - exit_credit)
        total_pnl = pnl_per_contract * pos["contracts"] * cfg.UNDERLYING_CONFIG.get(
            pos["underlying"], {}).get("multiplier", 100)

        days_held = (exit_date - pos["entry_date"]).days if hasattr(exit_date, '__sub__') else 0
        dte_at_close = pos.get("dte_remaining", 0)

        result = TradeResult.WIN if total_pnl > 0 else (
            TradeResult.BREAKEVEN if total_pnl == 0 else TradeResult.LOSS)

        trade = {
            **pos,
            "exit_reason": exit_reason,
            "exit_credit": exit_credit,
            "exit_date": exit_date,
            "pnl_per_contract": pnl_per_contract,
            "total_pnl": total_pnl,
            "return_on_risk": safe_divide(total_pnl, pos["total_max_loss"], 0) * 100,
            "days_held": days_held,
            "dte_at_close": dte_at_close,
            "result": result,
        }
        self._closed_trades.append(trade)
        return trade

    def update_position(self, position_id, current_spread_value=None,
                        dte_remaining=None, current_delta=None,
                        current_theta=None):
        """Update live tracking data for an open position."""
        pos = self._open_positions.get(position_id)
        if pos is None:
            return
        if current_spread_value is not None:
            pos["current_spread_value"] = current_spread_value
            multiplier = cfg.UNDERLYING_CONFIG.get(
                pos["underlying"], {}).get("multiplier", 100)
            pos["current_pnl"] = (
                (pos["entry_credit"] - current_spread_value)
                * pos["contracts"] * multiplier)
        if dte_remaining is not None:
            pos["dte_remaining"] = dte_remaining
        if current_delta is not None:
            pos["current_delta"] = current_delta
        if current_theta is not None:
            pos["current_theta"] = current_theta

    # -------------------------------------------------------------------------
    # Queries
    # -------------------------------------------------------------------------

    def open_positions(self):
        """Return list of all open position dicts."""
        return list(self._open_positions.values())

    def open_position_count(self):
        return len(self._open_positions)

    def open_position_count_for(self, underlying):
        return sum(1 for p in self._open_positions.values()
                   if p["underlying"] == underlying)

    def total_portfolio_heat(self):
        """Sum of max losses across all open positions."""
        return sum(p["total_max_loss"] for p in self._open_positions.values())

    def aggregate_delta(self):
        """Sum of delta across all open positions."""
        deltas = [p.get("current_delta", 0) or 0
                  for p in self._open_positions.values()]
        return sum(d * p.get("contracts", 1)
                   for d, p in zip(deltas, self._open_positions.values())) if deltas else 0.0

    def aggregate_theta(self):
        """Sum of theta across all open positions."""
        return sum((p.get("current_theta") or 0) * p.get("contracts", 1)
                   for p in self._open_positions.values())

    def aggregate_pnl(self):
        """Sum of unrealised P/L across all open positions."""
        return sum(p.get("current_pnl", 0) for p in self._open_positions.values())

    def business_days_since_last_entry(self, underlying, current_date):
        """Business days since last entry for a given underlying.

        Returns:
            int or None if no prior entries.
        """
        last_entry = None
        for p in self._open_positions.values():
            if p["underlying"] == underlying:
                if last_entry is None or p["entry_date"] > last_entry:
                    last_entry = p["entry_date"]
        for t in reversed(self._closed_trades):
            if t["underlying"] == underlying:
                if last_entry is None or t["entry_date"] > last_entry:
                    last_entry = t["entry_date"]
                break  # closed trades are in order
        if last_entry is None:
            return None
        return business_days_between(last_entry, current_date)

    def nearest_expiry_dte(self):
        """DTE of the position closest to expiration."""
        if not self._open_positions:
            return None
        return min(p.get("dte_remaining", 999)
                   for p in self._open_positions.values())

    # -------------------------------------------------------------------------
    # Statistics
    # -------------------------------------------------------------------------

    def recent_stats(self, last_n=10):
        """Performance statistics for the last N closed trades.

        Returns:
            dict with wins, losses, win_rate, profit_factor, total.
        """
        trades = self._closed_trades[-last_n:] if self._closed_trades else []
        total = len(trades)
        if total == 0:
            return {"wins": 0, "losses": 0, "win_rate": 0, "profit_factor": 0,
                    "total": 0, "total_pnl": 0}

        wins = sum(1 for t in trades if t["result"] == TradeResult.WIN)
        losses = total - wins
        gross_profit = sum(t["total_pnl"] for t in trades if t["total_pnl"] > 0)
        gross_loss = abs(sum(t["total_pnl"] for t in trades if t["total_pnl"] < 0))

        return {
            "wins": wins,
            "losses": losses,
            "win_rate": safe_divide(wins, total, 0) * 100,
            "profit_factor": safe_divide(gross_profit, gross_loss, 0),
            "total": total,
            "total_pnl": sum(t["total_pnl"] for t in trades),
        }

    def all_time_stats(self):
        """Lifetime performance statistics."""
        return self.recent_stats(last_n=len(self._closed_trades))

    def last_n_results(self, n=3):
        """Return the result (W/L) of the last N trades."""
        trades = self._closed_trades[-n:] if self._closed_trades else []
        return [t["result"].value[0] for t in trades]  # "W" or "L"

    # -------------------------------------------------------------------------
    # Logging
    # -------------------------------------------------------------------------

    def log_trade_closed(self, trade):
        """Format a closed trade for structured logging."""
        if trade is None:
            return ""
        stats = self.all_time_stats()
        lines = [
            f"[TRADE CLOSED] {trade['exit_date']} | "
            f"{trade['underlying']} Put Credit Spread",
            f"  Reason: {trade['exit_reason'].value}",
            f"  Entry Credit: ${trade['entry_credit']:.2f}",
            f"  Exit Debit: ${trade['exit_credit']:.2f}",
            f"  P/L: {format_currency(trade['pnl_per_contract'])}/contract "
            f"({format_currency(trade['total_pnl'])} total, "
            f"{trade['contracts']} contracts)",
            f"  Return on Risk: {trade['return_on_risk']:+.1f}%",
            f"  Days Held: {trade['days_held']}",
            f"  DTE at Close: {trade['dte_at_close']}",
            f"  Win/Loss: {trade['result'].value}",
            f"  Running Stats: {stats['wins']}W / {stats['losses']}L "
            f"({stats['win_rate']:.1f}% win rate), "
            f"PF: {stats['profit_factor']:.2f}",
        ]
        return "\n".join(lines)
