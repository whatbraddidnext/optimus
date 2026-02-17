# execution_manager.py — Optimus Execution Manager
# Version: v2.001
#
# Manages spread order submission, fill tracking, and close orders.
# Handles QuantConnect order API for multi-leg options spreads.

import config as cfg


class ExecutionManager:
    """Submits and tracks credit spread orders on QuantConnect.

    Responsibilities:
        - Submit put credit spread as a combo order (sell short put, buy long put)
        - Track order status and fills
        - Submit close orders (buy back the spread)
        - Log fill details and slippage
    """

    VERSION = "v2.001"

    def __init__(self, algorithm):
        self.algo = algorithm
        self._pending_orders = {}  # order_id -> order_info

    def open_spread(self, spread_candidate, contracts, position_id):
        """Submit a put credit spread order.

        Args:
            spread_candidate: SpreadCandidate from spread_builder.
            contracts: Number of contracts (int).
            position_id: Unique position identifier from trade_tracker.

        Returns:
            dict: {success, order_tickets, detail}
        """
        try:
            # Sell the short put (higher strike) — positive quantity
            short_symbol = self._get_option_symbol(
                spread_candidate.underlying,
                spread_candidate.expiry,
                spread_candidate.short_strike,
                is_put=True)

            # Buy the long put (lower strike) — negative quantity from our perspective
            long_symbol = self._get_option_symbol(
                spread_candidate.underlying,
                spread_candidate.expiry,
                spread_candidate.long_strike,
                is_put=True)

            if short_symbol is None or long_symbol is None:
                return {
                    "success": False,
                    "order_tickets": [],
                    "detail": "Could not resolve option symbols",
                }

            # Submit as market orders for reliability
            # In production, consider limit orders at mid-market
            short_ticket = self.algo.market_order(short_symbol, -contracts)
            long_ticket = self.algo.market_order(long_symbol, contracts)

            order_info = {
                "position_id": position_id,
                "short_ticket": short_ticket,
                "long_ticket": long_ticket,
                "spread_candidate": spread_candidate,
                "contracts": contracts,
            }
            self._pending_orders[position_id] = order_info

            self.algo.log(
                f"[EXECUTION] Spread order submitted — "
                f"Sell {contracts}x {spread_candidate.short_strike}P / "
                f"Buy {contracts}x {spread_candidate.long_strike}P "
                f"(target credit ${spread_candidate.net_credit:.2f})")

            return {
                "success": True,
                "order_tickets": [short_ticket, long_ticket],
                "detail": "Spread order submitted",
            }

        except Exception as e:
            self.algo.log(f"[EXECUTION] Order submission failed: {e}")
            return {
                "success": False,
                "order_tickets": [],
                "detail": f"Order failed: {e}",
            }

    def close_spread(self, position, reason):
        """Close an existing spread position.

        Args:
            position: Position dict from trade_tracker.
            reason: ExitReason enum.

        Returns:
            dict: {success, detail}
        """
        try:
            short_symbol = position.get("short_symbol")
            long_symbol = position.get("long_symbol")
            contracts = position.get("contracts", 0)

            if short_symbol is None or long_symbol is None:
                return {"success": False,
                        "detail": "Missing symbols for close"}

            # Buy back short put, sell long put
            short_close = self.algo.market_order(short_symbol, contracts)
            long_close = self.algo.market_order(long_symbol, -contracts)

            self.algo.log(
                f"[EXECUTION] Close order submitted — "
                f"Position {position['id']} ({reason.value})")

            return {"success": True, "detail": f"Close submitted ({reason.value})"}

        except Exception as e:
            self.algo.log(f"[EXECUTION] Close order failed: {e}")
            return {"success": False, "detail": f"Close failed: {e}"}

    def _get_option_symbol(self, underlying, expiry, strike, is_put=True):
        """Resolve a QuantConnect option symbol.

        Args:
            underlying: Ticker string.
            expiry: Expiration datetime.
            strike: Strike price.
            is_put: True for put, False for call.

        Returns:
            Symbol object or None.
        """
        try:
            option_type = 1 if is_put else 0  # QC: Put=1, Call=0
            # Use the algorithm's option symbol resolution
            canonical = getattr(self.algo, '_spx_option', None)
            if canonical is None:
                return None
            return self.algo.symbol(
                f"{underlying} {expiry.strftime('%y%m%d')}{'P' if is_put else 'C'}"
                f"{int(strike * 1000):08d}")
        except Exception:
            # Fallback: iterate known contracts
            return None

    def check_pending_orders(self):
        """Check status of pending orders and log fills.

        Returns:
            list of position_ids that have been fully filled.
        """
        filled = []
        for pos_id, info in list(self._pending_orders.items()):
            short_filled = info["short_ticket"].status == 3  # Filled
            long_filled = info["long_ticket"].status == 3

            if short_filled and long_filled:
                short_fill = info["short_ticket"].average_fill_price
                long_fill = info["long_ticket"].average_fill_price
                actual_credit = short_fill - long_fill

                sc = info["spread_candidate"]
                slippage = sc.net_credit - actual_credit

                self.algo.log(
                    f"[EXECUTION] Spread filled — Position {pos_id} "
                    f"Short fill: ${short_fill:.2f}, Long fill: ${long_fill:.2f}, "
                    f"Actual credit: ${actual_credit:.2f} "
                    f"(target: ${sc.net_credit:.2f}, "
                    f"slippage: ${slippage:.2f})")

                filled.append(pos_id)
                del self._pending_orders[pos_id]

        return filled
