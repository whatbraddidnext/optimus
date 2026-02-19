# OPTIMUS — Futures Options Premium Selling
## High-Level Design Document v1.0

**Strategy:** Systematic Futures Options Premium Selling (Trend-Adjusted Iron Condors & Strangles)
**Organisation:** Stargaze Capital
**Author:** Strategy Architecture Team
**Platform:** QuantConnect (LEAN) + Interactive Brokers
**Asset Class:** Futures Options (CME)
**Status:** Architecture — Ready for Engineering

---

## Document Control

| Version | Date | Author | Changes |
|---|---|---|---|
| 1.0 | Feb 2026 | Strategy Architecture | Initial HLD |

---

## Table of Contents

1. Executive Summary
2. Source of Alpha
3. Instrument Selection & Rationale
4. Strategy Architecture Overview
5. Per-Asset Parameter Configuration
6. Trend Gradient Engine (Skewed Wing Placement)
7. Signal Generator — Entry Logic
8. Trade Structure Selection (Tier System)
9. Position Management — Exit Logic
10. Rolling & Defence Mechanics
11. Regime Detection
12. Gold & FX Trend Suppress Filters (Portfolio Context)
13. Risk Manager
14. Position Sizing
15. Margin Management
16. Failsafe & Connection Recovery
17. Session Manager
18. Modular Architecture & File Structure
19. State Management
20. Notifications & Heartbeat
21. Configurable Parameters — Master Table
22. Backtesting Plan
23. Deployment Plan
24. Performance Targets
25. Known Risks & Mitigations
26. Engineering Notes & QC-Specific Guidance

---

## 1. Executive Summary

Optimus is a systematic futures options premium selling strategy that harvests the volatility risk premium across five uncorrelated futures underlyings. It sells trend-adjusted iron condors (default, defined risk) and strangles (upgrade tier, higher premium) on /ES, /GC, /CL, /ZB, and /6E, collecting theta decay from both sides of each trade.

The strategy is delta-neutral at inception but intentionally skews strike placement based on a measured trend gradient to align the structure with prevailing price drift. This skew improves win rate without introducing meaningful directional exposure.

Optimus serves as a portfolio diversifier and income generator within the Stargaze four-algorithm portfolio. It is structurally uncorrelated with Megatron (gold breakouts) and Bumblebee (equity momentum), profiting during low-volatility, rangebound conditions when those strategies are flat. An independent regime assessment prevents Optimus from selling premium on gold during breakout conditions (the same conditions where Megatron would be active). Optimus runs entirely independently — there is no direct logic link between algorithms.

**Target performance (own allocated capital):**
- CAGR: 12–19% (base case 19%)
- Sharpe: 1.0–1.3
- Sortino: 1.2–1.6
- Max drawdown: 14–18%
- Win rate: 80–83%

---

## 2. Source of Alpha

The volatility risk premium (VRP): implied volatility consistently exceeds realised volatility across asset classes. Market participants systematically overpay for portfolio insurance — puts in equities, hedges in commodities, protection in bonds and FX. By selling that insurance through options structures, Optimus harvests the difference between what the market prices in and what actually occurs.

This edge is well-documented academically and exploited institutionally. It persists because:

- Hedgers have structural demand for downside protection regardless of price.
- The risk premium compensates sellers for accepting tail risk — a risk that can be managed through defined-risk structures, position sizing, and diversification.
- Time decay (theta) is a mathematical certainty — every option loses time value daily, all else being equal. This creates a structural tailwind for sellers.

The additional alpha source is **trend-adjusted strike placement**. By measuring the gradient of price drift over the DTE window and skewing wing placement accordingly, Optimus positions the structure where the underlying is most likely to remain — improving win rate by an estimated 1–3% over symmetric placement.

**Why futures options specifically:**

| Advantage | Detail |
|---|---|
| SPAN margining | Risk-based margin calculation. A /ES strangle requiring $25K under Reg-T needs ~$10K under SPAN. 2–3× capital efficiency. |
| Richer premium | Commodity futures (/GC, /CL) carry higher implied vol than ETF equivalents (GLD, USO). More premium for same exposure. |
| Near 24-hour trading | ~23 hours/day reduces gap risk vs equities (17.5 hours closed overnight). Critical for premium sellers. |
| No PRIIPs restrictions | UK traders cannot buy SPY/QQQ options via IBKR. Futures options on /ES bypass this entirely. |
| Multi-asset diversification | Single platform access to equities, gold, crude, bonds, FX — genuinely uncorrelated macro drivers. |

---

## 3. Instrument Selection & Rationale

### 3.1 Universe

| Underlying | Contract | Sector | Macro Driver | Point Value | Correlation to /ES | Optimus Role |
|---|---|---|---|---|---|---|
| /ES | E-mini S&P 500 | Equities | Growth, risk sentiment | $50/pt | Baseline | Core — most liquid, tightest option spreads |
| /GC | Gold Futures | Precious metals | Real rates, safe haven | $100/pt | Low negative (-0.15) | Regime-conditional — ranging only (gold trend suppress filter) |
| /CL | Crude Oil | Energy | Supply/demand, geopolitics | $1,000/pt | Moderate (0.3) | Higher vol, richer premium, tighter management |
| /ZB | 30-Year US Treasury Bond | Bonds | Rates, Fed policy | $1,000/pt | Negative (-0.3) | Natural equity hedge |
| /6E | Euro FX | Currency | Rate differentials, ECB/Fed | $125,000/contract | Low (0.15) | Low correlation to all others |

### 3.2 Why Five Underlyings

Five underlyings across five genuinely different asset classes provide portfolio-level diversification within Optimus itself. The probability of all five moving against premium sellers simultaneously is low outside of systemic crises — and the regime detection and margin management systems address crisis scenarios directly.

The key correlation relationships:

- /ES and /ZB are negatively correlated (~-0.3). When equities sell off, bonds rally — the put side of /ES strangles suffers while /ZB positions benefit.
- /GC often rallies during equity selloffs (safe-haven bid), but this is handled by the gold trend suppress filter — Optimus only trades /GC during ranging conditions.
- /CL is driven by supply/demand fundamentals largely independent of equity/bond dynamics.
- /6E is driven by ECB/Fed rate differential expectations — fundamentally different from all others.

### 3.3 Liquidity Requirements

Before entering any position, the algorithm must verify minimum liquidity thresholds:

| Check | Threshold | Purpose |
|---|---|---|
| Bid-ask spread on short strike | < 15% of option mid price | Slippage control |
| Open interest on short strike | > 500 contracts | Exit liquidity |
| Daily volume on underlying future | > 50,000 contracts | Underlying liquidity |

If any check fails, the algorithm skips that underlying for the current cycle and logs the reason.

---

## 4. Strategy Architecture Overview

### 4.1 Core Flow

```
Market Data (futures + options chains)
    ↓
[Data & Indicator Engine] — IV rank, trend gradient, ATR, regime indicators
    ↓
[Regime Detector] ← determines if underlying is suitable for premium selling
    ↓
[Gold/FX Trend Suppress Filter] ← independent regime check for /GC and /6E
    ↓
[Signal Generator] — per-asset entry gates, IV rank filter, margin check
    ↓
[Trend Gradient Engine] — calculates skew, determines delta targets per side
    ↓
[Tier Selector] — iron condor (Tier 1) or strangle (Tier 2) based on conditions
    ↓
[Position Sizer] — max loss sizing for ICs, notional sizing for strangles
    ↓
[Risk Manager] ← veto power, margin cap check, correlation check
    ↓
[Execution Manager] — combo order submission, fill tracking
    ↓
[Position Manager] — daily P&L, profit target, loss limit, time stop, roll triggers
    ↓
[Trade Tracker] → [Notifications]
    ↓
[Diagnostics]
```

