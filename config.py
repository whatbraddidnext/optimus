# config.py — Optimus Centralised Configuration
# Version: v2.001
#
# All tuneable parameters in one place. No hardcoded values in other modules.
# Per-underlying configs allow extension to other tickers without code changes.


# =============================================================================
# STRATEGY VERSION
# =============================================================================
STRATEGY_VERSION = "v2.001"
STRATEGY_NAME = "Optimus"


# =============================================================================
# CORE TRADE PARAMETERS
# =============================================================================
TARGET_DELTA = -0.16           # Short strike delta target
SPREAD_WIDTH = 50              # Points between short and long strikes (SPX)
TARGET_DTE = 45                # Target days to expiration at entry
MIN_DTE_ENTRY = 30             # Minimum acceptable DTE for new entries
MAX_DTE_ENTRY = 60             # Maximum acceptable DTE for new entries
PROFIT_TARGET_PCT = 50         # Close at this % of max profit
STOP_LOSS_MULTIPLIER = 2.0     # Close when spread value = multiplier x credit
TIME_STOP_DTE = 21             # Close all positions at this DTE
MIN_IV_RANK = 50               # Minimum IV Rank (percentile) for entry


# =============================================================================
# POSITION LIMITS & RISK
# =============================================================================
MIN_DAYS_BETWEEN_ENTRIES = 3   # Business days between entries (same underlying)
MAX_CONCURRENT_PER_UNDERLYING = 3
MAX_CONCURRENT_TOTAL = 8
MAX_PORTFOLIO_HEAT_PCT = 15    # Max sum of max losses as % of equity
RISK_PER_TRADE_PCT = 2.0       # Max loss per trade as % of equity
CIRCUIT_BREAKER_COUNT = 3      # Consecutive max losses before halt
CIRCUIT_BREAKER_COOLDOWN_DAYS = 5  # Business days to pause after circuit breaker
MAX_AGGREGATE_DELTA = -0.50    # Portfolio-level short delta limit


# =============================================================================
# BOLLINGER BAND & MEAN REVERSION
# =============================================================================
BB_PERIOD = 20                 # Bollinger Band lookback period
BB_STD_DEV = 2.0              # Bollinger Band standard deviation multiplier
BB_TOUCH_LOOKBACK = 5          # Bars to look back for lower BB touch
MIN_CONSECUTIVE_UP_CLOSES = 1  # Required consecutive higher closes for confirmation
RSI_PERIOD = 14                # RSI calculation period
RSI_OVERSOLD_THRESHOLD = 30    # RSI must be above this and rising


# =============================================================================
# MARKET FILTER PARAMETERS
# =============================================================================
TREND_EMA_PERIOD = 200         # EMA period for trend filter
VIX_CRISIS_THRESHOLD = 35      # VIX level that triggers crisis regime
VIX_HIGH_VOL_THRESHOLD = 25    # VIX level that triggers high vol regime
VIX_ELEVATED_THRESHOLD = 18    # VIX level boundary for bullish calm vs elevated
VIX_TERM_STRUCTURE_THRESHOLD = 1.05  # Front/second month ratio for backwardation


# =============================================================================
# GLD INVERSE CORRELATION PARAMETERS
# =============================================================================
GLD_ROC_PERIOD = 5             # GLD rate of change lookback (days)
GLD_SPX_CORRELATION_PERIOD = 20  # Rolling window for GLD/SPX return correlation
GLD_SURGE_THRESHOLD = 1.5     # GLD daily % move that signals flight to safety
GLD_CONVICTION_BOOST = 0.20    # Added when GLD confirms risk-on rotation
GLD_CONVICTION_PENALTY_MILD = -0.15   # When GLD rising during SPX bounce
GLD_CONVICTION_PENALTY_SEVERE = -0.30  # When GLD surging (flight to safety)
GLD_TREND_EMA = 50             # EMA period for GLD trend in regime detection


# =============================================================================
# EXECUTION
# =============================================================================
EXECUTION_EARLIEST_HOUR = 10   # Earliest hour (ET) to execute trades
EXECUTION_EARLIEST_MINUTE = 0  # Earliest minute (ET) to execute trades
MAX_BID_ASK_SPREAD_PCT = 20   # Max bid/ask spread as % of mid-market credit


# =============================================================================
# CONVICTION SCORER WEIGHTS
# =============================================================================
CONVICTION_MIN = 0.5           # Minimum conviction multiplier
CONVICTION_MAX = 1.5           # Maximum conviction multiplier
CONVICTION_BASE = 1.0          # Neutral conviction


# =============================================================================
# DRAWDOWN SCALING
# =============================================================================
DRAWDOWN_LEVEL_1 = 0.10       # 10% drawdown threshold
DRAWDOWN_LEVEL_2 = 0.20       # 20% drawdown threshold
DRAWDOWN_RISK_1 = 1.5         # Risk % at level 1 drawdown
DRAWDOWN_RISK_2 = 1.0         # Risk % at level 2 drawdown


# =============================================================================
# WARMUP
# =============================================================================
WARMUP_PERIOD_DAYS = 252       # Days of historical data needed before trading


# =============================================================================
# PER-UNDERLYING CONFIGURATION
# =============================================================================
UNDERLYING_CONFIG = {
    "SPX": {
        "spread_width": SPREAD_WIDTH,
        "target_delta": TARGET_DELTA,
        "target_dte": TARGET_DTE,
        "min_dte": MIN_DTE_ENTRY,
        "max_dte": MAX_DTE_ENTRY,
        "min_iv_rank": MIN_IV_RANK,
        "max_concurrent": MAX_CONCURRENT_PER_UNDERLYING,
        "bb_period": BB_PERIOD,
        "bb_std": BB_STD_DEV,
        "bb_touch_lookback": BB_TOUCH_LOOKBACK,
        "min_consecutive_up_closes": MIN_CONSECUTIVE_UP_CLOSES,
        "multiplier": 100,
        "min_days_between_entries": MIN_DAYS_BETWEEN_ENTRIES,
    },
    # Future: add other underlyings with their own params
    # "RUT": { ... },
    # "NDX": { ... },
}


# =============================================================================
# NOTIFICATIONS (placeholders — configure per environment)
# =============================================================================
TELEGRAM_ENABLED = False
TELEGRAM_BOT_TOKEN = ""
TELEGRAM_CHAT_ID = ""
EMAIL_ENABLED = False
EMAIL_RECIPIENT = ""


# =============================================================================
# LOGGING
# =============================================================================
LOG_CONDENSED = True           # Use condensed logging to stay under QC 100KB limit
LOG_ENTRY_EVALS = True         # Log every daily entry evaluation
LOG_EXIT_EVALS = True          # Log every daily exit evaluation
LOG_DAILY_DASHBOARD = True     # Log daily dashboard summary
