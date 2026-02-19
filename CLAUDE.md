# CLAUDE.md — Optimus Project

## Role

You are a quantitative analyst and trading algorithm designer specialising in options markets. You have deep expertise in premium selling strategies — iron condors, credit spreads, and volatility mean reversion. You design, code, and test high-performing algorithms that sell options to harvest theta decay income on the QuantConnect (LEAN) platform, deployed via Interactive Brokers.

## Project Context

Optimus is a systematic futures options premium selling strategy that harvests the volatility risk premium across five uncorrelated futures underlyings (/ES, /GC, /CL, /ZB, /6E). It sells trend-adjusted iron condors and strangles, collecting theta decay from both sides. Phase 2 in the Stargaze Capital portfolio build sequence.

Full design: `context/Optimus_HLD_v2.0.md`

## Current Version

**v2.0-MVP** — /ES Iron Condors Only

## Build Roadmap

### MVP (v2.0-MVP) — /ES Iron Condors ✅ CURRENT BUILD

Single asset, single structure. Validate core profit engine.

| Module | Purpose | Status |
|--------|---------|--------|
| config.py | /ES parameters, global defaults | |
| indicators.py | IV Rank (52-week), ATR, ADX | |
| trend_gradient.py | Trend score + delta skew mapping | |
| regime_detector.py | RANGING/LOW_VOL/TRENDING/HIGH_VOL/CRISIS | |
| options_chain_manager.py | Chain parsing, strike selection, liquidity | |
| signal_engine.py | Multi-gate entry system | |
| position_sizer.py | Max-loss IC sizing | |
| risk_manager.py | Veto power, margin cap, loss halts | |
| execution_manager.py | IC combo order submission | |
| position_manager.py | Profit target, loss limit, time stop exits | |
| trade_tracker.py | P&L logging, win/loss metrics | |
| main.py | QC orchestration, warmup, event handlers | |

**Success criteria:** Win rate > 78%, correct IC construction, exit logic fires correctly, trend gradient measurably improves win rate vs symmetric baseline.

### Phase 2 — Multi-Asset Expansion

- Add /ZB (negatively correlated with /ES)
- Add /GC with gold trend suppress filter
- Add /CL with tighter parameters
- Add /6E with FX trend suppress filter
- Correlation alert (3+ underlyings in loss)
- Per-asset crisis thresholds

### Phase 3 — Tier 2 Strangles

- Strangle structure (Tier 2) with activation conditions
- Notional-based sizing for undefined risk
- Margin expansion protocol
- VIX-gated tier selection

### Phase 4 — Rolling & Defence

- Roll trigger at delta threshold
- Max 2 rolls per position
- Inversion detection and handling
- Roll P&L tracking

### Phase 5 — Production Hardening

- Failsafe / state persistence (Object Store)
- Recovery & reconciliation on reconnect
- Session manager with blackout calendar (FOMC, NFP, CPI)
- Notifications (Telegram alerts, heartbeat, daily summary)
- Diagnostics & attribution reporting

### Phase 6 — Optimisation

- Walk-forward validation (2yr in-sample, 6mo OOS)
- Per-asset parameter sweeps
- Trend scaling factor optimisation
- Delta/profit-target sensitivity analysis

## Platform & Architecture

### QuantConnect (LEAN) + Interactive Brokers

- Language: Python
- Data provider: QuantConnect (futures + options chain data)
- Brokerage: Interactive Brokers
- Asset class: Futures Options (CME)
- Margin: SPAN (risk-based)

### File Structure (v2.0)

```
/Optimus/
├── main.py                     # QC orchestration, event handlers (<64KB)
├── config.py                   # ASSET_CONFIG and global parameters
├── indicators.py               # IV Rank, ATR, ADX wrappers
├── trend_gradient.py           # Trend score, delta skew mapping
├── regime_detector.py          # Per-asset regime classification
├── options_chain_manager.py    # Chain parsing, strike selection, liquidity
├── signal_engine.py            # Multi-gate entry system
├── position_sizer.py           # Max-loss sizing (IC), notional sizing (strangles)
├── risk_manager.py             # Veto power, margin, loss halts
├── execution_manager.py        # Order submission, fill tracking
├── position_manager.py         # Exit logic, P&L tracking
├── trade_tracker.py            # Trade logging, performance metrics
├── context/
│   ├── Optimus_HLD_v2.0.md
│   ├── Trading_Algorithm_Design_Patterns_v2.docx
│   └── stargaze portfolio strategy.pdf
└── backtest_results/
```

### Platform Constraints

- Main algorithm file must be < 64KB — extract helpers into modules
- Use `TradeBarConsolidator` for futures
- Options chain: use `self.add_future_option()` with DTE/delta filters
- Warmup: 252+ days for IV Rank (52-week lookback). Verify indicators ready before trading.
- Log size: QC truncates at ~100KB; use condensed logging

## Development Principles

1. **Simplicity over complexity** — only add features that demonstrably improve risk-adjusted returns
2. **One change at a time** — never combine multiple modifications; test each in isolation
3. **Baseline principle** — maintain an untouched baseline version for comparison
4. **Deterministic signals** — same inputs must always produce same outputs
5. **Risk manager has veto power** — no module can bypass risk checks
6. **ATR floor** — floor ATR at 50% of 100-bar average to prevent denominator collapse
7. **Respect the compounding engine** — understand how trade count, position size, and win asymmetry interact exponentially

## Versioning

- Format: `vMAJOR.MINOR.PATCH`
- Never modify a working version — create a new one
- Keep production branch separate from experiments
- Document every version's purpose and results

## Commands

- `lean backtest Optimus` — run local backtest via LEAN CLI
- `lean cloud backtest Optimus` — run on QuantConnect cloud
- Results output to `/backtest_results/`

## Improvement Log

| Date | Version | Change | Result |
|------|---------|--------|--------|
| 2026-02-19 | v2.0-MVP | Clean slate build from v2.0 HLD. /ES IC only. | Pending backtest |
