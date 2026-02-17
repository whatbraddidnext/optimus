# Optimus — High-Level Design Document

**Version:** 1.0
**Date:** February 2026
**Status:** Draft
**Classification:** Internal — Stargaze Capital

---

## 1. Executive Summary

Optimus is a systematic options premium selling algorithm that harvests the volatility risk premium — the persistent gap between implied and realised volatility. It sells defined-risk put credit spreads on SPX (and extensible to other underlyings) when market conditions are favourable, using a mean reversion entry timing model built around Bollinger Bands.

**V1 scope:** Put credit spreads on SPX only. Iron condors, call credit spreads, and additional underlyings are deferred to later versions.

---

## 2. Strategy Philosophy

### Why Sell Options Premium?

Market participants systematically overpay for portfolio insurance. Implied volatility exceeds realised volatility approximately 85% of the time. By selling that insurance through defined-risk credit spreads, Optimus captures the structural premium that decays predictably over time (theta).

### Why SPX First?

- **Cash-settled, European-style** — no early assignment risk, no pin risk at expiration
- **Deep liquidity** — tightest bid/ask spreads of any options market; minimises slippage
- **Section 1256 tax treatment** (US) — 60/40 long-term/short-term capital gains (relevant for future international investors)
- **Larger notional per contract** — fewer contracts needed, reducing commission drag
- **No dividend risk** — cash-settled index, no ex-dividend surprises affecting pricing
- **50-point spread width** — clean, round number; produces meaningful premium while keeping defined risk manageable

### Why Mean Reversion Entry Timing?

Selling premium into an oversold bounce rather than blindly on a calendar schedule:
- Captures the volatility expansion that occurs during selloffs (higher IV = richer premium)
- Enters when the market has already pulled back and is turning (directional tailwind for put credit spreads)
- Avoids selling into the teeth of a developing crash (confirmation via Bollinger Band mean reversion)

---

## 3. Market Diagnosis Pipeline

Before any trade, Optimus runs a multi-layer market assessment. Each layer produces a clear pass/fail with debug logging.

### 3.1 Volatility Assessment

| Check | Condition | Purpose |
|-------|-----------|---------|
| IV Rank | > 50% (52-week percentile) | Only sell when IV is elevated relative to its own history |
| VIX Level | VIX within acceptable range (not crisis) | Avoid selling into a vol explosion |
| VIX Term Structure | Front-month vs second-month ratio | Contango = normal; backwardation = stress. Prefer contango or flat |
| IV/HV Ratio | IV > HV (current) | Confirm the risk premium exists right now |

**Best practice — IV Rank calculation:** Use the 52-week percentile method, not the simple rank. This accounts for the distribution of IV values and is more robust to outlier spikes.

### 3.2 Market Sentiment & Direction

| Check | Condition | Purpose |
|-------|-----------|---------|
| Trend Filter | SPX above 200-day EMA | Only sell puts when long-term trend is intact |
| Breadth | % of S&P 500 stocks above 50-day MA > 40% | Confirms broad market participation, not just mega-cap driven |
| Put/Call Ratio | 5-day smoothed P/C ratio | Extreme readings flag crowded positioning |
| Credit Spreads (HY) | Investment-grade/high-yield spread not widening sharply | Early warning of systemic stress |

**Configurable:** Each filter has an enable/disable toggle and adjustable threshold, stored as parameters per underlying.

### 3.3 Regime Classification

| Regime | Conditions | Action |
|--------|-----------|--------|
| **Bullish Calm** | VIX < 18, SPX > 200 EMA, breadth strong | Full allocation — ideal environment for put credit spreads |
| **Elevated Vol** | VIX 18–25, trend intact | Full allocation — richer premium, still favourable |
| **High Vol** | VIX 25–35, trend intact or recovering | Reduced allocation (50–75%). Wider spreads, more conservative delta |
| **Crisis** | VIX > 35 or term structure in steep backwardation | Halt new entries. Manage existing positions only |
| **Bear Trend** | SPX below 200 EMA, declining breadth | Halt new entries until trend recovers. Do not fight the trend |

---

## 4. Entry System — Mean Reversion with Bollinger Band Confirmation

### 4.1 Core Logic

