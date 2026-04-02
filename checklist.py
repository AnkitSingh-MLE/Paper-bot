"""
checklist.py
────────────
Intraday point system (100 pts max, passing = 65):
  Signal quality    25 pts  ORB first break=25, VWAP reclaim=20
  EMA trend agrees  20 pts
  VWAP alignment    20 pts
  Volume surge      20 pts  2x=20, 1.5x=15, 1.2x=8
  RSI momentum      15 pts
"""

import logging
import config

log = logging.getLogger(__name__)

PATTERN_SCORE = {6: 35, 5: 28, 4: 22, 3: 16, 2: 10, 0: 0}

def _pattern_pts(raw_value: float, bullish: bool) -> tuple[int, str]:
    val = int(raw_value)
    if bullish and val > 0:
        pts = PATTERN_SCORE.get(val, 0)
        label = {6:"bull_engulf", 5:"morn_star", 4:"hammer",
                 3:"piercing", 2:"bull_harami"}.get(val, "pattern")
        return pts, f"{label}+{pts}"
    return 0, ""

def score_varsity_swing_long(latest: dict) -> tuple[bool, int, list, dict]:
    if latest.get("close", 0) < latest.get("ema_200", 0) or \
       latest.get("ema_20", 0) < latest.get("ema_50", 0):
        return False, 0, ["bear_regime_skip"], {}
    if latest.get("adx", 0) < 20:
        return False, 0, ["sideways_chop_skip"], {}
    if latest.get("macd_line", 0) < latest.get("macd_signal", 0):
        return False, 0, ["no_momentum_skip"], {}

    score = 40
    pts, label = _pattern_pts(latest.get("engulfing", 0), bullish=True)
    score += pts
    if latest.get("vol_ratio", 0) >= 1.2:
        score += 20

    passed = score >= config.SWING_PASSING_SCORE
    breakdown = {
        "score":     score,
        "pattern":   label,
        "notes":     label,
        "vol_ratio": latest.get("vol_ratio", 0),
    }
    return passed, score, [label] if label else [], breakdown

def _volume_pts(vol_ratio: float) -> tuple[int, str]:
    if vol_ratio >= 2.0: return 20, "vol_surge_2x+20"
    if vol_ratio >= 1.5: return 15, "vol_surge_1.5x+15"
    if vol_ratio >= 1.2: return  8, "vol_surge_1.2x+8"
    return 0, "vol_weak+0"

def _or_quality_ok(latest: dict) -> bool:
    close    = latest.get("close", 1)
    or_range = latest.get("or_range", 0)
    if close <= 0: return False
    pct = or_range / close
    return 0.003 <= pct <= 0.03

def score_intraday_long(latest: dict) -> tuple[bool, int, list, dict]:
    orb_fired  = bool(latest.get("orb_long_first", False))
    vwap_fired = bool(latest.get("vwap_reclaim_long", False))

    if not orb_fired and not vwap_fired:
        return False, 0, ["no_signal_skip"], {}
    if not _or_quality_ok(latest):
        return False, 0, ["or_range_skip"], {}

    rsi = latest.get("rsi", 50)
    if rsi > 80:
        return False, 0, ["overbought_skip"], {}

    score = 0
    notes = []

    if orb_fired:
        score += 25; notes.append("orb_break+25")
    elif vwap_fired:
        score += 20; notes.append("vwap_reclaim+20")

    if latest.get("ema_trend_long", False):
        score += 20; notes.append("ema_trend+20")

    close = latest.get("close", 0)
    vwap  = latest.get("vwap", 0)
    if close > vwap:
        score += 20; notes.append("above_vwap+20")

    vol_pts, vol_note = _volume_pts(latest.get("vol_ratio", 0))
    score += vol_pts; notes.append(vol_note)

    if 40 <= rsi <= 65:
        score += 15; notes.append("rsi_sweet+15")
    elif 35 <= rsi < 40 or 65 < rsi <= 70:
        score += 8;  notes.append("rsi_ok+8")

    passed = score >= config.INTRADAY_PASSING_SCORE
    breakdown = {
        "score":     score,
        "notes":     " | ".join(notes),
        "vol_ratio": latest.get("vol_ratio", 0),
        "rsi_val":   rsi,
        "vwap_val":  vwap,
        "or_high":   latest.get("or_high", 0),
        "or_low":    latest.get("or_low", 0),
    }
    return passed, score, notes, breakdown

def score_intraday_short(latest: dict) -> tuple[bool, int, list, dict]:
    orb_fired  = bool(latest.get("orb_short_first", False))
    vwap_fired = bool(latest.get("vwap_reclaim_short", False))

    if not orb_fired and not vwap_fired:
        return False, 0, ["no_signal_skip"], {}
    if not _or_quality_ok(latest):
        return False, 0, ["or_range_skip"], {}

    rsi = latest.get("rsi", 50)
    if rsi < 20:
        return False, 0, ["oversold_skip"], {}

    score = 0
    notes = []

    if orb_fired:
        score += 25; notes.append("orb_breakdown+25")
    elif vwap_fired:
        score += 20; notes.append("vwap_loss+20")

    if latest.get("ema_trend_short", False):
        score += 20; notes.append("ema_trend+20")

    close = latest.get("close", 0)
    vwap  = latest.get("vwap", 0)
    if close < vwap:
        score += 20; notes.append("below_vwap+20")

    vol_pts, vol_note = _volume_pts(latest.get("vol_ratio", 0))
    score += vol_pts; notes.append(vol_note)

    if 35 <= rsi <= 60:
        score += 15; notes.append("rsi_sweet+15")
    elif 30 <= rsi < 35 or 60 < rsi <= 65:
        score += 8;  notes.append("rsi_ok+8")

    passed = score >= config.INTRADAY_PASSING_SCORE
    breakdown = {
        "score":     score,
        "notes":     " | ".join(notes),
        "vol_ratio": latest.get("vol_ratio", 0),
        "rsi_val":   rsi,
        "vwap_val":  vwap,
        "or_high":   latest.get("or_high", 0),
        "or_low":    latest.get("or_low", 0),
    }
    return passed, score, notes, breakdown

def calculate_atr_levels(entry: float, atr: float, strategy: str,
                         is_short: bool = False) -> tuple[float, float]:
    stop_mult   = 2.5 if strategy == "swing" else 1.5
    stop_dist   = max(stop_mult * atr, entry * 0.005, 0.10)
    target_dist = max(stop_dist * 2.0, 0.50)
    if is_short:
        stop, target = entry + stop_dist, entry - target_dist
    else:
        stop, target = entry - stop_dist, entry + target_dist
    return round(stop, 2), round(target, 2)