### 4.2 Cycle Timing

The strategy operates on a continuous cycle model:

| Parameter | Value |
|---|---|
| Entry DTE target | 45 days (range: 35–55) |
| Typical close | 15–25 days after entry |
| Max concurrent per underlying | Configurable per asset (see Section 5) |
| Stagger rule | New cycle eligible when existing position is ≥ 15 days old |
| Scan frequency | Daily at 15:00 ET (during NY session) |
| Management frequency | Twice daily: 10:00 ET and 15:00 ET |

---

## 5. Per-Asset Parameter Configuration

Each underlying has its own parameter set stored in a configuration dictionary. These values are the starting defaults — all are exposed for optimisation.

### 5.1 Master Configuration

```python
ASSET_CONFIG = {
    "ES": {
        "name": "E-mini S&P 500",
        "point_value": 50,
        "default_short_delta": 0.16,
        "min_short_delta": 0.10,
        "max_short_delta": 0.22,
        "wing_width_points": 50,
        "min_iv_rank": 35,
        "max_iv_rank": 75,
        "trend_lookback_days": 30,
        "trend_confirm_lookback_days": 10,
        "max_skew_delta": 0.22,
        "min_skew_delta": 0.10,
        "profit_target_pct": 50,
        "loss_limit_ic_pct": 100,     # % of max loss (IC is defined risk)
        "loss_limit_strangle_x": 2.0,  # × credit received
        "time_stop_dte": 21,
        "roll_trigger_delta": 0.30,
        "max_concurrent": 2,
        "tier2_eligible": True,
        "tier2_iv_rank_min": 40,
        "tier2_iv_rank_max": 65,
        "regime_filter": None,
        "min_dte_entry": 35,
        "max_dte_entry": 55,
    },
    "GC": {
        "name": "Gold Futures",
        "point_value": 100,
        "default_short_delta": 0.16,
        "min_short_delta": 0.10,
        "max_short_delta": 0.20,
        "wing_width_points": 50,
        "min_iv_rank": 40,
        "max_iv_rank": 65,
        "trend_lookback_days": 30,
        "trend_confirm_lookback_days": 10,
        "max_skew_delta": 0.20,
        "min_skew_delta": 0.10,
        "profit_target_pct": 50,
        "loss_limit_ic_pct": 100,
        "loss_limit_strangle_x": 2.0,
        "time_stop_dte": 21,
        "roll_trigger_delta": 0.30,
        "max_concurrent": 1,
        "tier2_eligible": False,       # No naked strangles on gold — breakout risk too high for undefined risk
        "tier2_iv_rank_min": None,
        "tier2_iv_rank_max": None,
        "regime_filter": "gold_trend_suppress",
        "min_dte_entry": 35,
        "max_dte_entry": 55,
    },
    "CL": {
        "name": "Crude Oil",
        "point_value": 1000,
        "default_short_delta": 0.14,   # Wider default — crude is volatile
        "min_short_delta": 0.10,
        "max_short_delta": 0.20,
        "wing_width_points": 3.0,
        "min_iv_rank": 30,
        "max_iv_rank": 70,
        "trend_lookback_days": 20,     # Shorter — crude trends shift faster
        "trend_confirm_lookback_days": 7,
        "max_skew_delta": 0.20,
        "min_skew_delta": 0.10,
        "profit_target_pct": 45,       # Take profits faster on crude
        "loss_limit_ic_pct": 100,
        "loss_limit_strangle_x": 1.75, # Tighter stop — crude gaps harder
        "time_stop_dte": 21,
        "roll_trigger_delta": 0.28,    # Earlier roll trigger
        "max_concurrent": 2,
        "tier2_eligible": True,
        "tier2_iv_rank_min": 40,
        "tier2_iv_rank_max": 60,       # Narrower window for crude strangles
        "regime_filter": None,
        "min_dte_entry": 35,
        "max_dte_entry": 50,           # Shorter max DTE — crude expiry cycles differ
    },
    "ZB": {
        "name": "30-Year US Treasury Bond",
        "point_value": 1000,
        "default_short_delta": 0.16,
        "min_short_delta": 0.10,
        "max_short_delta": 0.22,
        "wing_width_points": 2.0,
        "min_iv_rank": 35,
        "max_iv_rank": 75,
        "trend_lookback_days": 30,
        "trend_confirm_lookback_days": 10,
        "max_skew_delta": 0.22,
        "min_skew_delta": 0.10,
        "profit_target_pct": 50,
        "loss_limit_ic_pct": 100,
        "loss_limit_strangle_x": 2.0,
        "time_stop_dte": 21,
        "roll_trigger_delta": 0.30,
        "max_concurrent": 2,
        "tier2_eligible": True,
        "tier2_iv_rank_min": 40,
        "tier2_iv_rank_max": 65,
        "regime_filter": None,
        "min_dte_entry": 35,
        "max_dte_entry": 55,
    },
    "6E": {
        "name": "Euro FX",
        "point_value": 125000,
        "default_short_delta": 0.18,   # Wider default — FX premium is thinner
        "min_short_delta": 0.12,
        "max_short_delta": 0.22,
        "wing_width_points": 0.0100,
        "min_iv_rank": 30,
        "max_iv_rank": 70,
        "trend_lookback_days": 30,
        "trend_confirm_lookback_days": 10,
        "max_skew_delta": 0.22,
        "min_skew_delta": 0.12,
        "profit_target_pct": 50,
        "loss_limit_ic_pct": 100,
        "loss_limit_strangle_x": 2.0,
        "time_stop_dte": 21,
        "roll_trigger_delta": 0.30,
        "max_concurrent": 2,
        "tier2_eligible": True,
        "tier2_iv_rank_min": 40,
        "tier2_iv_rank_max": 65,
        "regime_filter": "fx_trend_suppress",
        "min_dte_entry": 35,
        "max_dte_entry": 55,
    },
}
```

### 5.2 Parameter Discipline

Every parameter must have a rationale, a valid range, and a default that works without optimisation. The engineer should never need to guess at a value.

| Principle | Rule |
|---|---|
| No magic numbers | Every constant comes from the config dictionary |
| Range validation | On initialisation, validate all parameters are within sane ranges |
| Optimisation exposure | All numeric parameters are sweepable via QC's optimisation framework |
| Per-asset isolation | Changing /CL parameters must not affect /ES behaviour |
| Versioning | Config changes are tracked in the version log |

---

## 6. Trend Gradient Engine (Skewed Wing Placement)

### 6.1 Purpose

Standard iron condors and strangles are symmetric — same delta on both sides, assuming equal probability of upward and downward moves. Over a 45-day holding period, this is rarely true. Equities drift upward on average. Gold trends in macro cycles. Crude follows supply dynamics.

The Trend Gradient Engine measures the prevailing price drift for each underlying and skews the strike placement to give the trending side more room while tightening the counter-trend side. This is not a directional bet — it is a probabilistic alignment that improves win rate by positioning the structure where price is most likely to remain.

### 6.2 Trend Score Calculation

**Step 1: Primary slope**
Compute the linear regression slope of daily closing prices over the primary lookback window (default: 30 days, configurable per asset).

```
primary_slope = LinearRegression(close, trend_lookback_days).slope
```