The entry timing uses a Bollinger Band mean reversion model on the underlying (SPX). The thesis: sell put credit spreads when the market has been oversold, has touched or penetrated the lower Bollinger Band, and is **confirmed to be returning to the mean** — not continuing to fall.

### 4.2 Entry Gates (All Must Pass)

| Gate | Condition | Purpose |
|------|-----------|---------|
| 1. Market Regime | Not in Crisis or Bear Trend regime | Don't sell into a crash |
| 2. IV Rank | IV Rank > 50% | Only sell rich premium |
| 3. VIX Term Structure | Not in steep backwardation (front/second month ratio < 1.05) | Avoid selling during vol explosions |
| 4. Trend | SPX > 200-day EMA | Long-term uptrend intact |
| 5. Oversold | SPX price touched or closed below lower Bollinger Band (20, 2.0) within the last N bars (configurable, default 5) | Market has pulled back |
| 6. Mean Reversion Confirmation | SPX closes back above lower BB AND current close > prior close (consecutive up-closes configurable, default 1) | The bounce is real, not a dead cat |
| 7. Momentum Confirmation | RSI(14) > 30 and rising (current RSI > prior bar RSI) | Oversold but recovering, not in freefall |
| 8. MACD Confirmation (optional) | MACD histogram turning positive or MACD crossing above signal line | Secondary momentum confirmation |
| 9. Capacity | Total open positions < max concurrent (parameter, default 8) | Risk management |
| 10. Minimum Spacing | At least N business days since last entry (parameter, default 3) | Prevents clustering entries in a single selloff |

### 4.3 Confirmation Logic — "Returning to Mean, Not Dropping Further"

This is the critical differentiator. Touching the lower BB is necessary but not sufficient. The algorithm requires:

1. **BB Touch/Breach:** Price touched or closed below the lower BB within the lookback window
2. **Recovery Close:** The most recent close is above the lower BB (price has bounced back inside the bands)
3. **Positive Price Action:** At least 1 consecutive higher close (configurable), confirming upward momentum
4. **RSI Inflection:** RSI is above 30 and rising (not still falling)

If any confirmation fails, the signal is logged as "BB touch detected but confirmation failed" with specific gate failures, and the algorithm waits.

### 4.4 Entry Timing

Once all gates pass, the trade is eligible for execution on the **next trading day's open** (not intraday). This avoids end-of-day volatility distortion and gives clean fills on SPX options at the open.

**Best practice:** Execute between 10:00–11:00 ET to avoid the opening auction noise and capture stable mid-market pricing on spreads.

---

## 5. Trade Construction

### 5.1 Credit Spread Parameters

| Parameter | Value | Notes |
|-----------|-------|-------|
| Structure | Put credit spread (bull put spread) | Sell higher strike put, buy lower strike put |
| Underlying | SPX (V1), extensible to others | Each underlying has its own parameter set |
| Short Strike Delta | -0.16 (target) or nearest available | ~84% probability OTM. Select the strike with delta closest to -0.16 |
| Spread Width | 50 points (SPX) | Defined risk = $5,000 per contract max loss minus premium received |
| Target DTE | 45 days | Select the expiration closest to 45 DTE (but not less than 30 DTE) |
| Acceptable DTE Range | 30–60 DTE | If no expiration at exactly 45, select nearest within this window |

### 5.2 Strike Selection Logic

1. Retrieve the options chain for the target expiration
2. Filter for put options only
3. Find the strike where delta is closest to -0.16
4. That strike becomes the **short put**
5. The **long put** is 50 points below the short put
6. Validate that both strikes exist and have acceptable bid/ask spreads (mid-market spread < 20% of premium)
7. If no acceptable strikes found, log "No suitable strikes for entry" and skip

### 5.3 Multi-Underlying Support (Future Versions)

The system stores parameters per underlying in a configuration dictionary:

```python
UNDERLYING_CONFIG = {
    "SPX": {
        "spread_width": 50,
        "target_delta": -0.16,
        "target_dte": 45,
        "min_dte": 30,
        "max_dte": 60,
        "min_iv_rank": 50,
        "max_concurrent": 3,
        "bb_period": 20,
        "bb_std": 2.0,
    },
    # Future: add QQQ, IWM, RUT, etc. with their own params
}
```

---

