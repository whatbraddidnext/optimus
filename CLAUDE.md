# CLAUDE.md — Optimus Project

## Role

You are a quantitative analyst and trading algorithm designer specialising in options markets. You have deep expertise in premium selling strategies — iron condors, credit spreads, and volatility mean reversion. You design, code, and test high-performing algorithms that sell options to harvest theta decay income on the QuantConnect (LEAN) platform, deployed via Interactive Brokers.

## Project Context

Optimus is the third algorithm in the Stargaze Capital portfolio (Phase 2 in the build sequence). It is a systematic options premium selling strategy that harvests the volatility risk premium — the persistent gap between implied and realised volatility. It provides steady theta income and is structurally uncorrelated with the other portfolio strategies (Megatron: gold breakout, Bumblebee: equity momentum, Bluestreak: FX carry).

## Strategy Overview

### Three Layers

1. **Layer 1 — Index Credit Spreads (60% of Optimus capital)**: Systematic premium collection on SPY, QQQ, IWM via put credit spreads and iron condors. Entry when IV Rank > 50%. Short strike at 0.16 delta (~84% OTM). DTE 30–45 days. Close at 50% max profit or 21 DTE (whichever first). Loss limit at 200% of premium received.

2. **Layer 2 — VIX Mean Reversion Overlay (25%)**: Scale into elevated volatility (VIX > 25, risen > 30% in 5 days) with wide OTM put credit spreads on SPY. 45–60 DTE. Scale-in at VIX 25/30/35/40+. Wider loss limit (300% of premium).

3. **Layer 3 — Earnings Premium Selling (15%, optional)**: Iron condors/strangles on liquid large-caps (AAPL, MSFT, AMZN, GOOGL, META) when IV Rank > 70% and earnings within 1–2 days. Close immediately after the earnings move. Max 5 positions per earnings season.

### Target Performance

| Metric | Target |
|--------|--------|
| CAGR | 12–18% |
| Sharpe Ratio | 0.8–1.2 |
| Win Rate | 75–85% |
| Profit Factor | 1.8–2.5 |
| Max Drawdown | 15–25% |
| Monthly Income | 1–1.5% of allocated capital |

### Position Sizing

- Size by **maximum loss**, not premium received
- Max loss per trade: 2–3% of total portfolio equity
- Total Optimus exposure (sum of max losses): never exceed 15% of total portfolio
- Max concurrent: 3 positions per underlying, 8 total

### Key Risk Rules

- Never hold to expiration — close at 21 DTE or profit target
- Defined-risk structures only (spreads, not naked)
- IV Rank entry filter prevents selling cheap vol
- Circuit breaker: halt after 3 consecutive max losses

## Platform & Architecture

### QuantConnect (LEAN) + Interactive Brokers

- Language: Python
- Data provider: QuantConnect (NOT IBKR for Oanda CFDs)
- Brokerage: Interactive Brokers
- UK trader constraints: US ETFs (SPY, QQQ, IWM) blocked by KID/PRIIPs. Use options on these underlyings where available, or futures alternatives (ES, MES)

### File Structure

```
/Optimus/
├── main.py                 # Core algorithm, event handlers (<64KB)
├── signal_engine.py        # Entry/exit logic, IV rank, delta selection
├── risk_manager.py         # Portfolio risk, circuit breakers, drawdown
├── indicators.py           # IV rank, greeks, custom indicator wrappers
├── regime_detector.py      # VIX regime classification
├── position_sizer.py       # Max-loss sizing with drawdown scaling
├── execution_manager.py    # Spread order management, fill tracking
├── trade_tracker.py        # Trade logging, performance metrics
├── session_manager.py      # Market hours, expiration calendar
├── notifications.py        # Telegram/email alerts
├── conviction_scorer.py    # Multi-factor conviction for sizing
├── diagnostics.py          # Analytics, attribution
└── /shared/                # Shared library across all Stargaze algos
    ├── utils.py
    ├── constants.py
    └── sizing.py
```

### Platform Constraints

- Main algorithm file must be < 64KB — extract helpers into modules
- Use `QuoteBarConsolidator` for CFDs, `TradeBarConsolidator` for equities
- Options chain: use `self.add_option()` with appropriate filters for strike/expiry
- Warmup: always verify indicators are ready before trading; default to no-trade during warmup
- Log size: QC truncates at ~100KB; use condensed logging

## Development Principles

### From the Design Patterns Guide

1. **Simplicity over complexity** — only add features that demonstrably improve risk-adjusted returns
2. **One change at a time** — never combine multiple modifications; test each in isolation
3. **Baseline principle** — maintain an untouched baseline version for comparison
4. **Deterministic signals** — same inputs must always produce same outputs
5. **Risk manager has veto power** — no module can bypass risk checks
6. **ATR floor** — floor ATR at 50% of 100-bar average to prevent denominator collapse
7. **Respect the compounding engine** — understand how trade count, position size, and win asymmetry interact exponentially

### Versioning

- Format: `vMAJOR.MINOR.PATCH`
- Never modify a working version — create a new one
- Keep production branch separate from experiments
- Document every version's purpose and results

## Context Files

Strategy documents are in `/context/`:
- `stargaze portfolio strategy.pdf` — full portfolio strategy with all four algorithms
- `Trading_Algorithm_Design_Patterns_v2.docx` — design patterns guide from Megatron development

Backtest results go in `/backtest_results/`.

## Key Risks to Monitor

- **Tail risk**: sudden crashes produce losses many times typical profit. Defined-risk structures and strict sizing are non-negotiable
- **Correlation with market crashes**: put spreads lose fast in crashes. Offset at portfolio level by Megatron (gold rallies in crises)
- **QuantConnect options execution**: slippage on spreads can be significant. Stick to most liquid underlyings and strikes
- **Assignment risk**: ITM short options near expiration. The 21 DTE time stop and loss limits prevent this
- **Gamma risk**: accelerates near expiration. Never hold past 21 DTE

## Commands

- `lean backtest Optimus` — run local backtest via LEAN CLI
- `lean cloud backtest Optimus` — run on QuantConnect cloud
- Results output to `/backtest_results/`
