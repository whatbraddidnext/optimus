# trade_tracker.py — Optimus v2.0-MVP
# Trade logging, performance metrics, complete audit trail
# Every decision logged for post-trade analysis

MODULE_VERSION = "1.0"


class TradeTracker:
    """Records all trade activity and calculates performance metrics.

    Tracks:
    - Every entry with gate audit trail
    - Every exit with reason and P&L
    - Running statistics (win rate, profit factor, avg win/loss)
    - Per-asset and per-regime breakdowns
    """

    def __init__(self, algorithm):
        self.algo = algorithm
        self.closed_trades = []
        self.entry_log = []
        self.skip_log = []

        # Running statistics
        self.total_wins = 0
        self.total_losses = 0
        self.gross_profit = 0.0
        self.gross_loss = 0.0

    def log_entry(self, position_state, signal):
        """Log a trade entry with full context."""
        entry = {
            "id": position_state["id"],
            "underlying": position_state["underlying"],
            "entry_date": str(position_state["entry_date"]),
            "contracts": position_state["contracts"],
            "entry_credit": position_state["entry_credit"],
            "max_loss": position_state["max_loss"],
            "trend_score": position_state["entry_trend_score"],
            "iv_rank": position_state["entry_iv_rank"],
            "regime": position_state["entry_regime"],
            "call_delta": signal.call_delta,
            "put_delta": signal.put_delta,
            "legs": [
                {
                    "type": leg["type"],
                    "strike": leg["strike"],
                    "premium": leg["entry_premium"],
                }
                for leg in position_state["legs"]
            ],
        }
        self.entry_log.append(entry)

        self.algo.debug(
            f"[TRADE] ENTRY {position_state['underlying']} "
            f"{position_state['contracts']}x IC "
            f"credit={position_state['entry_credit']:.2f} "
            f"max_loss={position_state['max_loss']:.0f} "
            f"trend={position_state['entry_trend_score']:.2f} "
            f"IVR={position_state['entry_iv_rank']:.0f} "
            f"regime={position_state['entry_regime']}"
        )

    def log_skip(self, signal):
        """Log a skipped entry with rejection reason."""
        skip = {
            "underlying": signal.asset_key,
            "reason": signal.rejection_reason,
            "iv_rank": signal.iv_rank,
            "trend_score": signal.trend_score,
            "regime": signal.regime,
            "gates": signal.summary(),
        }
        self.skip_log.append(skip)

        self.algo.debug(f"[TRADE] SKIP {signal.summary()}")

    def log_exit(self, position_state, exit_reason, realised_pnl, exit_time):
        """Log a trade exit with P&L and reason."""
        days_held = (exit_time - position_state["entry_date"]).days

        trade = {
            "id": position_state["id"],
            "underlying": position_state["underlying"],
            "entry_date": str(position_state["entry_date"]),
            "exit_date": str(exit_time),
            "days_held": days_held,
            "contracts": position_state["contracts"],
            "entry_credit": position_state["entry_credit"],
            "realised_pnl": realised_pnl,
            "exit_reason": exit_reason,
            "trend_score": position_state["entry_trend_score"],
            "iv_rank": position_state["entry_iv_rank"],
            "regime": position_state["entry_regime"],
        }
        self.closed_trades.append(trade)

        # Update running stats
        if realised_pnl >= 0:
            self.total_wins += 1
            self.gross_profit += realised_pnl
        else:
            self.total_losses += 1
            self.gross_loss += abs(realised_pnl)

        self.algo.debug(
            f"[TRADE] EXIT {position_state['underlying']} "
            f"reason={exit_reason} "
            f"P&L=${realised_pnl:.0f} "
            f"held={days_held}d "
            f"record={self.total_wins}W/{self.total_losses}L"
        )

    @property
    def total_trades(self):
        return self.total_wins + self.total_losses

    @property
    def win_rate(self):
        if self.total_trades == 0:
            return 0.0
        return self.total_wins / self.total_trades * 100

    @property
    def profit_factor(self):
        if self.gross_loss == 0:
            return float("inf") if self.gross_profit > 0 else 0.0
        return self.gross_profit / self.gross_loss

    @property
    def avg_win(self):
        if self.total_wins == 0:
            return 0.0
        return self.gross_profit / self.total_wins

    @property
    def avg_loss(self):
        if self.total_losses == 0:
            return 0.0
        return self.gross_loss / self.total_losses

    @property
    def net_pnl(self):
        return self.gross_profit - self.gross_loss

    def summary(self):
        """Generate performance summary string."""
        if self.total_trades == 0:
            return "No trades yet"

        return (
            f"Trades: {self.total_trades} | "
            f"Win Rate: {self.win_rate:.1f}% | "
            f"PF: {self.profit_factor:.2f} | "
            f"Net P&L: ${self.net_pnl:,.0f} | "
            f"Avg Win: ${self.avg_win:,.0f} | "
            f"Avg Loss: ${self.avg_loss:,.0f}"
        )

    def log_daily_summary(self, equity, open_position_count, margin_pct, risk_state):
        """Log end-of-day summary to algorithm debug output."""
        self.algo.debug(
            f"[DAILY] Equity=${equity:,.0f} | "
            f"Open={open_position_count} | "
            f"Margin={margin_pct:.1%} | "
            f"Risk={risk_state} | "
            f"{self.summary()}"
        )