## 6. Position Sizing

### 6.1 Sizing by Maximum Loss

**Never size by premium received.** Always size by the maximum possible loss.

```
Max Loss per Contract = (Spread Width - Premium Received) × Multiplier
Position Size = floor(Max Risk per Trade / Max Loss per Contract)
```

Where:
- **Max Risk per Trade** = 2–3% of total portfolio equity (parameter, default 2%)
- **Multiplier** = 100 for SPX options

Example: $500,000 portfolio, 2% risk = $10,000 max loss per trade. SPX 50-point spread, $4.00 credit received. Max loss = ($50 - $4) × 100 = $4,600 per contract. Position size = floor($10,000 / $4,600) = 2 contracts.

### 6.2 Conviction-Based Scaling

The conviction scorer adjusts position size between 0.5x and 1.5x of the base size:

| Factor | High Conviction | Low Conviction |
|--------|----------------|----------------|
| IV Rank | > 70% | 50–55% |
| VIX Term Structure | Strong contango | Flat |
| Trend Strength | SPX well above 200 EMA | Barely above |
| BB Depth | Deep touch (> 2.5 std) | Shallow touch |
| Recent Win Rate | Last 10 trades > 80% win | Last 10 trades < 60% win |

### 6.3 Portfolio-Level Constraints

| Constraint | Limit |
|-----------|-------|
| Max loss per trade | 2–3% of portfolio equity |
| Max concurrent positions per underlying | 3 |
| Max total concurrent positions | 8 |
| Total exposure (sum of max losses) | Never exceed 15% of portfolio equity |
| Drawdown scaling | At 10% DD → reduce to 1.5% risk. At 20% DD → reduce to 1% |

---

## 7. Exit System

Exits are evaluated daily. The first triggered condition closes the trade.

### 7.1 Exit Rules (Priority Order)

| Exit | Condition | Action |
|------|-----------|--------|
| **Profit Target** | Spread can be closed for 50% of max profit (i.e., bought back at 50% of credit received) | Close immediately |
| **Stop Loss** | Spread value has increased to 200% of credit received (loss = 1x premium) | Close immediately |
| **Time Stop** | Position reaches 21 DTE | Close regardless of P/L (avoid gamma acceleration) |
| **Circuit Breaker** | 3 consecutive max losses across all positions | Halt all new entries for configurable period (default 5 business days) |
| **Regime Shift** | Market enters Crisis or Bear Trend regime | Close all positions within 1 business day |

### 7.2 Exit Priority

If multiple exit conditions trigger simultaneously (e.g., 21 DTE and profit target), the most conservative action wins. In practice, profit target > stop loss > time stop in priority because profit target and stop loss would trigger before 21 DTE in most cases.

### 7.3 Never Hold to Expiration

This is a non-negotiable rule. Gamma risk accelerates exponentially as DTE approaches zero. The 21 DTE time stop ensures all positions are closed well before expiration.

**Best practice:** Consider a "soft warning" at 28 DTE that tightens the profit target to 40% of max profit. This captures slightly less profit but increases the probability of exiting before the 21 DTE hard stop.

---

## 8. Minimum Trade Spacing

### 8.1 Rationale

Multiple entries during the same selloff creates correlated risk. If the market continues lower, all positions lose simultaneously. The minimum spacing parameter enforces diversification across time.

### 8.2 Implementation

| Parameter | Default | Notes |
|-----------|---------|-------|
| `min_days_between_entries` | 3 business days | Configurable per underlying |
| Measurement | Calendar of business days since last entry on same underlying | Excludes weekends and market holidays |

### 8.3 Multiple Open Positions

With 45 DTE entries every 3+ business days, the algorithm will naturally hold multiple overlapping positions. At steady state:
- ~6–10 open positions at any time (subject to capacity and regime constraints)
- Staggered expirations provide smoother P/L
- Each position is independently managed (its own profit target, stop loss, time stop)

**Best practice:** Track aggregate delta and aggregate theta across all positions. If aggregate short delta exceeds a threshold (configurable, default -0.50 portfolio delta), restrict new entries even if individual gate checks pass.

---

## 9. Reporting & Diagnostics

### 9.1 Entry Condition Logging

Every time the algorithm evaluates an entry (daily when market is open), it must produce a structured log entry:

