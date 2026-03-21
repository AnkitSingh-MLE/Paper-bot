"""
checklist.py v7 — Paper Trading
────────────────────────────────
Swing long:     Pattern-first Varsity. 200 EMA hard filter.
Intraday long:  VWAP hard filter. Pattern + momentum.
Intraday short: VWAP hard filter (below). Pattern + momentum mirror.

Intraday ATR: 1.0x stop / 2.0x target (tighter than swing for same-day)
Swing ATR:    1.5x stop / 3.0x target
"""

import logging
import config

log = logging.getLogger(__name__)

PATTERN_SCORE = {6: 35, 5: 28, 4: 22, 3: 16, 2: 10, 0: 0}


def _pattern_pts(raw_value: float, bullish: bool) -> tuple[int, str]:
    val = int(raw_value)
    if bullish and val > 0:
        pts   = PATTERN_SCORE.get(val, 0)
        label = {6:"bull_engulf", 5:"morn_star/marubozu", 4:"hammer",
                 3:"piercing", 2:"bull_harami"}.get(val, "pattern")
        return pts, f"{label}+{pts}"
    if not bullish and val < 0:
        pts   = PATTERN_SCORE.get(abs(val), 0)
        label = {6:"bear_engulf", 5:"eve_star/marubozu", 4:"shoot_star",
                 3:"dark_cloud", 2:"bear_harami"}.get(abs(val), "pattern")
        return pts, f"{label}+{pts}"
    return 0, ""


