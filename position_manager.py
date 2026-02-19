# position_manager.py — Optimus v2.0-MVP
# Exit logic: profit target, loss limit, time stop, catastrophic stop
# Priority-ordered exit evaluation on every management scan

MODULE_VERSION = "1.0"

import uuid
from datetime import datetime


class ExitReason:
    CATASTROPHIC_STOP = "CATASTROPHIC_STOP"
    LOSS_LIMIT = "LOSS_LIMIT"
    PROFIT_TARGET = "PROFIT_TARGET"
    TIME_STOP = "TIME_STOP"
    RISK_FORCE_CLOSE = "RISK_FORCE_CLOSE"
    MANUAL = "MANUAL"


class PositionManager:
    """Manages open iron condor positions and evaluates exits.

    Exit priority (HLD Section 9.1):
    1. Catastrophic stop — underlying moved > 3x ATR(14) in session
    2. Loss limit — P&L <= -(max_loss * loss_limit_ic_pct / 100)
    3. Profit target — P&L >= credit * (profit_target_pct / 100)
    4. Time stop — remaining DTE <= time_stop_dte

    Position tracking fields:
    - entry_credit, current_value, unrealised_pnl
    - max_loss, days_held, remaining_dte
    - short_call_delta, short_put_delta
    """

    def __init__(self, global_config):
        self.config = global_config
        self.positions = {}  # id -> PositionState dict

    def create_position(self, asset_key, asset_config, ic_legs, contracts,
                        trend_score, iv_rank, regime, current_time):
        """Create a new position state after successful IC entry.

        Returns position ID.
        """
        pos_id = f"{asset_key}_{current_time.strftime('%Y%m%d_%H%M')}_{uuid.uuid4().hex[:6]}"

        # Build leg records
        legs = []
        for leg_type, contract, qty_sign in [
            ("short_call", ic_legs.short_call, -contracts),
            ("long_call", ic_legs.long_call, contracts),
            ("short_put", ic_legs.short_put, -contracts),
            ("long_put", ic_legs.long_put, contracts),
        ]:
            legs.append({
                "type": leg_type,
                "symbol": contract.symbol,
                "strike": float(contract.strike),
                "expiry": ic_legs.expiry,
                "quantity": qty_sign,
                "entry_premium": (contract.bid_price + contract.ask_price) / 2.0,
            })

        position = {
            "id": pos_id,
            "underlying": asset_key,
            "tier": 1,  # MVP: IC only
            "legs": legs,
            "contracts": contracts,
            "entry_credit": ic_legs.total_credit * contracts,
            "entry_credit_per_contract": ic_legs.total_credit,
            "entry_date": current_time,
            "entry_trend_score": trend_score,
            "entry_regime": regime,
            "entry_iv_rank": iv_rank,
            "max_loss": ic_legs.max_loss * contracts,
            "max_loss_per_contract": ic_legs.max_loss,
            "profit_target_pct": asset_config["profit_target_pct"],
            "loss_limit_ic_pct": asset_config["loss_limit_ic_pct"],
            "time_stop_dte": asset_config["time_stop_dte"],
            "point_value": asset_config["point_value"],
            "status": "active",
        }

        self.positions[pos_id] = position
        return pos_id

    def evaluate_exits(self, algorithm, risk_manager, current_time, atr_value=None,
                       session_open_price=None, current_price=None):
        """Evaluate all open positions for exit conditions.

        Returns list of (position_id, ExitReason, details) for positions that should close.
        """
        exits = []

        for pos_id, pos in list(self.positions.items()):
            if pos["status"] != "active":
                continue

            # Calculate current position value and P&L
            pnl_info = self._calculate_pnl(algorithm, pos)
            if pnl_info is None:
                continue

            unrealised_pnl = pnl_info["unrealised_pnl"]
            remaining_dte = pnl_info["remaining_dte"]

            # Priority 1: Catastrophic stop
            if (atr_value is not None and session_open_price is not None
                    and current_price is not None and atr_value > 0):
                move_atrs = abs(current_price - session_open_price) / atr_value
                if risk_manager.check_catastrophic_stop(move_atrs):
                    exits.append((pos_id, ExitReason.CATASTROPHIC_STOP,
                                  f"underlying moved {move_atrs:.1f}x ATR"))
                    continue

            # Priority 2: Loss limit
            loss_limit_pct = pos["loss_limit_ic_pct"] / 100.0
            loss_threshold = -(pos["max_loss"] * loss_limit_pct)
            if unrealised_pnl <= loss_threshold:
                exits.append((pos_id, ExitReason.LOSS_LIMIT,
                              f"P&L ${unrealised_pnl:.0f} <= limit ${loss_threshold:.0f}"))
                continue

            # Priority 3: Profit target
            credit = pos["entry_credit"] * pos["point_value"]
            profit_target = credit * (pos["profit_target_pct"] / 100.0)
            # Tighten if risk manager says so (WEEK_HALT -> 40%)
            if risk_manager.should_tighten_targets():
                profit_target = credit * 0.40

            if unrealised_pnl >= profit_target:
                exits.append((pos_id, ExitReason.PROFIT_TARGET,
                              f"P&L ${unrealised_pnl:.0f} >= target ${profit_target:.0f}"))
                continue

            # Priority 4: Time stop
            if remaining_dte <= pos["time_stop_dte"]:
                exits.append((pos_id, ExitReason.TIME_STOP,
                              f"DTE {remaining_dte} <= {pos['time_stop_dte']}"))
                continue

            # Priority 5: Risk force close (MONTH_HALT and DTE > 21)
            if risk_manager.should_force_close_above_dte():
                if remaining_dte > pos["time_stop_dte"]:
                    exits.append((pos_id, ExitReason.RISK_FORCE_CLOSE,
                                  f"MONTH_HALT: closing DTE {remaining_dte} position"))
                    continue

        return exits

    def _calculate_pnl(self, algorithm, pos):
        """Calculate unrealised P&L and remaining DTE for a position.

        P&L = entry_credit - current_cost_to_close (both in point terms)
        Positive P&L = profit (option decayed, costs less to buy back)
        """
        total_current_value = 0.0
        remaining_dte = None
        point_value = pos["point_value"]

        for leg in pos["legs"]:
            symbol = leg["symbol"]
            security = algorithm.securities.get(symbol)
            if security is None:
                return None

            mid_price = (security.bid_price + security.ask_price) / 2.0
            if mid_price <= 0 and security.price > 0:
                mid_price = security.price

            # For short legs (negative quantity), cost to close is positive
            # For long legs (positive quantity), value is positive
            total_current_value += mid_price * leg["quantity"]

            # DTE from any leg (all same expiry)
            if remaining_dte is None:
                remaining_dte = (leg["expiry"] - algorithm.time).days

        # Entry credit is positive (we received premium)
        # Current value: negative means it costs us to close (losing)
        # P&L = (entry_credit + current_market_value) * point_value
        # entry_credit is total premium received (positive)
        # current_market_value: sum of (mid * quantity) — short legs have neg qty
        entry_credit_total = pos["entry_credit"]
        unrealised_pnl = (entry_credit_total + total_current_value) * point_value

        return {
            "unrealised_pnl": unrealised_pnl,
            "remaining_dte": remaining_dte if remaining_dte is not None else 0,
            "current_value": total_current_value,
        }

    def close_position(self, pos_id, reason, details=""):
        """Mark a position as closed. Actual order submission done by execution_manager."""
        if pos_id in self.positions:
            self.positions[pos_id]["status"] = "closed"
            self.positions[pos_id]["exit_reason"] = reason
            self.positions[pos_id]["exit_details"] = details
            return self.positions.pop(pos_id)
        return None

    def get_positions_for_asset(self, asset_key):
        """Get all active positions for a given underlying."""
        return [p for p in self.positions.values()
                if p["underlying"] == asset_key and p["status"] == "active"]

    def get_open_count(self, asset_key=None):
        """Count active positions, optionally filtered by asset."""
        if asset_key:
            return len(self.get_positions_for_asset(asset_key))
        return len([p for p in self.positions.values() if p["status"] == "active"])

    def get_youngest_position_age(self, asset_key, current_time):
        """Age in days of the newest position on an asset. None if no positions."""
        positions = self.get_positions_for_asset(asset_key)
        if not positions:
            return None
        newest = max(positions, key=lambda p: p["entry_date"])
        return (current_time - newest["entry_date"]).days

    def get_aggregate_risk(self):
        """Sum of max_loss across all active positions."""
        return sum(p["max_loss"] for p in self.positions.values()
                   if p["status"] == "active")

    def get_aggregate_unrealised_pnl(self, algorithm):
        """Sum of unrealised P&L across all active positions."""
        total = 0.0
        for pos in self.positions.values():
            if pos["status"] != "active":
                continue
            pnl_info = self._calculate_pnl(algorithm, pos)
            if pnl_info:
                total += pnl_info["unrealised_pnl"]
        return total