```
[ENTRY EVAL] 2026-02-17 | SPX
  Regime: Bullish Calm (PASS)
  IV Rank: 62.3% (PASS, threshold: 50%)
  VIX Term Structure: 0.97 contango ratio (PASS, threshold: <1.05)
  Trend: SPX 5,842 > 200 EMA 5,650 (PASS)
  BB Touch: Lower BB 5,780, low 5,765 on 2026-02-14 (PASS, within 5-bar lookback)
  Mean Reversion: Close 5,810 > Lower BB 5,780 (PASS)
  Price Action: +0.4% today, 1 consecutive up-close (PASS, min: 1)
  RSI: 38.2, prior 35.1 (PASS, >30 and rising)
  Capacity: 4/8 open positions (PASS)
  Spacing: 5 business days since last entry (PASS, min: 3)
  >>> SIGNAL: ENTRY TRIGGERED
```

When conditions are unfavourable:

```
[ENTRY EVAL] 2026-02-18 | SPX
  Regime: Elevated Vol (PASS)
  IV Rank: 44.2% (FAIL, threshold: 50%)
  >>> NO TRADE: IV Rank below threshold (44.2% < 50%)
  [Remaining gates not evaluated — first failure stops chain]
```

### 9.2 Trade Parameter Logging

On every fill:

```
[TRADE OPENED] 2026-02-17 | SPX Put Credit Spread
  Short Put: SPX 5700P @ $12.40 (delta: -0.157)
  Long Put: SPX 5650P @ $9.80
  Net Credit: $2.60 ($260 per contract)
  Contracts: 2
  Spread Width: 50 points ($5,000 per contract)
  Max Loss: $4,740 per contract ($9,480 total)
  Max Profit: $260 per contract ($520 total)
  Risk/Reward: 18.2:1 max loss to max profit (mitigated by high win rate)
  DTE: 44
  Expiration: 2026-04-02
  Profit Target: Close at $1.30 (50% of $2.60 credit)
  Stop Loss: Close at $7.80 (200% of $2.60 credit)
  Time Stop: 2026-03-12 (21 DTE)
  Portfolio Risk: $9,480 / $500,000 = 1.9% of equity
  Total Exposure: 6.2% of equity (4 positions open)
```

### 9.3 Exit Logging

```
[TRADE CLOSED] 2026-03-03 | SPX Put Credit Spread
  Reason: PROFIT TARGET (50%)
  Entry Credit: $2.60
  Exit Debit: $1.28
  P/L: +$1.32 per contract (+$264 total, 2 contracts)
  Return on Risk: +2.8% ($264 / $9,480)
  Days Held: 14
  DTE at Close: 30
  Win/Loss: WIN
  Running Stats: 7W / 2L (77.8% win rate), Profit Factor: 2.34
```

### 9.4 Unfavourable Market Logging

When the algorithm determines conditions are not suitable for any trade:

```
[DAILY SUMMARY] 2026-02-17 | NO TRADES ELIGIBLE
  SPX: BLOCKED — Bear Trend regime (SPX below 200 EMA)
  Open Positions: 3 (all within risk limits)
  Aggregate Delta: -0.32
  Aggregate Theta: +$145/day
  Portfolio Heat: 8.4% of equity at risk
  Days Since Last Entry: 12
  Note: Market in sustained downtrend. All entry signals suppressed.
```

### 9.5 Daily Dashboard Summary

```
[DAILY DASHBOARD] 2026-02-17
  Regime: Bullish Calm | VIX: 16.2 | IV Rank: 58%
  Open Positions: 5 | Aggregate P/L: +$1,240
  Aggregate Delta: -0.28 | Aggregate Theta: +$185/day
  Portfolio Heat: 9.8% of equity
  Nearest Expiry: 2026-03-07 (18 DTE) — ALERT: approaching time stop
  Circuit Breaker: OFF (last 3 trades: W, W, L)
  Trades Today: 1 opened (SPX 5700/5650 PCS)
```

---

## 10. Parameters & Configuration

All tuneable parameters are centralised for easy backtesting and optimisation.

### 10.1 Core Parameters

