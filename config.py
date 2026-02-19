# config.py — Optimus v2.0-MVP
# Single source of truth for all parameters
# MVP: /ES only. Other assets defined but disabled.

MODULE_VERSION = "1.0"

# ─── Asset Configuration ──────────────────────────────────────────────
# Each underlying has its own parameter set. MVP only activates ES.

ACTIVE_ASSETS = ["ES"]  # MVP: ES only. Phase 2 adds GC, CL, ZB, 6E.

ASSET_CONFIG = {
    "ES": {
        "name": "E-mini S&P 500",
        "future_ticker": Futures.Indices.SP500EMini,
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
        "loss_limit_ic_pct": 100,
        "time_stop_dte": 21,
        "roll_trigger_delta": 0.30,
        "max_concurrent": 2,
        "min_dte_entry": 35,
        "max_dte_entry": 55,
        "regime_filter": None,
        # Crisis threshold
        "crisis_rv_threshold": None,  # Uses VIX for ES
        # Regime parameters
        "adx_trending_threshold": 25,
        "adx_low_vol_threshold": 20,
        "atr_distance_threshold": 1.5,
        "bandwidth_squeeze_percentile": 20,
        "high_vol_rv_multiplier": 2.0,
        "high_vol_session_move_pct": 3.0,
    },
}

# ─── Global Parameters ────────────────────────────────────────────────

GLOBAL = {
    # Position sizing
    "risk_pct_per_trade": 0.025,        # 2.5% of equity max loss per IC
    "aggregate_max_loss_pct": 0.15,     # 15% total max loss across all positions
    "max_total_positions": 12,          # Max open positions across all underlyings

    # Margin
    "margin_cap": 0.45,                 # Max margin utilisation

    # Timing
    "stagger_min_days": 15,             # Min age of existing position before new entry
    "target_dte": 45,                   # Ideal DTE for entry

    # Risk halts
    "daily_loss_halt_pct": 0.03,        # 3% daily P&L triggers day halt
    "weekly_loss_halt_pct": 0.05,       # 5% weekly triggers week halt
    "monthly_dd_halt_pct": 0.08,        # 8% MTD triggers month halt

    # VIX
    "vix_crisis": 35,                   # VIX crisis threshold (ES-specific)

    # Trend gradient
    "trend_scaling_factor": 0.5,        # Sensitivity (range: 0.3–0.8)
    "trend_score_suppress": 0.9,        # Above this + low IV = skip trade
    "trend_score_suppress_iv": 30,      # IV rank below which suppression applies

    # Management schedule (ET hours)
    "entry_scan_hour": 15,              # 15:00 ET daily scan
    "management_hours": [10, 15],       # 10:00 and 15:00 ET management scans

    # Catastrophic stop
    "catastrophic_atr_multiple": 3.0,   # 3x ATR(14) single-session move

    # ATR floor (design pattern)
    "atr_floor_pct": 0.50,             # Floor at 50% of 100-bar average

    # Slippage for backtesting
    "option_slippage_pct": 0.10,       # 10% of mid-price

    # Warmup
    "warmup_days": 260,                # 252 trading days for IV rank + buffer

    # Regime confirmation
    "regime_confirm_days": 2,          # Days to confirm regime change
    "regime_recovery_days": 5,         # Days of declining RV to return to RANGING

    # Initial capital
    "initial_capital": 100000,
}

# ─── Liquidity Thresholds ─────────────────────────────────────────────

LIQUIDITY = {
    "max_spread_pct": 0.15,            # Bid-ask spread < 15% of mid
    "min_open_interest": 500,          # Min OI on short strike
    "min_underlying_volume": 50000,    # Min daily volume on underlying
}