**Step 2: Normalise to daily percentage**
```
normalised_slope = primary_slope / current_price × 100
```

**Step 3: ATR-normalise to produce Trend Score**
```
daily_atr = ATR(trend_lookback_days) / current_price × 100
trend_score = clip(normalised_slope / (daily_atr × SCALING_FACTOR), -1.0, +1.0)
```

The `SCALING_FACTOR` (default: 0.5, optimisable range: 0.3–0.8) controls sensitivity. Lower values produce more extreme scores from smaller trends; higher values require stronger trends to generate skew.

**Step 4: Confirmation filter**
Compute a secondary slope over the confirmation lookback (default: 10 days).

```
confirm_slope = LinearRegression(close, trend_confirm_lookback_days).slope
```

If the confirmation slope and primary slope **disagree in direction**, force `trend_score = 0` (symmetric placement). This prevents the skew from chasing a trend that is already reversing.

### 6.3 Delta Skew Mapping

The Trend Score maps to call-side and put-side delta targets:

| Trend Score Range | Call Delta | Put Delta | Interpretation |
|---|---|---|---|
| +0.8 to +1.0 (strong uptrend) | asset.min_skew_delta (e.g., 0.10) | asset.max_skew_delta (e.g., 0.22) | Maximum room above, lean hard into puts |
| +0.3 to +0.8 (moderate uptrend) | Interpolated toward min | Interpolated toward max | Mild to moderate skew |
| -0.3 to +0.3 (no clear trend) | asset.default_short_delta | asset.default_short_delta | Symmetric — standard placement |
| -0.8 to -0.3 (moderate downtrend) | Interpolated toward max | Interpolated toward min | Mirror of uptrend |
| -1.0 to -0.8 (strong downtrend) | asset.max_skew_delta | asset.min_skew_delta | Maximum room below |

**Interpolation formula:**

```
For trend_score > 0.3:
  skew_factor = (trend_score - 0.3) / 0.7   # 0 to 1.0 as score goes from 0.3 to 1.0
  call_delta = default_delta - skew_factor × (default_delta - min_skew_delta)
  put_delta  = default_delta + skew_factor × (max_skew_delta - default_delta)

For trend_score < -0.3:
  Mirror of above (swap call/put)

For -0.3 ≤ trend_score ≤ +0.3:
  call_delta = default_delta
  put_delta  = default_delta
```

### 6.4 Skew Override — Strong Trend Suppression

If the trend score exceeds ±0.9 AND the underlying's IV rank is below 30, the algorithm **skips the trade entirely** for that underlying. This condition indicates a strong directional trend with low volatility — premium is thin and the structure is likely to be breached. For /GC specifically, a score above ±0.8 triggers the gold trend suppress filter (see Section 12).

### 6.5 Expected Impact

Based on historical analysis of 45-day windows across the five underlyings:

- Symmetric placement win rate: ~80% (16-delta, managed)
- Trend-adjusted win rate: ~81.5–83% (skewed deltas, managed)
- The 1.5–3% improvement converts ~2–4 additional trades per year from losers to winners
- At a blended swing value of ~$1,500 per conversion: +$3,000–$6,000/year additional P&L
- No additional risk — the total premium collected is similar; only the placement changes

---

## 7. Signal Generator — Entry Logic

### 7.1 Multi-Gate Entry System

All gates must pass before an entry signal is generated. Gates are evaluated sequentially — failure at any gate short-circuits the remaining checks.

| Gate | Condition | Purpose |
|---|---|---|
| 1. Regime | Underlying is in RANGING or LOW_VOL regime (see Section 11) | Only sell premium in suitable conditions |
| 2. Trend Suppress Filter | /GC: not in breakout/trending conditions. /6E: not in strong trend (see Section 12) | Avoid selling premium against strong trends on overlapping underlyings |
| 3. IV Rank | Per-asset IV rank within [min_iv_rank, max_iv_rank] | Premium must be sufficient to compensate risk |
| 4. DTE Availability | Options chain with DTE in [min_dte_entry, max_dte_entry] exists with sufficient liquidity | Contract must exist and be tradeable |
| 5. Margin Available | Current margin utilisation + estimated new position margin < margin_cap | Never exceed margin budget |
| 6. Concurrent Limit | Open positions on this underlying < max_concurrent | Per-asset exposure control |
| 7. Stagger Check | If existing position on same underlying: age ≥ stagger_min_days (default: 15) | Diversify expiry dates |
| 8. Trend Score Valid | trend_score is not in suppression zone (±0.9 AND IV rank < 30) | Don't sell premium against strong trends in low vol |
| 9. Correlation Check | If ≥ 3 underlyings have active positions showing loss > 0.5× credit: pause new entries | Detect correlated adverse moves |

### 7.2 IV Rank Calculation

IV Rank represents where current implied volatility sits relative to its own 52-week range:

```
iv_rank = (current_iv - 52_week_low_iv) / (52_week_high_iv - 52_week_low_iv) × 100
```

For futures options, IV is derived from the at-the-money (ATM) option at the target DTE. If the exact DTE is not available, interpolate between the two nearest expiration cycles.

The IV Rank is calculated per underlying — **not** derived from VIX. VIX measures S&P 500 implied vol only and is a poor proxy for gold, crude, bond, and FX volatility.

### 7.3 Strike Selection

Once the entry signal fires, the algorithm selects strikes:

1. **Determine delta targets** from the Trend Gradient Engine (Section 6)
2. **Find the option chain** at the target DTE (nearest available within the DTE range)
3. **Select the short call strike** — the strike whose delta is closest to `call_delta_target`
4. **Select the short put strike** — the strike whose delta (absolute value) is closest to `put_delta_target`
5. **For iron condors (Tier 1):** Select long wings at `short_strike ± wing_width_points`
6. **Verify liquidity** (bid-ask spread, open interest) on all legs
7. **Calculate total credit** and **maximum loss** (IC: wing width × point value - credit)

If the selected strikes fail the liquidity check, widen by one strike increment and re-check. If still illiquid, skip the trade.

---

## 8. Trade Structure Selection (Tier System)

### 8.1 Tier 1 — Iron Condors (Default)

The base case for all entries. Defined risk, predictable maximum loss, suitable for all IV regimes within the entry window.

| Component | Description |
|---|---|
| Structure | Short call + long call (call spread) AND short put + long put (put spread) |
| Max loss | (Wing width × point value) - credit received. Known at entry. |
| Margin | Typically lower than strangles. Width of widest spread minus credit. |
| When used | Always eligible when entry gates pass |

### 8.2 Tier 2 — Strangles (Upgrade)

Higher premium, higher risk. Only activated when conditions make the soft stop reliable.

| Component | Description |
|---|---|
| Structure | Short call + short put. No long wings. Undefined risk. |
| Max loss | Theoretically unlimited. Managed via soft stop at loss_limit_strangle_x × credit. |
| Margin | SPAN-based. Typically higher than IC margin. |
| When used | Only when ALL of the following are true |

**Tier 2 Activation Conditions:**

| Condition | Rationale |
|---|---|
| Asset is tier2_eligible = True | /GC is excluded — gold's breakout tendency makes undefined risk inappropriate |
| IV rank within [tier2_iv_rank_min, tier2_iv_rank_max] | Moderate vol — enough premium but not crisis conditions |
| VIX between 18 and 30 | Broad market not in extreme fear or complacency |
| Margin utilisation < 40% | Buffer for margin expansion |
| No active correlation alert (Gate 9) | Markets are not in correlated drawdown |
| Underlying's 5-day realised vol < 1.5× 30-day realised vol | No recent volatility spikes |