def score_based_position_size(score: int) -> float:
    """Swing: $200 base at 70, +$50 per 10pts."""
    base  = 200.0
    steps = max(0, (score - 70) // 10)
    return min(base + steps * 50.0, config.MAX_POSITION_SIZE)


def intraday_position_size(score: int) -> float:
    """Intraday: $1000 base at 70, +$200 per 10pts."""
    base  = config.INTRADAY_BASE_SIZE
    steps = max(0, (score - 70) // 10)
    return min(base + steps * config.INTRADAY_SIZE_STEP, config.INTRADAY_MAX_SIZE)


def score_varsity_swing_long(latest: dict) -> tuple[bool, int, list, dict]:
    """
    Swing long. Varsity priority: pattern > support > volume > trend > RSI > MACD > ADX.
    HARD: Price > 200 EMA. Max 120. Need 70.
    """
    notes     = []
    breakdown = {}

    ema_200 = latest.get("ema_200", 0)
    if not ema_200 or latest["close"] < ema_200:
        return False, 0, ["below_ema200"], {}

    score = 0

    pattern_raw = latest.get("engulfing", 0)
    pts, label  = _pattern_pts(pattern_raw, bullish=True)
    breakdown["pattern"] = label if pts > 0 else "none"
    breakdown["pattern_pts"] = pts
    if pts > 0:
        score += pts
        notes.append(label)

    support  = latest.get("support", 0)
    near_sup = bool(support and latest["close"] <= support * 1.05)
    breakdown["near_support"]  = near_sup
    breakdown["support_val"]   = round(support, 2) if support else 0
    breakdown["support10_val"] = round(latest.get("support10", 0), 2)
    breakdown["support_pts"]   = 25 if near_sup else 0
    if near_sup:
        score += 25
        notes.append("near_support+25")

    vol_ratio = latest.get("vol_ratio", 0)
    vol_fired = bool(vol_ratio >= 1.2)
    breakdown["vol_surge"] = vol_fired
    breakdown["vol_ratio"] = round(vol_ratio, 2)
    breakdown["vol_pts"]   = 20 if vol_fired else 0
    if vol_fired:
        score += 20
        notes.append("vol_surge+20")

    ema_20 = latest.get("ema_20", 0)
    ema_50 = latest.get("ema_50", 0)
    ema_aligned = bool(ema_20 and ema_50 and ema_20 > ema_50)
    breakdown["ema_aligned"] = ema_aligned
    breakdown["ema_20_val"]  = round(ema_20, 2) if ema_20 else 0
    breakdown["ema_50_val"]  = round(ema_50, 2) if ema_50 else 0
    breakdown["ema_200_val"] = round(ema_200, 2)
    breakdown["ema_pts"]     = 15 if ema_aligned else 0
    if ema_aligned:
        score += 15
        notes.append("ema20>ema50+15")

    rsi = latest.get("rsi", 50)
    rsi_fired = bool(30 < rsi < 50)
    breakdown["rsi_fired"] = rsi_fired
    breakdown["rsi_val"]   = round(rsi, 1)
    breakdown["rsi_pts"]   = 10 if rsi_fired else 0
    if rsi_fired:
        score += 10
        notes.append(f"rsi_oversold({rsi:.0f})+10")

    macd_hist  = latest.get("macd_hist", None)
    macd_fired = bool(macd_hist is not None and macd_hist > 0)
    breakdown["macd_fired"] = macd_fired
    breakdown["macd_hist"]  = round(macd_hist, 4) if macd_hist is not None else 0
    breakdown["macd_pts"]   = 10 if macd_fired else 0
    if macd_fired:
        score += 10
        notes.append("macd_pos+10")

    adx = latest.get("adx") or 0
    adx_fired = bool(adx == adx and adx > 15)
    breakdown["adx_fired"] = adx_fired
    breakdown["adx_val"]   = round(adx, 1) if adx else 0
    breakdown["adx_pts"]   = 5 if adx_fired else 0
    if adx_fired:
        score += 5
        notes.append(f"adx({adx:.0f})+5")

    breakdown["total_score"] = score
    breakdown["notes"]       = "|".join(notes)

    passed = score >= config.SWING_PASSING_SCORE
    return passed, score, notes, breakdown


# Alias for backward compatibility
score_varsity_swing = score_varsity_swing_long


def score_intraday_long(latest: dict) -> tuple[bool, int, list, dict]:
    """
    Intraday long. VWAP hard filter. Max 105. Need 70.
    Pattern +35 | Support +25 | Volume +20 | EMA +15 | RSI +10
    """
    notes     = []
    breakdown = {}

    vwap = latest.get("vwap")
    if vwap is None or latest["close"] <= vwap:
        return False, 0, ["below_vwap"], {}

    score = 0

    pattern_raw = latest.get("engulfing", 0)
    pts, label  = _pattern_pts(pattern_raw, bullish=True)
    breakdown["pattern"]     = label if pts > 0 else "none"
    breakdown["pattern_pts"] = pts
    if pts > 0:
        score += pts
        notes.append(label)

    support  = latest.get("support", 0)
    near_sup = bool(support and latest["close"] <= support * 1.0075)
    breakdown["near_support"] = near_sup
    breakdown["support_val"]  = round(support, 2) if support else 0
    breakdown["support_pts"]  = 25 if near_sup else 0
    if near_sup:
        score += 25
        notes.append("near_support+25")

    vol_ratio = latest.get("vol_ratio", 0)
    vol_fired = bool(vol_ratio >= 1.2)
    breakdown["vol_surge"] = vol_fired
    breakdown["vol_ratio"] = round(vol_ratio, 2)
    breakdown["vol_pts"]   = 20 if vol_fired else 0
    if vol_fired:
        score += 20
        notes.append("vol_surge+20")

    ema_aligned = bool(latest.get("ema_9", 0) > latest.get("ema_21", 0))
    breakdown["ema_aligned"] = ema_aligned
    breakdown["ema_pts"]     = 15 if ema_aligned else 0
    if ema_aligned:
        score += 15
        notes.append("ema_aligned+15")

    rsi = latest.get("rsi", 50)
    rsi_fired = bool(35 < rsi < 55)
    breakdown["rsi_fired"] = rsi_fired
    breakdown["rsi_val"]   = round(rsi, 1)
    breakdown["rsi_pts"]   = 10 if rsi_fired else 0
    if rsi_fired:
        score += 10
        notes.append(f"rsi_recovery({rsi:.0f})+10")

    breakdown["total_score"] = score
    breakdown["notes"]       = "|".join(notes)
    breakdown["vwap_val"]    = round(vwap, 2)

    passed = score >= config.INTRADAY_PASSING_SCORE
    return passed, score, notes, breakdown


def score_intraday_short(latest: dict) -> tuple[bool, int, list, dict]:
    """
    Intraday short. VWAP hard filter (below). Max 105. Need 70.
    Pattern +35 | Resistance +25 | Volume +20 | EMA +15 | RSI +10
    """
    notes     = []
    breakdown = {}

    vwap = latest.get("vwap")
    if vwap is None or latest["close"] >= vwap:
        return False, 0, ["above_vwap"], {}

    score = 0

    pattern_raw = latest.get("engulfing", 0)
    pts, label  = _pattern_pts(pattern_raw, bullish=False)
    breakdown["pattern"]     = label if pts > 0 else "none"
    breakdown["pattern_pts"] = pts
    if pts > 0:
        score += pts
        notes.append(label)

    resistance = latest.get("resistance", float("inf"))
    near_res   = bool(resistance and latest["close"] >= resistance * 0.99)
    breakdown["near_resistance"] = near_res
    breakdown["resistance_val"]  = round(resistance, 2) if resistance != float("inf") else 0
    breakdown["resistance_pts"]  = 25 if near_res else 0
    if near_res:
        score += 25
        notes.append("near_resistance+25")

    vol_ratio = latest.get("vol_ratio", 0)
    vol_fired = bool(vol_ratio >= 1.2)
    breakdown["vol_surge"] = vol_fired
    breakdown["vol_ratio"] = round(vol_ratio, 2)
    breakdown["vol_pts"]   = 20 if vol_fired else 0
    if vol_fired:
        score += 20
        notes.append("vol_surge+20")

    ema_bearish = bool(latest.get("ema_9", 0) < latest.get("ema_21", 0))
    breakdown["ema_bearish"] = ema_bearish
    breakdown["ema_pts"]     = 15 if ema_bearish else 0
    if ema_bearish:
        score += 15
        notes.append("ema_bearish+15")

    rsi = latest.get("rsi", 50)
    rsi_fired = bool(55 < rsi < 75)
    breakdown["rsi_fired"] = rsi_fired
    breakdown["rsi_val"]   = round(rsi, 1)
    breakdown["rsi_pts"]   = 10 if rsi_fired else 0
    if rsi_fired:
        score += 10
        notes.append(f"rsi_overbought({rsi:.0f})+10")

    breakdown["total_score"] = score
    breakdown["notes"]       = "|".join(notes)
    breakdown["vwap_val"]    = round(vwap, 2)

    passed = score >= config.INTRADAY_PASSING_SCORE
    return passed, score, notes, breakdown


def calculate_rrr(entry: float, target: float, stop: float) -> float:
    risk = entry - stop
    reward = target - entry
    if risk <= 0: return 0.0
    return round(reward / risk, 2)


def calculate_short_rrr(entry: float, target: float, stop: float) -> float:
    risk = stop - entry
    reward = entry - target
    if risk <= 0: return 0.0
    return round(reward / risk, 2)


def calculate_atr_levels(
    entry: float, atr: float, strategy: str, is_short: bool = False
) -> tuple[float, float]:
    """
    Swing:    1.5x stop / 3.0x target → RRR 2.0
    Intraday: 1.0x stop / 2.0x target → RRR 2.0 (tighter for same-day)
    """
    if strategy == "swing":
        stop_mult, target_mult = 1.5, 3.0
    else:
        stop_mult, target_mult = 1.0, 2.0

    if is_short:
        stop   = round(entry + stop_mult   * atr, 2)
        target = round(entry - target_mult * atr, 2)
    else:
        stop   = round(entry - stop_mult   * atr, 2)
        target = round(entry + target_mult * atr, 2)

    return stop, target