| Parameter | Default | Range | Description |
|-----------|---------|-------|-------------|
| `target_delta` | -0.16 | -0.10 to -0.25 | Short strike delta target |
| `spread_width` | 50 | 25–100 | Points between short and long strikes (SPX) |
| `target_dte` | 45 | 30–60 | Target days to expiration at entry |
| `min_dte_entry` | 30 | 21–45 | Minimum acceptable DTE for new entries |
| `max_dte_entry` | 60 | 45–90 | Maximum acceptable DTE for new entries |
| `profit_target_pct` | 50 | 30–75 | Close at this % of max profit |
| `stop_loss_multiplier` | 2.0 | 1.5–3.0 | Close when spread value = multiplier × credit received |
| `time_stop_dte` | 21 | 14–28 | Close all positions at this DTE |
| `min_iv_rank` | 50 | 30–70 | Minimum IV Rank for entry |
| `min_days_between_entries` | 3 | 1–10 | Business days between entries on same underlying |
| `max_concurrent_per_underlying` | 3 | 1–5 | Max open positions per underlying |
| `max_concurrent_total` | 8 | 3–15 | Max total open positions |
| `max_portfolio_heat` | 15 | 5–25 | Max sum of max losses as % of equity |
| `risk_per_trade_pct` | 2.0 | 1.0–3.0 | Max loss per trade as % of equity |
| `circuit_breaker_count` | 3 | 2–5 | Consecutive max losses before halt |
| `circuit_breaker_cooldown_days` | 5 | 3–10 | Business days to pause after circuit breaker |

### 10.2 Bollinger Band & Mean Reversion Parameters

| Parameter | Default | Range | Description |
|-----------|---------|-------|-------------|
| `bb_period` | 20 | 10–30 | Bollinger Band lookback period |
| `bb_std_dev` | 2.0 | 1.5–2.5 | Bollinger Band standard deviation multiplier |
| `bb_touch_lookback` | 5 | 3–10 | Bars to look back for lower BB touch |
| `min_consecutive_up_closes` | 1 | 1–3 | Required consecutive higher closes for confirmation |
| `rsi_period` | 14 | 7–21 | RSI calculation period |
| `rsi_oversold_threshold` | 30 | 20–40 | RSI must be above this and rising |

### 10.3 Market Filter Parameters

| Parameter | Default | Range | Description |
|-----------|---------|-------|-------------|
| `trend_ema_period` | 200 | 100–250 | EMA period for trend filter |
| `vix_crisis_threshold` | 35 | 30–45 | VIX level that triggers crisis regime |
| `vix_high_vol_threshold` | 25 | 20–30 | VIX level that triggers high vol regime |
| `vix_term_structure_threshold` | 1.05 | 1.00–1.10 | Front/second month ratio above which = backwardation warning |
| `max_aggregate_delta` | -0.50 | -0.30 to -1.00 | Portfolio-level short delta limit |

---

## 11. Performance Enhancement Suggestions

### 11.1 Dynamic Profit Targets

Rather than a fixed 50% profit target, adjust based on DTE remaining:
- **DTE > 35:** Target 50% profit (let theta work)
- **DTE 28–35:** Target 40% profit (start tightening)
- **DTE 21–28:** Target 30% profit (approaching time stop, take what you can)

This captures more winners that would otherwise hit the 21 DTE time stop at a loss.

### 11.2 VIX-Adjusted Delta Selection

When VIX is elevated, the same delta represents a wider strike distance. Consider adjusting:
- **VIX < 18:** Target -0.16 delta (standard)
- **VIX 18–25:** Target -0.14 delta (slightly more OTM for added safety)
- **VIX 25–35:** Target -0.12 delta (wider buffer against continued selloff)

### 11.3 Theta Decay Acceleration Capture

Theta decay is not linear — it accelerates as expiration approaches. The 45 DTE entry with 21 DTE exit captures the steepest part of the theta curve for short-dated options while exiting before gamma risk dominates.

**Enhancement:** Track the daily theta capture rate. If a position is decaying slower than expected (because IV is expanding), this is an early warning to tighten the stop.

### 11.4 Roll Mechanics (Future Enhancement)

Rather than closing losing positions at the stop loss, consider rolling:
- Roll to a later expiration (add 30 days)
- Roll the short strike further OTM
- Only if the roll produces a net credit