If any condition fails, the entry defaults to Tier 1 (iron condor).

### 8.3 Structure Selection Decision Tree

```
Entry gates pass → Check Tier 2 conditions:
  All Tier 2 conditions met?
    → YES: Construct strangle
    → NO:  Construct iron condor
```

The engineer should log which tier was selected and why, including which Tier 2 condition(s) failed if applicable. This data is critical for optimisation.

---

## 9. Position Management — Exit Logic

Position management runs on every management scan (twice daily: 10:00 ET, 15:00 ET). Each open position is evaluated against the following exit conditions in priority order.

### 9.1 Exit Priority Hierarchy

| Priority | Exit Condition | Action | Applies To |
|---|---|---|---|
| 1 | **Catastrophic stop** — underlying has moved > 3× ATR(14) from entry in a single session | Immediate market close on all legs | Both tiers |
| 2 | **Loss limit (IC)** — position P&L ≤ -(max_loss × loss_limit_ic_pct / 100) | Close all legs | Tier 1 only |
| 3 | **Loss limit (strangle)** — position P&L ≤ -(credit × loss_limit_strangle_x) | Close all legs | Tier 2 only |
| 4 | **Roll trigger** — either short leg's delta has reached roll_trigger_delta | Execute roll (see Section 10) | Both tiers |
| 5 | **Profit target** — position P&L ≥ credit × (profit_target_pct / 100) | Close all legs | Both tiers |
| 6 | **Time stop** — remaining DTE ≤ time_stop_dte | Close all legs regardless of P&L | Both tiers |

### 9.2 P&L Tracking Per Position

Each position tracks:

| Field | Description |
|---|---|
| entry_credit | Total credit received at entry (sum of all leg premiums) |
| current_value | Current market value of the position (cost to close) |
| unrealised_pnl | entry_credit - current_value (positive = profit) |
| max_loss | Wing width × point value - credit (Tier 1) or credit × strangle loss multiplier (Tier 2) |
| days_held | Calendar days since entry |
| remaining_dte | Days to expiration of the options |
| short_call_delta | Current delta of the short call leg |
| short_put_delta | Current delta (absolute) of the short put leg |

### 9.3 No Holding to Expiration

Under no circumstances does the algorithm hold a position to expiration. The time stop at 21 DTE is a hard exit. Gamma risk accelerates exponentially in the final 21 days — a small underlying move produces disproportionate option price changes. The time stop eliminates this risk entirely.

---

## 10. Rolling & Defence Mechanics

### 10.1 When to Roll

A roll is triggered when either short leg's delta reaches the `roll_trigger_delta` threshold (default: 0.30, meaning the underlying has moved significantly toward that strike and the probability of the strike being breached has risen materially).

### 10.2 Roll Procedure

| Step | Action |
|---|---|
| 1 | Identify the tested leg (the one with delta ≥ roll_trigger_delta) |
| 2 | Buy to close the tested leg |
| 3 | Sell to open a new leg: same delta target as original entry, but in the next available expiration cycle (~30 DTE out) |
| 4 | The untested leg remains in place (it is profitable and decaying) |
| 5 | Calculate the net credit/debit of the roll |
| 6 | Update the position record: new credit = original credit ± roll adjustment |
| 7 | If the roll produces a net debit > 50% of original credit: close entire position instead |

### 10.3 Maximum Rolls Per Position

| Parameter | Value | Rationale |
|---|---|---|
| Max rolls per position | 2 | Beyond 2 rolls, the position is fighting the trend. Cut the loss. |
| Min days between rolls | 5 | Prevent roll-churn in whipsaw markets |

### 10.4 Inverted Strangles

If the underlying moves through one side entirely, the strangle becomes inverted (put strike > call strike after rolling). This is not automatically closed — the position still has time value and may recover. However:

- The time stop at 21 DTE still applies
- The loss limit still applies
- If the inversion exceeds the wing width equivalent (what the IC width would have been), close immediately

### 10.5 Roll Logging

Every roll must be logged with: underlying, original strike, new strike, roll credit/debit, current underlying price, delta at roll time, roll number (1 or 2). This data is essential for evaluating whether the rolling rules are contributing to or detracting from performance.

---

## 11. Regime Detection

### 11.1 Purpose

Not all market conditions are suitable for premium selling. The regime detector classifies each underlying's current state and gates entry accordingly.

### 11.2 Regime Definitions

| Regime | Indicators | Optimus Behaviour |
|---|---|---|
| RANGING | ADX(14) < 25 AND price within 1.5 ATR of 20-day SMA AND bandwidth > 20th percentile | Active — ideal conditions. Symmetric or mildly skewed ICs. |
| LOW_VOL | ADX(14) < 20 AND bandwidth < 20th percentile (squeeze) | Active but cautious — premium is thin. Wider deltas. IV rank filter more important. |
| TRENDING | ADX(14) ≥ 25 AND price > 1.5 ATR from 20-day SMA | Reduced — enter only with strong trend-adjusted skew. Skip if trend_score > ±0.9. |
| HIGH_VOL | Realised vol (20-day) > 2× 60-day average OR underlying moved > 3% in a session | Pause — no new entries. Manage existing positions only. |
| CRISIS | VIX > 35 (for /ES) OR per-asset equivalent threshold OR 3+ underlyings in HIGH_VOL simultaneously | Halt — close positions approaching loss limits. No new entries on any underlying. |

### 11.3 Regime Transition Rules

- Regime changes require **2 consecutive daily closes** confirming the new state (prevents whipsaw classification)
- Transitions from RANGING/LOW_VOL → TRENDING: existing positions remain but are managed more aggressively (tighten profit targets to 40%)
- Transitions to HIGH_VOL or CRISIS: no new entries; existing positions managed by normal exit rules
- Return to RANGING after HIGH_VOL requires **5 consecutive days** of declining realised vol

### 11.4 Per-Asset Crisis Thresholds

Since VIX only measures /ES vol, each underlying needs its own crisis threshold:

| Underlying | Crisis Trigger |
|---|---|
| /ES | VIX > 35 |
| /GC | 5-day realised vol > 2.5% daily (annualised ~40%) |
| /CL | 5-day realised vol > 4% daily (annualised ~63%) or intraday move > 5% |
| /ZB | 5-day realised vol > 1.5% daily (annualised ~24%) |
| /6E | 5-day realised vol > 1.2% daily (annualised ~19%) |

---

## 12. Gold & FX Trend Suppress Filters (Portfolio Context)

### 12.1 Purpose

Two of Optimus's underlyings overlap with other strategies in the broader Stargaze portfolio:
- **/GC** (gold) — also traded by Megatron (breakout strategy, separate deployment)
- **/6E** (EUR/USD) — also traded by Sideways (forex carry, separate deployment)

These overlaps are not a problem because the strategies target opposing market conditions. However, the market conditions that make premium selling unprofitable on these underlyings (strong trends, breakouts) happen to be the same conditions the other strategies exploit. Optimus suppresses entries during these conditions purely based on its own analysis — this is good risk management regardless of what other algorithms exist.

### 12.2 Design Principle — Fully Independent

Each Stargaze algorithm is a standalone deployment. Optimus has no awareness of whether Megatron or Sideways are deployed, running, or holding positions. The regime assessment is based entirely on observable market conditions (price, volatility, trend indicators) computed within Optimus itself. This means:

