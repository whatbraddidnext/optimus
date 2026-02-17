# conviction_scorer.py — Optimus Conviction Scorer
# Version: v2.001
#
# Multi-factor scoring that scales position size between 0.5x and 1.5x.
# Factors: IV Rank, VIX term structure, trend strength, BB depth,
#          GLD inverse signal, recent win rate.

import config as cfg
from shared.utils import clamp


class ConvictionScorer:
    """Scores trade conviction from multiple factors to adjust position size.

    Each factor contributes a positive or negative adjustment.
    The final score is clamped to [CONVICTION_MIN, CONVICTION_MAX].
    """

    VERSION = "v2.001"

    def __init__(self, indicators, market_analyzer, trade_tracker):
        self.ind = indicators
        self.market = market_analyzer
        self.tracker = trade_tracker

    def score(self):
        """Calculate conviction multiplier.

        Returns:
            dict: {
                multiplier: float (0.5 to 1.5),
                factors: list of (name, adjustment, detail),
                total_adjustment: float,
            }
        """
        factors = []
        total_adj = 0.0

        # Factor 1: IV Rank
        adj, detail = self._score_iv_rank()
        factors.append(("IV Rank", adj, detail))
        total_adj += adj

        # Factor 2: VIX Term Structure
        adj, detail = self._score_vix_term_structure()
        factors.append(("VIX Term Structure", adj, detail))
        total_adj += adj

        # Factor 3: Trend Strength
        adj, detail = self._score_trend_strength()
        factors.append(("Trend Strength", adj, detail))
        total_adj += adj

        # Factor 4: BB Depth
        adj, detail = self._score_bb_depth()
        factors.append(("BB Depth", adj, detail))
        total_adj += adj

        # Factor 5: GLD Inverse Signal
        adj, detail = self._score_gld()
        factors.append(("GLD Signal", adj, detail))
        total_adj += adj

        # Factor 6: Recent Win Rate
        adj, detail = self._score_recent_wins()
        factors.append(("Recent Win Rate", adj, detail))
        total_adj += adj

        multiplier = clamp(
            cfg.CONVICTION_BASE + total_adj,
            cfg.CONVICTION_MIN,
            cfg.CONVICTION_MAX)

        return {
            "multiplier": round(multiplier, 3),
            "factors": factors,
            "total_adjustment": round(total_adj, 3),
        }

    def _score_iv_rank(self):
        """IV Rank scoring: higher = more conviction."""
        iv_rank = self.ind.iv_rank()
        if iv_rank is None:
            return 0.0, "IV Rank unavailable"
        if iv_rank >= 70:
            return 0.15, f"IV Rank {iv_rank:.0f}% — high"
        elif iv_rank >= 60:
            return 0.05, f"IV Rank {iv_rank:.0f}% — moderate"
        elif iv_rank <= 55:
            return -0.10, f"IV Rank {iv_rank:.0f}% — near threshold"
        return 0.0, f"IV Rank {iv_rank:.0f}%"

    def _score_vix_term_structure(self):
        """VIX contango = positive conviction."""
        ratio = self.ind.vix_term_structure_ratio()
        if ratio is None:
            return 0.0, "VIX term structure unavailable"
        if ratio < 0.95:
            return 0.10, f"Strong contango ({ratio:.3f})"
        elif ratio < 1.0:
            return 0.05, f"Mild contango ({ratio:.3f})"
        return -0.05, f"Flat/backwardation ({ratio:.3f})"

    def _score_trend_strength(self):
        """How far SPX is above EMA — farther = more conviction."""
        distance = self.ind.spx_ema_distance_pct()
        if distance >= 5.0:
            return 0.10, f"SPX {distance:+.1f}% above EMA — strong"
        elif distance >= 2.0:
            return 0.05, f"SPX {distance:+.1f}% above EMA"
        elif distance > 0:
            return -0.05, f"SPX {distance:+.1f}% above EMA — barely"
        return -0.15, f"SPX {distance:+.1f}% vs EMA — below"

    def _score_bb_depth(self):
        """Deeper BB touch = richer premium opportunity."""
        spx = self.ind.spx_price()
        lower = self.ind.bb_lower()
        middle = self.ind.bb_middle()
        if spx is None or lower is None or middle is None:
            return 0.0, "BB data unavailable"

        bandwidth = middle - lower
        if bandwidth <= 0:
            return 0.0, "BB bandwidth zero"

        # How deep was the touch relative to the band width
        # A touch near 2.5 std is deeper than 2.0
        depth_ratio = (middle - spx) / bandwidth if spx < middle else 0
        if depth_ratio > 0.8:
            return 0.10, f"Deep pullback ({depth_ratio:.2f} of band width)"
        elif depth_ratio > 0.5:
            return 0.05, f"Moderate pullback ({depth_ratio:.2f})"
        return 0.0, f"Shallow or recovering ({depth_ratio:.2f})"

    def _score_gld(self):
        """GLD inverse signal conviction adjustment."""
        gld_assessment = self.market.assess_gld_signal()
        adj = gld_assessment["conviction_adj"]
        detail = gld_assessment["detail"]
        return adj, detail

    def _score_recent_wins(self):
        """Recent trade performance affects conviction."""
        stats = self.tracker.recent_stats(last_n=10)
        if stats["total"] < 5:
            return 0.0, f"Insufficient history ({stats['total']} trades)"
        win_rate = stats["win_rate"]
        if win_rate >= 80:
            return 0.10, f"Win rate {win_rate:.0f}% (last {stats['total']})"
        elif win_rate >= 70:
            return 0.05, f"Win rate {win_rate:.0f}%"
        elif win_rate < 60:
            return -0.10, f"Win rate {win_rate:.0f}% — below target"
        return 0.0, f"Win rate {win_rate:.0f}%"

    def to_log(self, result):
        """Format conviction score for logging."""
        lines = [f"[CONVICTION] Multiplier: {result['multiplier']:.2f}x "
                 f"(base {cfg.CONVICTION_BASE} + {result['total_adjustment']:+.3f})"]
        for name, adj, detail in result["factors"]:
            sign = "+" if adj >= 0 else ""
            lines.append(f"  {name}: {sign}{adj:.3f} — {detail}")
        return "\n".join(lines)