This is a V2 enhancement — rolling adds complexity and can mask losses if not disciplined.

### 11.5 Skew Analysis

Put skew (the steepness of the IV smile) varies. When skew is steep, OTM puts are relatively expensive — ideal for selling. When skew is flat, the premium for OTM puts is thinner.

**Enhancement:** Add a skew filter: only enter when the 25-delta put IV / ATM IV ratio exceeds its 30-day average.

### 11.6 Intraday vs End-of-Day Execution

SPX options are most liquid during the first 2 hours and last hour of trading. The mid-market spread is tightest during these windows.

**Recommendation:** Evaluate entry signals at the previous day's close. Execute between 10:00–11:00 ET the following morning. This gives stable pricing and avoids the opening auction.

### 11.7 Earnings Awareness

Even though Optimus trades index options (not single stocks), major earnings clusters can cause index-level volatility expansion. During peak earnings weeks (early-mid January, mid-April, mid-July, mid-October), IV may be temporarily elevated due to event risk rather than structural overpricing.

**Enhancement:** Flag when > 20% of S&P 500 market cap reports earnings within 5 days. Do not block trades, but note it in diagnostics.

### 11.8 Correlation with Portfolio

Optimus put credit spreads are structurally short volatility and long equity markets. During crashes, they lose. Megatron (gold breakout) profits during risk-off events. Monitor the rolling 30-day correlation between Optimus P/L and Megatron P/L. If correlation rises above -0.05 (becoming less negatively correlated), it may indicate regime shift.

### 11.9 Greeks Monitoring

Track portfolio Greeks in real-time:
- **Delta:** Net directional exposure. Should stay moderately negative (short puts = short delta).
- **Gamma:** Acceleration risk. Increases as DTE decreases. The 21 DTE exit controls this.
- **Theta:** Daily income. This should be consistently positive. If aggregate theta turns negative, something is wrong.
- **Vega:** Sensitivity to IV changes. All short options are short vega. A VIX spike hurts all positions simultaneously.

### 11.10 Warm-Up Period

The algorithm requires sufficient historical data before trading:
- 200 bars for the trend EMA
- 52 weeks of IV data for IV Rank calculation
- 20 bars for Bollinger Bands
- 14 bars for RSI

**No trades during warmup.** Log "WARMUP: indicators not ready, X bars remaining" daily until all indicators are seeded.

---

## 12. Risk Controls Summary

### Non-Negotiable Rules

1. **Defined risk only** — never sell naked options. Every short option has a corresponding long option.
2. **Never hold to expiration** — 21 DTE time stop is absolute.
3. **Size by max loss** — never by premium received.
4. **Risk manager has veto** — no entry can bypass risk checks.
5. **Circuit breaker** — 3 consecutive max losses halts all new entries.
6. **Portfolio heat limit** — total exposure never exceeds 15% of equity.
7. **Regime override** — Crisis or Bear Trend regime halts all entries and may force exits.

### Defence in Depth

| Layer | Protection |
|-------|-----------|
| Individual trade | Stop loss at 200% of premium |
| Position level | Max 3 per underlying |
| Portfolio level | Max 8 total, 15% equity heat limit |
| Strategy level | Circuit breaker after consecutive losses |
| Regime level | Crisis detection halts all activity |
| Time level | 21 DTE hard exit on all positions |

---

## 13. File Architecture

```
/Optimus/
├── main.py                 # Core algorithm, event handlers, scheduling (<64KB)
├── config.py               # All parameters from Section 10, per-underlying configs
├── signal_engine.py        # Entry gate evaluation, BB mean reversion logic
├── market_analyzer.py      # Volatility assessment, sentiment, regime (Section 3)
├── spread_builder.py       # Options chain filtering, strike selection, spread construction
├── risk_manager.py         # Portfolio risk, circuit breakers, drawdown scaling
├── indicators.py           # IV rank, BB, RSI, EMA, Greeks wrappers
├── regime_detector.py      # VIX regime classification (Section 3.3)
├── position_sizer.py       # Max-loss sizing with conviction scaling
├── execution_manager.py    # Spread order management, fill tracking
├── trade_tracker.py        # Trade logging, performance metrics, win/loss tracking
├── session_manager.py      # Market hours, expiration calendar, business day logic
├── notifications.py        # Telegram/email alerts
├── conviction_scorer.py    # Multi-factor conviction for sizing (Section 6.2)
├── diagnostics.py          # Daily dashboard, analytics, attribution
└── /shared/                # Shared library across all Stargaze algos
    ├── utils.py
    ├── constants.py
    └── sizing.py
```