- Optimus can be deployed, tested, and run without any other Stargaze algorithm being live
- No shared Object Store keys, no shared state files, no API calls between algorithms
- The "handoff" is a market-condition filter, not an inter-algorithm signal
- If Megatron is never built, Optimus still correctly avoids selling premium during gold breakout conditions

### 12.3 /GC Gold Trend Suppress Logic

| Condition | Optimus /GC Behaviour |
|---|---|
| Bandwidth > 20th percentile AND ADX < 25 AND trend_score between -0.6 and +0.6 | **Active** — gold is ranging, ideal for ICs |
| Bandwidth dropping toward 20th percentile AND ADX rising | **Caution** — squeeze may be forming. No new entries. Existing positions managed normally. |
| Bandwidth < 20th percentile (squeeze) OR trend_score > ±0.8 | **Inactive** — breakout conditions. Close existing /GC positions at next profit opportunity or time stop. |
| ADX > 30 AND price > 2 ATR from 50-day EMA | **Inactive** — gold is trending hard. Not suitable for premium selling. |

### 12.4 /6E Independent Trend Assessment

The same principle applies to EUR/USD. Optimus independently assesses whether /6E is in trending or ranging conditions. Strong trends on EUR/USD are poor environments for premium selling — this is true regardless of any other strategy running on the same pair.

| Condition | Optimus /6E Behaviour |
|---|---|
| EUR/USD trend_score between -0.5 and +0.5 AND ADX < 25 | **Active** — ranging, suitable for premium selling |
| EUR/USD trend_score > ±0.7 AND ADX > 25 | **Caution** — strong trend developing. Reduce max_concurrent to 1. Widen deltas. |
| EUR/USD trend_score > ±0.9 | **Reduced** — only enter if IV rank > 50 (premium compensates for trend risk) |

Note: Unlike the /GC handoff, /6E is never fully deactivated. FX ranges even during trends are typically wider relative to premium than gold, making premium selling viable alongside carry momentum.

---

## 13. Risk Manager

### 13.1 Veto Power

The Risk Manager has absolute veto power over all entries and can force exits. No trade bypasses risk checks.

### 13.2 Risk Rules

| Rule | Trigger | Action |
|---|---|---|
| Margin cap | Margin utilisation ≥ margin_cap (default: 45%) | Block all new entries until below cap |
| Per-underlying loss limit | Cumulative unrealised loss on one underlying > 5% of total equity | Close worst position on that underlying |
| Daily loss limit | Total daily P&L across all Optimus positions < -3% of equity | Halt all new entries for remainder of day |
| Weekly loss limit | Total weekly P&L < -5% of equity | Halt all new entries for remainder of week. Tighten profit targets to 40% on existing. |
| Monthly drawdown limit | MTD P&L < -8% of equity | Halt all new entries for remainder of month. Close any position > 21 DTE. |
| Correlation alert | ≥ 3 underlyings simultaneously showing unrealised loss > 0.5× credit | Halt new entries. Flag for review. |
| Portfolio-level breaker | Aggregate Stargaze portfolio drawdown > 15% (manual intervention — not automated cross-algorithm) | Reduce Optimus to 50% of normal capacity |

### 13.3 Risk State Machine

```
NORMAL → (daily loss > 3%) → DAY_HALT
NORMAL → (weekly loss > 5%) → WEEK_HALT
NORMAL → (monthly DD > 8%) → MONTH_HALT
NORMAL → (correlation alert) → CORR_ALERT
DAY_HALT → (next trading day) → NORMAL
WEEK_HALT → (next trading week) → NORMAL
MONTH_HALT → (next month) → NORMAL
CORR_ALERT → (< 2 underlyings in loss) → NORMAL
```

---

## 14. Position Sizing

### 14.1 Core Principle

**Size by maximum loss, not premium received.** A $1,000 credit on an iron condor with 50-point wings on /ES risks $1,500 ($2,500 max loss - $1,000 credit). Size to the $1,500.

### 14.2 Iron Condor Sizing

```
max_loss_per_ic = (wing_width × point_value) - credit_received
contracts = floor(max_risk_per_trade / max_loss_per_ic)
```

Where:
```
max_risk_per_trade = equity × risk_pct_per_trade
```

Default `risk_pct_per_trade`: 2.5% (range: 1.5–3.5%)

### 14.3 Strangle Sizing

Since strangles have undefined risk, sizing uses a notional approach:

```
notional_exposure = underlying_price × point_value × contracts
max_notional_per_trade = equity × max_notional_pct
contracts = floor(max_notional_per_trade / (underlying_price × point_value))
```

Default `max_notional_pct`: 15% (range: 10–20%)

Additionally, the soft stop loss defines an expected maximum loss:
```
expected_max_loss = credit × loss_limit_strangle_x × contracts
```

This expected max loss must not exceed `risk_pct_per_trade × equity`. If it does, reduce contracts.

### 14.4 Aggregate Exposure Limits

| Limit | Default | Purpose |
|---|---|---|
| Total max loss across all open positions | 15% of equity | Portfolio-level risk cap |
| Max positions per underlying | Per-asset config | Concentration control |
| Total open positions across all underlyings | 12 | Complexity management |
| Margin utilisation cap | 45% | Reserve for margin expansion events |

---

## 15. Margin Management

### 15.1 SPAN Margin Estimation

SPAN margin is calculated by the exchange and varies with market conditions. The algorithm must estimate margin requirements before entry and track actual margin in real-time.

**Estimation approach:**

For iron condors:
```
estimated_margin = max(call_spread_width, put_spread_width) × point_value - credit
```

For strangles (conservative estimate):
```
estimated_margin = max(call_margin, put_margin) + other_side_premium
where call_margin ≈ underlying_price × point_value × 0.05  # ~5% of notional
where put_margin ≈ underlying_price × point_value × 0.05
```

These are approximations. The actual SPAN calculation is performed by IBKR and may differ. The algorithm should query IBKR's margin what-if endpoint where available and adjust the estimate accordingly.

### 15.2 Margin Expansion Protocol

During volatility spikes, SPAN margin requirements can double overnight. The algorithm must:

1. Track `margin_buffer_ratio = available_margin / total_margin_used`
2. If `margin_buffer_ratio < 2.0`: tighten profit targets to 40%, no new entries
3. If `margin_buffer_ratio < 1.5`: begin closing highest-margin positions (strangles first)
4. If `margin_buffer_ratio < 1.2`: close all strangle positions immediately; keep ICs (defined risk)
5. If `margin_buffer_ratio < 1.05`: close all positions — imminent margin call

### 15.3 Margin Reserve

The strategy must always maintain a margin reserve (default: 55% of capital). This reserve exists specifically to absorb margin expansion during volatile periods without forced liquidation.

---

## 16. Failsafe & Connection Recovery

### 16.1 Design Principle

The failsafe module operates on the assumption that any live connection will eventually fail. IBKR disconnects occur due to daily server resets (~23:45 ET), internet interruptions, login conflicts, and QuantConnect node restarts. The algorithm must survive all of these without orphaning positions.

### 16.2 State Persistence

On every state change (trade entry, exit, roll, regime transition, risk state change), the algorithm writes a serialised state snapshot to the QuantConnect Object Store.

**Persisted state:**

| Category | Fields |
|---|---|
| Open positions | Per-position: underlying, tier, structure type, legs (strikes, quantities), entry_credit, entry_date, roll_count, regime_at_entry, trend_score_at_entry |
| Strategy state | Per-asset: current_regime, last_entry_date, consecutive_losses. Global: risk_state, daily_pnl, weekly_pnl, monthly_pnl |
| Margin state | Total margin used, margin buffer ratio, last IBKR margin query result |
| Trade statistics | Running totals: wins, losses, gross_profit, gross_loss by underlying/tier/regime |
| Heartbeat | Last heartbeat timestamp, last broker status |

