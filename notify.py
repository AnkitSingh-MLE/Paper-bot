"""
notify.py
─────────
Slack notification system for the paper bot.
Sends alerts for: trade entry, daily summary, bot start/stop, errors.

Usage:
    from notify import alert_trade, alert_summary, alert_info, alert_error
"""

import os
import json
import logging
import urllib.request
import urllib.error
from datetime import datetime

log = logging.getLogger(__name__)

# Load webhook from environment
SLACK_WEBHOOK = os.getenv("SLACK_WEBHOOK", "")


def _post(payload: dict) -> bool:
    """Send payload to Slack webhook. Returns True on success."""
    if not SLACK_WEBHOOK:
        log.warning("SLACK_WEBHOOK not set — skipping notification.")
        return False
    try:
        data = json.dumps(payload).encode("utf-8")
        req  = urllib.request.Request(
            SLACK_WEBHOOK,
            data=data,
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        with urllib.request.urlopen(req, timeout=5) as resp:
            return resp.status == 200
    except urllib.error.URLError as e:
        log.error(f"Slack notification failed: {e}")
        return False


def alert_trade(symbol: str, direction: str, strategy: str,
                entry: float, stop: float, target: float,
                qty: int, score: int, rrr: float):
    """Send a trade entry alert."""
    emoji    = "🟢" if direction == "long" else "🔴"
    tag      = "LONG" if direction == "long" else "SHORT"
    strat    = strategy.replace("_", " ").upper()
    pnl_risk = round((entry - stop) / entry * 100, 2) if direction == "long" else round((stop - entry) / entry * 100, 2)

    payload = {"blocks": [
        {"type": "header", "text": {"type": "plain_text", "text": f"{emoji} TRADE ENTRY — {symbol}"}},
        {"type": "section", "fields": [
            {"type": "mrkdwn", "text": f"*Strategy:*\n{strat}"},
            {"type": "mrkdwn", "text": f"*Direction:*\n{tag}"},
            {"type": "mrkdwn", "text": f"*Entry:*\n${entry:.2f}"},
            {"type": "mrkdwn", "text": f"*Qty:*\n{qty} shares"},
            {"type": "mrkdwn", "text": f"*Stop:*\n${stop:.2f}  (-{pnl_risk:.2f}%)"},
            {"type": "mrkdwn", "text": f"*Target:*\n${target:.2f}"},
            {"type": "mrkdwn", "text": f"*Score:*\n{score}/100"},
            {"type": "mrkdwn", "text": f"*R:R:*\n{rrr:.2f}"},
        ]},
        {"type": "context", "elements": [
            {"type": "mrkdwn", "text": f"📅 {datetime.now().strftime('%Y-%m-%d %H:%M:%S ET')}"}
        ]}
    ]}
    _post(payload)


def alert_reconcile(wins: int, losses: int, win_rate: float,
                    avg_win: float, avg_loss: float, matched: int):
    """Send end-of-day reconcile summary."""
    emoji = "✅" if win_rate >= 52 else "⚠️"
    payload = {"blocks": [
        {"type": "header", "text": {"type": "plain_text", "text": f"{emoji} EOD RECONCILE SUMMARY"}},
        {"type": "section", "fields": [
            {"type": "mrkdwn", "text": f"*Trades Matched Today:*\n{matched}"},
            {"type": "mrkdwn", "text": f"*All-Time Win Rate:*\n{win_rate:.1f}%"},
            {"type": "mrkdwn", "text": f"*All-Time Wins:*\n{wins}"},
            {"type": "mrkdwn", "text": f"*All-Time Losses:*\n{losses}"},
            {"type": "mrkdwn", "text": f"*Avg Win:*\n+{avg_win:.2f}%"},
            {"type": "mrkdwn", "text": f"*Avg Loss:*\n{avg_loss:.2f}%"},
        ]},
        {"type": "context", "elements": [
            {"type": "mrkdwn", "text": f"📅 {datetime.now().strftime('%Y-%m-%d')}  |  Target win rate: 52%+"}
        ]}
    ]}
    _post(payload)


def alert_info(message: str):
    """Send a plain info message — bot start, stop, janitor actions."""
    _post({"text": f"ℹ️  {message}"})


def alert_error(message: str):
    """Send an error alert."""
    _post({"text": f"🚨 *ERROR:* {message}"})


def alert_janitor(action: str, symbols: list[str] = None):
    """Send janitor/reaper action alert."""
    if symbols:
        sym_list = ", ".join(symbols)
        _post({"text": f"🧹 *JANITOR:* {action} — closed: {sym_list}"})
    else:
        _post({"text": f"🧹 *JANITOR:* {action}"})


# ── Quick test ──────────────────────────────────────────────
if __name__ == "__main__":
    import sys
    logging.basicConfig(level=logging.INFO)

    if not SLACK_WEBHOOK:
        print("ERROR: SLACK_WEBHOOK environment variable not set.")
        print("Add it to your .env file and retry.")
        sys.exit(1)

    print("Sending test messages to Slack...")
    alert_info("PaperBot connected ✅ — notification system online")
    alert_trade("NVDA", "long", "intraday_long", 177.50, 175.00, 181.00, 28, 88, 2.1)
    alert_reconcile(wins=5, losses=5, win_rate=50.0, avg_win=2.36, avg_loss=-1.41, matched=10)
    alert_error("Test error alert — ignore this")
    print("Done. Check your Slack channel.")
