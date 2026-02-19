# execution_manager.py — Optimus v2.0-MVP
# Iron condor order submission and fill tracking
# Handles combo orders with leg-by-leg fallback

MODULE_VERSION = "1.0"


class ExecutionManager:
    """Submits iron condor orders and tracks fills.

    MVP: Leg-by-leg market orders with slippage modelling.
    QC combo orders can be unreliable for futures options,
    so we submit each leg individually.

    Order sequence for IC entry:
    1. Sell short call
    2. Buy long call
    3. Sell short put
    4. Buy long put

    Order sequence for IC exit (close all legs):
    1. Buy short call (close)
    2. Sell long call (close)
    3. Buy short put (close)
    4. Sell long put (close)
    """

    def __init__(self, algorithm):
        self.algo = algorithm
        self._pending_orders = {}

    def submit_iron_condor_entry(self, ic_legs, contracts):
        """Submit entry orders for an iron condor.

        Args:
            ic_legs: IronCondorLegs object
            contracts: Number of contracts

        Returns:
            List of order tickets or None on failure
        """
        tickets = []

        try:
            # Short call — sell to open
            ticket = self.algo.market_order(
                ic_legs.short_call.symbol, -contracts
            )
            tickets.append(("short_call", ticket))

            # Long call — buy to open
            ticket = self.algo.market_order(
                ic_legs.long_call.symbol, contracts
            )
            tickets.append(("long_call", ticket))

            # Short put — sell to open
            ticket = self.algo.market_order(
                ic_legs.short_put.symbol, -contracts
            )
            tickets.append(("short_put", ticket))

            # Long put — buy to open
            ticket = self.algo.market_order(
                ic_legs.long_put.symbol, contracts
            )
            tickets.append(("long_put", ticket))

            self.algo.debug(
                f"[EXEC] IC entry submitted: {contracts}x "
                f"{ic_legs.summary()}"
            )
            return tickets

        except Exception as e:
            self.algo.error(f"[EXEC] IC entry failed: {e}")
            return None

    def submit_iron_condor_exit(self, position_state):
        """Submit exit orders to close all legs of an iron condor.

        Args:
            position_state: PositionState dict with leg symbols and quantities

        Returns:
            List of order tickets or None on failure
        """
        tickets = []

        try:
            for leg in position_state["legs"]:
                symbol = leg["symbol"]
                quantity = leg["quantity"]
                # Close = opposite direction
                close_qty = -quantity
                ticket = self.algo.market_order(symbol, close_qty)
                tickets.append((leg["type"], ticket))

            self.algo.debug(
                f"[EXEC] IC exit submitted: {position_state['underlying']} "
                f"position {position_state['id']}"
            )
            return tickets

        except Exception as e:
            self.algo.error(f"[EXEC] IC exit failed: {e}")
            return None

    def get_fill_price(self, ticket):
        """Extract fill price from order ticket."""
        if ticket is None:
            return None
        if hasattr(ticket, "average_fill_price"):
            return ticket.average_fill_price
        return None