### 16.3 Recovery Protocol

On algorithm restart or broker reconnection:

1. Load last state snapshot from Object Store
2. Query IBKR for current open positions
3. Reconcile: for each persisted position, verify it exists in IBKR's response
4. If position exists in both: update current market values, resume management
5. If position in Object Store but not in IBKR: flag as orphaned, send CRITICAL alert, do not re-enter
6. If position in IBKR but not in Object Store: flag as untracked, send CRITICAL alert, apply default management rules
7. Resume normal operation

### 16.4 Broker Failure Alerts

Any broker connection failure or login issue triggers an immediate CRITICAL Telegram alert. The algorithm does not attempt to trade until the connection is confirmed restored.

---

## 17. Session Manager

### 17.1 Trading Windows

Futures options trade nearly 24 hours. However, not all hours are suitable:

| Session | Time (ET) | Behaviour |
|---|---|---|
| Pre-market scan | 09:00–09:30 | Regime assessment, prepare entry candidates |
| Primary entry window | 09:30–10:30 | Entry orders submitted if gates pass |
| Mid-day management | 13:00–14:00 | Position management scan |
| Afternoon management | 15:00–16:00 | Position management scan, entry window |
| After-hours | 16:00–09:00 | Monitor only. Catastrophic stops only. No new entries. |

### 17.2 Blackout Periods

| Event | Blackout Window | Affected Underlyings |
|---|---|---|
| FOMC announcement | 2 hours before through 2 hours after | All |
| US employment report (NFP) | 30 min before through 1 hour after | /ES, /ZB, /6E |
| CPI/PPI release | 30 min before through 1 hour after | All |
| OPEC meeting | 2 hours before through 2 hours after | /CL |
| ECB rate decision | 1 hour before through 1 hour after | /6E, /GC |

During blackouts: no new entries, no rolls. Existing positions are managed only by catastrophic stops and hard loss limits.

### 17.3 Options Expiration Handling

Any position with < 5 DTE is closed regardless of P&L. This should not occur under normal operation (time stop at 21 DTE), but serves as a safety net for edge cases (e.g., algorithm downtime preventing normal time stop execution).

---

## 18. Modular Architecture & File Structure

### 18.1 Project Structure

```
/Optimus/
├── main.py                     # Core algorithm, event handlers (<64KB)
├── signal_engine.py            # Multi-gate entry system, strike selection
├── trend_gradient.py           # Trend score calculation, delta skew mapping
├── tier_selector.py            # IC vs strangle decision logic
├── options_chain_manager.py    # Futures options chain handling, DTE selection, liquidity checks
├── position_manager.py         # Exit logic, P&L tracking, roll triggers
├── roll_manager.py             # Roll execution, inversion handling
├── risk_manager.py             # Portfolio risk, margin monitoring, circuit breakers
├── regime_detector.py          # Per-asset regime classification, handoff logic
├── position_sizer.py           # IC and strangle sizing, aggregate limits
├── margin_manager.py           # SPAN estimation, margin expansion protocol
├── execution_manager.py        # Combo order submission, fill tracking
├── trade_tracker.py            # Trade logging, performance metrics
├── session_manager.py          # Time windows, blackout calendar
├── notifications.py            # Telegram alerts, heartbeat
├── failsafe.py                 # State persistence, recovery, reconciliation
├── config.py                   # ASSET_CONFIG and all global parameters
├── diagnostics.py              # Analytics, attribution reporting
└── /shared/                    # Shared library (common to all Stargaze algos)
    ├── utils.py
    ├── constants.py
    └── sizing.py
```

### 18.2 Module Responsibilities

| Module | Responsibility | Key Constraint |
|---|---|---|
| main.py | Orchestration, QC event handlers, warmup | < 64KB |
| signal_engine.py | Gate evaluation, entry signal generation | Deterministic: same inputs → same outputs |
| trend_gradient.py | Trend score, skew calculation | Pure calculation — no side effects |
| tier_selector.py | Structure selection (IC vs strangle) | Logs selection reason |
| options_chain_manager.py | Chain parsing, strike selection, liquidity validation | Handles missing chains gracefully |
| position_manager.py | All exit logic: profit target, loss limit, time stop, roll trigger | Priority-ordered exit evaluation |
| roll_manager.py | Roll execution, max roll tracking, inversion detection | Never rolls more than max_rolls times |
| risk_manager.py | Veto power, margin cap, loss limits, correlation alert | Can block any trade, can force any exit |
| regime_detector.py | Per-asset regime, cross-strategy handoff | 2-day confirmation required for transitions |
| position_sizer.py | Contract quantity calculation | Never exceeds aggregate limits |
| margin_manager.py | SPAN estimation, margin expansion protocol | Conservative estimates |
| execution_manager.py | Order submission, partial fill handling | Fault-tolerant |
| trade_tracker.py | Complete audit trail | Every decision logged |
| session_manager.py | Time-aware gating | Blackout calendar maintained |
| notifications.py | Telegram alerts | Never crashes the algorithm |
| failsafe.py | State persistence and recovery | Writes on every state change |
| config.py | All parameters | Single source of truth |
| diagnostics.py | Post-trade analytics | Not real-time decision-making |

### 18.3 Module Versioning

Each module carries its own version number. The algorithm's top-level version captures the combination:

```
Optimus v1.003 = main v1, signal_engine v1, trend_gradient v1, risk_manager v1, etc.
```

When a module is modified, its version increments. This allows isolated performance comparison: did trend_gradient v2 improve win rate vs v1, holding all else constant?

---

## 19. State Management

### 19.1 Position State Object

Each open position is represented by a state object:

```python
PositionState = {
    "id": str,                    # Unique identifier
    "underlying": str,            # "ES", "GC", "CL", "ZB", "6E"
    "tier": int,                  # 1 (IC) or 2 (strangle)
    "legs": [                     # List of legs
        {
            "type": str,          # "short_call", "long_call", "short_put", "long_put"
            "strike": float,
            "expiry": datetime,
            "quantity": int,
            "entry_premium": float,
            "current_delta": float,
        }
    ],
    "entry_credit": float,
    "entry_date": datetime,
    "entry_trend_score": float,
    "entry_regime": str,
    "entry_iv_rank": float,
    "call_delta_target": float,
    "put_delta_target": float,
    "max_loss": float,            # Defined for IC, estimated for strangles
    "roll_count": int,
    "days_held": int,
    "remaining_dte": int,
    "unrealised_pnl": float,
    "status": str,                # "active", "rolling", "closing"
}
```

### 19.2 Strategy State Object

```python
StrategyState = {
    "risk_state": str,            # "NORMAL", "DAY_HALT", "WEEK_HALT", "MONTH_HALT", "CORR_ALERT"
    "daily_pnl": float,
    "weekly_pnl": float,
    "monthly_pnl": float,
    "margin_used": float,
    "margin_buffer_ratio": float,
    "per_asset_regime": {         # Per underlying
        "ES": {"regime": str, "confirmation_days": int},
        "GC": {"regime": str, "confirmation_days": int, "handoff_active": bool},
        # ... etc
    },
    "total_open_positions": int,
    "positions_per_underlying": dict,
    "correlation_alert_active": bool,
    "last_state_write": datetime,
}
```

---

