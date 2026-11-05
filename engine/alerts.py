"""Alerting & Webhook Notification Engine for Hotel Stays & Point Arbitrage.
Supports Discord Webhooks, Telegram Bot API, and formatted Console/Log Alerts.
"""
import logging
import json
import httpx
from datetime import datetime
from typing import List, Dict, Any, Optional

logger = logging.getLogger("hotel_alerts")

class DealAlertEngine:
    def __init__(self, discord_webhook_url: Optional[str] = None, telegram_bot_token: Optional[str] = None, telegram_chat_id: Optional[str] = None):
        self.discord_webhook_url = discord_webhook_url
        self.telegram_bot_token = telegram_bot_token
        self.telegram_chat_id = telegram_chat_id

    def evaluate_deal(self, deal: Dict[str, Any]) -> Dict[str, Any]:
        """Evaluates whether a rate record qualifies as an urgent deal alert."""
        cpp = deal.get("cents_per_point", 0.0)
        surge_multiplier = deal.get("surge_multiplier", 1.0)
        brand = deal.get("brand", "")

        # High-value thresholds
        thresholds = {
            "HYATT": 1.9,      # >= 1.9c / pt
            "MARRIOTT": 0.85,  # >= 0.85c / pt
            "HILTON": 0.55,    # >= 0.55c / pt
            "IHG": 0.65,       # >= 0.65c / pt
            "WYNDHAM": 1.2,    # >= 1.2c / pt
        }

        is_alert_worthy = False
        alert_reason = []

        target_cpp = thresholds.get(brand, 1.0)
        if cpp >= target_cpp:
            is_alert_worthy = True
            alert_reason.append(f"🔥 Exceptional CPP: {cpp:.2f}¢/pt (Target: {target_cpp:.2f}¢)")

        if surge_multiplier >= 2.5:
            is_alert_worthy = True
            alert_reason.append(f"📈 Extreme Cash Surge: {surge_multiplier:.2f}x above baseline")

        deal["is_alert"] = is_alert_worthy
        deal["alert_reasons"] = alert_reason
        return deal

    def send_discord_alert(self, deals: List[Dict[str, Any]]) -> bool:
        """Dispatches rich deal alerts to Discord channel via webhook."""
        if not self.discord_webhook_url or not deals:
            return False

        embeds = []
        for d in deals[:10]:  # Cap at 10 per webhook payload
            embed = {
                "title": f"🚨 SWEET SPOT ALERT: {d['hotel_name']}",
                "url": d.get("official_url", "https://www.google.com"),
                "color": 0x10B981 if d.get("brand") == "HYATT" else 0xEF4444,
                "fields": [
                    {"name": "🏨 Brand & City", "value": f"`{d['brand']}` • {d['city']}", "inline": True},
                    {"name": "📅 Stay Date", "value": str(d['stay_date']), "inline": True},
                    {"name": "💎 CPP Valuation", "value": f"**{d.get('cents_per_point', 0.0):.2f}¢ / point**", "inline": True},
                    {"name": "💵 Cash vs Floor", "value": f"Current: **${d['cash_rate']:.2f}**\nFloor: `${d.get('cash_floor', 0.0):.2f}`", "inline": True},
                    {"name": "🎯 Points Needed", "value": f"**{d.get('points_required', 0):,} pts**", "inline": True},
                    {"name": "🏷️ Deal Rating", "value": d.get("deal_rating", "HIGH_VALUE"), "inline": True},
                ],
                "footer": {"text": "All Hotel Stays Arbitrage Monitor • Live Alert"},
                "timestamp": datetime.utcnow().isoformat()
            }
            embeds.append(embed)

        payload = {
            "content": f"⚡ **{len(deals)} High-Value Hotel Arbitrage Deals Detected!**",
            "embeds": embeds
        }

        try:
            r = httpx.post(self.discord_webhook_url, json=payload, timeout=10.0)
            return r.status_code in [200, 204]
        except Exception as e:
            logger.error(f"Failed to post Discord webhook: {e}")
            return False
