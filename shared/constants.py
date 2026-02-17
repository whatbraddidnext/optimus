# shared/constants.py — Stargaze Capital Shared Constants
# Version: v2.001

from enum import Enum


class Regime(Enum):
    """Market regime classification."""
    BULLISH_CALM = "Bullish Calm"
    ELEVATED_VOL = "Elevated Vol"
    HIGH_VOL = "High Vol"
    CRISIS = "Crisis"
    BEAR_TREND = "Bear Trend"


class ExitReason(Enum):
    """Why a position was closed."""
    PROFIT_TARGET = "PROFIT TARGET"
    STOP_LOSS = "STOP LOSS"
    TIME_STOP = "TIME STOP"
    REGIME_SHIFT = "REGIME SHIFT"
    CIRCUIT_BREAKER = "CIRCUIT BREAKER"
    MANUAL = "MANUAL"


class TradeResult(Enum):
    """Win or loss classification."""
    WIN = "WIN"
    LOSS = "LOSS"
    BREAKEVEN = "BREAKEVEN"


class GateResult(Enum):
    """Result of a single entry gate evaluation."""
    PASS = "PASS"
    FAIL = "FAIL"
    SKIP = "SKIP"


class GldSignal(Enum):
    """GLD inverse correlation signal."""
    RISK_ON_ROTATION = "Risk-On Rotation"
    NEUTRAL = "Neutral"
    CAUTION = "Caution"
    FLIGHT_TO_SAFETY = "Flight to Safety"


# SPX option multiplier
SPX_MULTIPLIER = 100

# Minimum bars required for warmup per indicator
WARMUP_BARS = {
    "ema_200": 200,
    "bb_20": 20,
    "rsi_14": 14,
    "iv_rank": 252,  # 52 weeks of daily bars
    "gld_ema_50": 50,
    "gld_roc_5": 5,
    "gld_spx_corr_20": 20,
}