## 20. Notifications & Heartbeat

### 20.1 Alert Types

| Type | Trigger | Message Content |
|---|---|---|
| TRADE_ENTRY | New position opened | Underlying, tier, strikes, credit, DTE, trend score, regime |
| TRADE_EXIT | Position closed | Underlying, P&L, exit reason, days held |
| TRADE_ROLL | Leg rolled | Underlying, old strike → new strike, roll credit/debit, roll number |
| RISK_ALERT | Risk state changes | New risk state, trigger condition, current drawdown |
| MARGIN_WARNING | Margin buffer ratio < 2.0 | Current margin, buffer ratio, action being taken |
| REGIME_CHANGE | Underlying regime transitions | Underlying, old regime → new regime |
| CORRELATION_ALERT | ≥ 3 underlyings in simultaneous loss | Affected underlyings, loss amounts |
| BROKER_FAILURE | Connection lost or login issue | Timestamp, error details, recovery status |
| CRITICAL | Any condition requiring human attention | Context-dependent |

### 20.2 Heartbeat

A heartbeat message is sent every 2 hours during trading hours confirming the algorithm is operational.

**Heartbeat content:**
- Algorithm status (running/halted)
- Risk state
- Number of open positions (by underlying)
- Aggregate unrealised P&L
- Margin utilisation
- Current regime per underlying
- Any active alerts

### 20.3 Daily Summary

At 17:00 ET daily:
- All trades executed today
- Daily P&L
- MTD P&L
- Open positions summary
- Regime status per underlying
- Margin status

### 20.4 Implementation Rule

Notifications are wrapped in try/except blocks. A Telegram failure must never crash the algorithm.

---

## 21. Configurable Parameters — Master Table

### 21.1 Global Parameters

| Parameter | Default | Range | Description |
|---|---|---|---|
| risk_pct_per_trade | 2.5% | 1.5–3.5% | Max loss per IC trade as % of equity |
| max_notional_pct | 15% | 10–20% | Max notional per strangle trade |
| aggregate_max_loss_pct | 15% | 10–20% | Total max loss across all open positions |
| max_total_positions | 12 | 8–15 | Max open positions across all underlyings |
| margin_cap | 45% | 30–55% | Max margin utilisation |
| stagger_min_days | 15 | 10–20 | Min age of existing position before new entry |
| daily_loss_halt_pct | 3% | 2–5% | Daily P&L trigger for day halt |
| weekly_loss_halt_pct | 5% | 3–8% | Weekly P&L trigger for week halt |
| monthly_dd_halt_pct | 8% | 5–12% | MTD drawdown trigger for month halt |
| vix_tier2_min | 18 | 14–22 | Min VIX for Tier 2 eligibility |
| vix_tier2_max | 30 | 25–40 | Max VIX for Tier 2 eligibility |
| vix_crisis | 35 | 30–45 | VIX crisis threshold |
| trend_scaling_factor | 0.5 | 0.3–0.8 | Trend score sensitivity |
| trend_score_suppress | 0.9 | 0.8–1.0 | Trend score above which entry is suppressed |
| max_rolls_per_position | 2 | 1–3 | Max roll attempts before closing |
| min_days_between_rolls | 5 | 3–7 | Minimum gap between rolls |
| management_times | [10:00, 15:00] | — | ET times for position scan |
| heartbeat_interval_hours | 2 | 1–4 | Hours between heartbeat messages |

### 21.2 Per-Asset Parameters

See Section 5.1 for the complete per-asset configuration. Key optimisation targets:

| Parameter | Optimisation Priority | Rationale |
|---|---|---|
| default_short_delta | HIGH | Directly affects win rate and premium. Small changes = large P&L impact. |
| profit_target_pct | HIGH | The trade-off between win rate and average profit per winner. |
| roll_trigger_delta | HIGH | Earlier rolls = more commissions but potentially fewer max-loss trades. |
| min_iv_rank | MEDIUM | Entry selectivity. Higher = fewer but better-compensated trades. |
| trend_scaling_factor | MEDIUM | Skew sensitivity. Requires careful validation against history. |
| loss_limit_strangle_x | MEDIUM | Tighter = smaller losers but more losers. Wider = fewer losers but larger. |
| wing_width_points | LOW | Affects max loss and margin. Relatively stable across market conditions. |
| time_stop_dte | LOW | 21 DTE is well-established. Marginal returns from optimising. |

---

## 22. Backtesting Plan

### 22.1 Data Requirements

| Data | Source | Resolution | Period |
|---|---|---|---|
| Futures prices (/ES, /GC, /CL, /ZB, /6E) | QC CME data | Daily + Hourly | 5+ years (2019–2024 minimum) |
| Futures options chains | QC options data | Daily | 5+ years |
| VIX | QC/CBOE | Daily | 5+ years |
| FOMC/ECB/NFP calendar | Hardcoded or external | — | Full backtest period |

### 22.2 Backtest Phases

| Phase | Focus | Success Criteria |
|---|---|---|
| 1. Single underlying, IC only | Validate core entry/exit logic on /ES | Win rate > 78%, no code errors |
| 2. All underlyings, IC only | Validate per-asset parameters | Aggregate win rate > 78%, uncorrelated returns |
| 3. Add Tier 2 (strangles) | Validate tier selection and strangle management | Marginal return improvement without outsized DD |
| 4. Add trend gradient | Validate skew logic | Win rate improvement of 1–3% vs Phase 2 |
| 5. Add regime detection + handoffs | Validate regime gating and /GC handoff | /GC positions avoid breakout periods |
| 6. Stress test (2020 crash, 2022 rate hikes) | Validate risk management under crisis | Max DD < 20%, margin expansion handled |
| 7. Full system with all modules | Integration test | All targets met, all modules functioning |

### 22.3 Walk-Forward Validation

| Parameter | Value |
|---|---|
| In-sample | 2 years |
| Out-of-sample | 6 months |
| Walk-forward windows | Rolling, overlap by 6 months |
| Parameter re-optimisation | Per window, per asset |

### 22.4 Metrics to Track Per Backtest

| Metric | Target |
|---|---|
| Win rate (by underlying, by tier, by regime) | > 80% aggregate |
| Average win / average loss ratio | > 0.3 (premium selling has inherently low payoff ratio) |
| Sharpe ratio | > 1.0 |
| Sortino ratio | > 1.2 |
| Max drawdown | < 18% |
| Profit factor | > 1.5 |
| Average days held | 15–25 |
| Roll frequency | < 15% of trades |
| Roll success rate (rolls that convert to winners) | > 60% |
| Margin utilisation peak | < 50% |
| Trend-adjusted vs symmetric win rate delta | > 1% |

### 22.5 Backtest Integrity Rules

| Rule | Implementation |
|---|---|
| No lookahead bias | Options chain data must use available-at-time greeks, not end-of-day |
| Realistic fills | Apply 10% slippage to option mid-price (wider for /CL options) |
| Commission modelling | $1.50/contract per leg (IBKR futures options rate) |
| Margin modelling | Conservative SPAN estimate, not backtest-available margin |
| Survivorship bias | N/A for futures (continuous contracts) |
| Warmup period | 60 days minimum (for 52-week IV rank calculation, need 252 days of IV history; use pre-loaded data) |

---

## 23. Deployment Plan

### 23.1 Phased Rollout

