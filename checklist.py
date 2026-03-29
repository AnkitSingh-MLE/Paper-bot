import math
import logging
import config

log = logging.getLogger(__name__)

PATTERN_SCORE = {6: 35, 5: 28, 4: 22, 3: 16, 2: 10, 0: 0}

def _pattern_pts(raw_value: float, bullish: bool) -> tuple[int, str]:
    val = int(raw_value)
    if bullish and val > 0:
        pts = PATTERN_SCORE.get(val, 0)
        label = {6:"bull_engulf", 5:"morn_star", 4:"hammer", 3:"piercing", 2:"bull_harami"}.get(val, "pattern")
        return pts, f"{label}+{pts}"
    return 0, ""

def score_varsity_swing_long(latest: dict) -> tuple[bool, int, list, dict]:
    # --- HARD FILTERS ---
    if latest["close"] < latest.get("ema_200", 0) or latest.get("ema_20", 0) < latest.get("ema_50", 0):
        return False, 0, ["bear_regime_skip"], {}
    if latest.get("adx", 0) < 20:
        return False, 0, ["sideways_chop_skip"], {}
    if latest.get("macd_line", 0) < latest.get("macd_signal", 0):
        return False, 0, ["no_momentum_skip"], {}

    # --- SCORING ---
    score = 40 
    pts, label = _pattern_pts(latest.get("engulfing", 0), bullish=True)
    score += pts
    if latest.get("vol_ratio", 0) >= 1.2: score += 20
    
    passed = score >= config.SWING_PASSING_SCORE
    return passed, score, [label], latest

def calculate_atr_levels(entry: float, atr: float, strategy: str, is_short: bool = False) -> tuple[float, float]:
    """2.5x ATR for Swing. Enforces $0.50 Min Profit Floor."""
    stop_mult = 2.5 if strategy == "swing" else 1.5
    stop_dist = max(stop_mult * atr, entry * 0.01)
    
    # Target: Min of ($0.50 profit OR 1.5% move OR 2x Stop distance)
    min_profit = max(0.50, entry * 0.015, stop_dist * 2.0)
    target_dist = min_profit

    if is_short:
        stop, target = entry + stop_dist, entry - target_dist
    else:
        stop, target = entry - stop_dist, entry + target_dist
    return round(stop, 2), round(target, 2)