### Key Design Decisions

- **`config.py` is new** — centralises all parameters for clean backtesting sweeps
- **`market_analyzer.py` is new** — separates market diagnosis (Section 3) from signal generation
- **`spread_builder.py` is new** — isolates options chain logic from entry signal logic
- All modules import parameters from `config.py`, never hardcoded values
- `risk_manager.py` has veto power — it wraps every trade decision

---

## 14. Data Flow

```
Market Data (SPX price, VIX, options chain)
    │
    ▼
[indicators.py] ── compute BB, RSI, EMA, IV Rank, Greeks
    │
    ▼
[market_analyzer.py] ── volatility assessment, sentiment, regime
    │
    ▼
[regime_detector.py] ── classify current regime
    │
    ▼
[signal_engine.py] ── evaluate all entry gates, produce ENTRY/NO_TRADE signal
    │
    ├── NO_TRADE → [diagnostics.py] log reason, update daily summary
    │
    └── ENTRY →
        │
        ▼
    [spread_builder.py] ── find optimal strikes, construct spread
        │
        ▼
    [conviction_scorer.py] ── score conviction (0.5x–1.5x)
        │
        ▼
    [position_sizer.py] ── calculate contracts from max loss, conviction, drawdown
        │
        ▼
    [risk_manager.py] ── APPROVE or VETO (portfolio heat, capacity, regime)
        │
        ├── VETO → [diagnostics.py] log reason
        │
        └── APPROVE →
            │
            ▼
        [execution_manager.py] ── submit spread order, track fill
            │
            ▼
        [trade_tracker.py] ── log trade details, update stats
            │
            ▼
        [notifications.py] ── send alert
```

### Daily Exit Evaluation

```
For each open position:
    │
    ▼
[trade_tracker.py] ── current P/L, DTE remaining
    │
    ▼
[risk_manager.py] ── check stop loss, profit target, time stop, regime shift
    │
    ├── HOLD → log status, continue
    │
    └── EXIT →
        │
        ▼
    [execution_manager.py] ── close spread
        │
        ▼
    [trade_tracker.py] ── record exit, update running stats
        │
        ▼
    [diagnostics.py] ── update daily dashboard
        │
        ▼
    [notifications.py] ── send alert
```

---

## 15. Version Roadmap

| Version | Scope | Notes |
|---------|-------|-------|
| **v1.0** | SPX put credit spreads with BB mean reversion entry | This document |
| v1.1 | Backtesting and parameter optimisation | Tune BB, delta, DTE, profit targets |
| v1.2 | Paper trading validation | 2–4 weeks live paper |
| **v2.0** | Add iron condors (sell call credit spread above + put credit spread below) | Neutral bias when trend is flat |
| v2.1 | Add call credit spread standalone (bearish signal) | When market is overbought at upper BB |
| **v3.0** | Multi-underlying (RUT, NDX, or futures options ES/NQ) | Each with own parameter set |
| v3.1 | VIX mean reversion overlay (Layer 2 from portfolio strategy) | Scale into vol spikes |
| **v4.0** | Roll mechanics for losing positions | Only if net credit achievable |
| v4.1 | Earnings premium selling (Layer 3) | Single-stock iron condors |

---

## 16. Success Criteria

| Metric | Target |
|--------|--------|
| CAGR | 40%+ |
| Sharpe Ratio | 0.8–1.2 |
| Win Rate | 75–85% |
| Profit Factor | 1.8–2.5 |
| Max Drawdown | 15–25% |
| Monthly Income | 1–1.5% of allocated capital |
| Avg Trade Duration | 15–30 days |

### Failure Conditions (halt and review)

- Win rate drops below 60% over 20+ trades
- 3 consecutive max losses (circuit breaker fires)
- Max drawdown exceeds 25%
- Profit factor below 1.2 over rolling 30-trade window
- Consistent negative theta capture (positions losing more than theta predicts)