| Phase | Duration | Description |
|---|---|---|
| 1. Paper trade | 4 weeks | Full system on QC paper trading. Validate execution, fills, margin estimation. |
| 2. Single underlying live | 4 weeks | /ES only at 50% target sizing. Validate live fills and management. |
| 3. Add second underlying | 2 weeks | Add /ZB (negatively correlated with /ES). Validate multi-asset management. |
| 4. Full deployment | 2 weeks | Add /GC, /CL, /6E. Scale to 75% target sizing. |
| 5. Full sizing | Ongoing | Scale to 100% after 1 month of stable live performance. |

### 23.2 QC Deployment Configuration

| Setting | Value |
|---|---|
| Brokerage | Interactive Brokers |
| Data provider | QuantConnect (for options chain data) |
| Account type | Margin (futures-enabled) |
| Resolution | Daily for signals, Hourly for management scans |
| Live node | Dedicated (not shared) |

### 23.3 Build Sequence Within Stargaze Portfolio

Optimus is Phase 2 in the Stargaze build sequence:

1. **Megatron** (gold breakouts) — foundation, shared library built
2. **Optimus** (futures options premium) — first diversifier, uses shared library
3. **Bumblebee** (equity momentum) — second alpha generator
4. **Sideways** (forex carry momentum) — final diversification layer

---

## 24. Performance Targets

### 24.1 Strategy-Level Targets

| Metric | Conservative | Base Case | Optimistic |
|---|---|---|---|
| CAGR (own capital) | 12% | 19% | 25% |
| Sharpe ratio | 0.9 | 1.2 | 1.5 |
| Sortino ratio | 1.2 | 1.6 | 2.0 |
| Max drawdown | -18% | -14% | -10% |
| Win rate | 80% | 82% | 85% |
| Profit factor | 1.5 | 2.0 | 2.8 |
| Monthly income consistency | 7/12 positive months | 9/12 | 11/12 |
| Avg trade duration | 18–25 days | 18–25 days | 15–22 days |

### 24.2 Portfolio Contribution (at 25% Allocation)

| Metric | Value |
|---|---|
| Portfolio CAGR contribution | 3.0–6.25% |
| Correlation with Megatron | -0.15 (target) |
| Correlation with Bumblebee | -0.10 (target) |
| Correlation with Sideways | Near zero (0.05) |
| Portfolio Sharpe improvement | Significant positive impact |

### 24.3 Return Math — Base Case

Configuration: 5 underlyings, 9 concurrent cycles, 80% IC / 20% strangles, trend-adjusted skew.

| Component | Trades/Year | Win Rate | Avg Win | Avg Loss | Net |
|---|---|---|---|---|---|
| Iron condors | 108 | 82% | $400 | -$1,100 | +$15,750 |
| Strangles | 27 | 83% | $675 | -$2,700 | +$5,650 |
| Commissions | 135 | — | — | — | -$2,430 |
| **Total** | | | | | **+$18,970** |

On $100K allocated capital: ~19% CAGR.

---

## 25. Known Risks & Mitigations

| Risk | Severity | Mitigation |
|---|---|---|
| Tail risk — sudden large moves (crash, supply shock) | HIGH | Defined risk (IC) as default. Catastrophic stop. Margin reserve. CRISIS regime halts. |
| Correlation spike — all underlyings move together in crisis | HIGH | Correlation alert at 3+ underlyings in loss. Multi-level loss halts. Margin buffer. |
| Margin expansion — SPAN requirements double overnight | HIGH | 55% margin reserve. Margin expansion protocol closes strangles first. |
| /CL negative prices (April 2020 precedent) | HIGH | Catastrophic stop at 3× ATR. Loss limit on every position. /CL gets tighter parameters. |
| Win rate below 80% | MEDIUM | Trend-adjusted skew. Regime filtering. Per-asset parameter tuning. Phase 2 walk-forward validation. |
| Futures options data quality on QC | MEDIUM | Liquidity checks before entry. Skip illiquid chains. Compare to IBKR data in live. |
| QuantConnect execution complexity (combos, multi-leg) | MEDIUM | Leg-by-leg execution as fallback if combo orders fail. Slippage budget in sizing. |
| /GC breakout risk | MEDIUM | Independent gold trend suppress filter. Max concurrent = 1. No Tier 2 on gold. |
| Slippage on options spreads | LOW-MEDIUM | Liquidity checks. 10% slippage model. Stick to most liquid strikes. |
| Broker disconnection during roll | LOW | Failsafe module. State persistence. Reconciliation on reconnect. |

---

## 26. Engineering Notes & QC-Specific Guidance

### 26.1 Futures Options on QuantConnect

| Topic | Guidance |
|---|---|
| Data subscription | Use `self.add_future_option(future_symbol)` for options chain access |
| Bar type | Futures = TradeBar, use TradeBarConsolidator |
| Options chain filtering | Filter by DTE range and delta range before strike selection |
| Combo orders | QC supports combo legs but execution may be unreliable. Implement leg-by-leg fallback. |
| Contract rollover | Futures options follow the underlying future's expiry. Handle front-month to back-month transitions. |
| Greeks calculation | Use QC's built-in Greeks if available; otherwise implement Black-76 model for futures options pricing |

### 26.2 Key Implementation Hazards

| Hazard | Prevention |
|---|---|
| 64KB file limit | Modular architecture splits code across files |
| Log truncation | Condensed logging. Write critical summaries early. Use debug flag for verbose mode. |
| Options chain gaps | Always check chain is populated before accessing. Skip underlying if chain is empty. |
| IBKR margin queries | May timeout or return stale data. Use conservative internal estimate as primary, IBKR query as validation. |
| Timezone handling | All internal times in ET. Convert for display in Telegram (UTC or UK time for Brad). |
| Warmup period | 252+ days for IV rank (52-week lookback). Pre-load historical IV data or use shorter initial lookback with flag. |

### 26.3 Testing Priority

1. **Core loop first**: Entry gates → strike selection → IC construction → profit target exit. Validate this produces correct P&L on /ES with known historical data.
2. **Add management**: Loss limits, time stop, roll logic. Validate edge cases.
3. **Add trend gradient**: Compare win rate with and without skew across all underlyings.
4. **Add regime and handoff**: Validate /GC positions are suppressed during breakout-like conditions.
5. **Add risk manager**: Inject simulated drawdown scenarios to verify halts trigger correctly.
6. **Add failsafe**: Simulate broker disconnection mid-roll to verify state recovery.

---

## Appendix A: Glossary

| Term | Definition |
|---|---|
| ATR | Average True Range — volatility measure |
| DTE | Days to Expiration |
| IC | Iron Condor — defined-risk options structure |
| IV Rank | Implied Volatility Rank — current IV vs 52-week range |
| SPAN | Standard Portfolio Analysis of Risk — futures margin methodology |
| VRP | Volatility Risk Premium — difference between implied and realised vol |
| Theta | Time decay — daily erosion of option value |
| Delta | Sensitivity of option price to $1 move in underlying |
| Gamma | Rate of change of delta — accelerates near expiration |
| Wing | The long option leg in a spread that defines max loss |

## Appendix B: Related Documents

| Document | Relevance |
|---|---|
| Stargaze Portfolio Strategy | Master portfolio design, allocation, correlation targets |
| Trading Algorithm Design Patterns v2 | QC-specific architecture patterns, deployment configuration |
| Trading Algorithms Guide v3 | Options strategy theory, modular architecture reference |
| Megatron HLD | Gold breakout architecture — /GC handoff reference |
| Sideways HLD | Forex carry momentum — /6E awareness reference |

---

*Document maintained by Stargaze Capital. Next review: upon completion of Phase 1 backtesting.*
