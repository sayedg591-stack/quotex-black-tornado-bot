"""Telegram bot notification dispatcher with exact Black Tornado v1.0 layout.
Updated to support Telegram custom emojis (custom_emoji_id) for channel and pair labels.
Fixed UTF-16 offset calculation for Telegram entities (avoids "ends in a middle of a UTF-16 symbol" error).
"""
import aiohttp
import pytz
from datetime import datetime
from typing import Dict, Any, Optional
from app.config import settings
import logging

logger = logging.getLogger(__name__)


class TelegramNotifier:
    def __init__(
        self,
        bot_token: Optional[str] = None,
        chat_id: Optional[str] = None,
        tz_name: str = settings.DISPLAY_TIMEZONE,
        emoji_channel_id: Optional[str] = None,
        emoji_pair_id: Optional[str] = None,
    ):
        self.bot_token = bot_token or settings.TELEGRAM_BOT_TOKEN
        self.chat_id = chat_id or settings.TELEGRAM_CHAT_ID
        self.tz = pytz.timezone(tz_name)

        # custom emoji IDs (can be overridden when constructing the notifier)
        # Provided defaults come from user request
        self.emoji_channel_id = emoji_channel_id or "6214983170991853422"
        self.emoji_pair_id = emoji_pair_id or "5231200819986047254"

    def _format_time(self, ts: int) -> str:
        dt = datetime.fromtimestamp(ts, tz=pytz.utc).astimezone(self.tz)
        return dt.strftime("%H:%M:%S PKT")

    def _utf16_length(self, s: str) -> int:
        """Return length in UTF-16 code units for a Python string."""
        # utf-16-le will produce 2 bytes per UTF-16 code unit (no BOM), so divide by 2
        return len(s.encode("utf-16-le")) // 2

    def _utf16_offset(self, text: str, char_index: int) -> int:
        """Return UTF-16 code unit offset for the position `char_index` (python string index)."""
        prefix = text[:char_index]
        return len(prefix.encode("utf-16-le")) // 2

    def format_signal_message(self, signal_data: Dict[str, Any]) -> Dict[str, Any]:
        """
        Returns a dict with 'text' and optional 'entities' to send via sendMessage.

        New Arabic layout with custom emojis for channel and pair as requested.
        Uses UTF-16-aware offsets so Telegram accepts entities reliably.
        """
        sig = signal_data["signal"]
        score = signal_data.get("composite_score", getattr(sig, "score", 0))
        entry_time_str = self._format_time(signal_data["intended_entry_time"]).replace(" PKT", "")

        # placeholders for custom emoji characters (each placeholder may be multi-code-unit)
        placeholder_channel = "😊"
        placeholder_pair = "🔹"

        text = (
            f"{placeholder_channel} قناة تداول كوتكس\n\n"
            f"{placeholder_pair} الزوج: {sig.symbol}\n\n"
            f"🎯(UTC 3+) نقطة الدخول: {entry_time_str} \n\n"
            f"🔴 الأتجاه: {sig.direction} ⬇️\n"
            f"📊 BT Score: {int(round(score))}/100\n"
            f"✅ M5/M1 Bearish Aligned\n"
            f"⚡️ Volatility: Optimal / Low Noise"
        )

        entities = []
        # compute python string index and convert to UTF-16 offsets
        try:
            pos_channel = text.index(placeholder_channel)
            offset_channel = self._utf16_offset(text, pos_channel)
            length_channel = self._utf16_length(placeholder_channel)
            entities.append({
                "type": "custom_emoji",
                "offset": offset_channel,
                "length": length_channel,
                "custom_emoji_id": str(self.emoji_channel_id),
            })
        except ValueError:
            logger.debug("Channel placeholder not found in text; skipping custom emoji entity for channel")

        try:
            pos_pair = text.index(placeholder_pair)
            offset_pair = self._utf16_offset(text, pos_pair)
            length_pair = self._utf16_length(placeholder_pair)
            entities.append({
                "type": "custom_emoji",
                "offset": offset_pair,
                "length": length_pair,
                "custom_emoji_id": str(self.emoji_pair_id),
            })
        except ValueError:
            logger.debug("Pair placeholder not found in text; skipping custom emoji entity for pair")

        return {"text": text, "entities": entities}

    def format_outcome_message(self, outcome_data: Dict[str, Any]) -> str:
        """
        Keep existing outcome formatting (unchanged).
        """
        sym = outcome_data["symbol"]
        dir_val = outcome_data["direction"]
        outcome = outcome_data["outcome"]
        entry_quote = outcome_data.get("entry_quote")
        expiry_quote = outcome_data.get("expiry_quote")

        wins_count = outcome_data.get("wins_count", 0)
        losses_count = outcome_data.get("losses_count", 0)
        win_rate = outcome_data.get("win_rate_percent", 0.0)

        is_call = dir_val == "CALL"
        sig_icon = "🟢" if is_call else "🔴"

        # Support martingale result labels (MTG_WIN / MTG_LOSS) and normal results
        if outcome == "WIN":
            res_str = "✅ WIN"
        elif outcome == "LOSS":
        elif outcome == "MTG_WIN":
            res_str = "🏆 MTG WIN"
        elif outcome == "LOSS" or outcome == "MTG_LOSS":
            # Treat MTG_LOSS same as LOSS (customize if you want a special label)
            res_str = "❌ LOSS"
        elif outcome == "DRAW":
            res_str = "⚖️ DRAW"
        else:
            res_str = "⚠️ UNVERIFIED"

        entry_str = f"{entry_quote:.5f}" if entry_quote is not None else "N/A"
        expiry_str = f"{expiry_quote:.5f}" if expiry_quote is not None else "N/A"

        text = (
            "🌪️ <b>BLACK TORNADO RESULT</b>\n"
            f"💱 <b>Pair:</b> <code>{sym}</code>\n"
            f"{sig_icon} <b>Signal:</b> {dir_val}\n"
            f"🏆 <b>Result:</b> {res_str}\n"
            f"📈 <b>Entry:</b> {entry_str}\n"
            f"📉 <b>Expiry:</b> {expiry_str}\n"
            f"✅ <b>Wins:</b> {wins_count} | ❌ <b>Losses:</b> {losses_count}\n"
            f"🎯 <b>Win Rate:</b> {int(round(win_rate))}%\n"
            "⚠️ <b>Result:</b> Feed-estimated\n"
            "━━━━━━━━━━━━"
        )
        return text

    async def send_message(self, text: str, entities: Optional[list] = None) -> bool:
        if not self.bot_token or not self.chat_id:
            logger.info(f"[DRY-RUN / NO BOT CREDENTIALS] Telegram message:\n{text}")
            return True

        url = f"https://api.telegram.org/bot{self.bot_token}/sendMessage"
        payload: Dict[str, Any] = {
            "chat_id": self.chat_id,
            "text": text,
            "disable_web_page_preview": True,
        }

        # If entities were provided (for custom emojis), attach them.
        if entities:
            payload["entities"] = entities

        try:
            async with aiohttp.ClientSession() as session:
                async with session.post(url, json=payload, timeout=aiohttp.ClientTimeout(total=5)) as resp:
                    if resp.status == 200:
                        return True
                    err = await resp.text()
                    logger.error(f"Telegram dispatch failed: HTTP {resp.status} - {err}")
                    return False
        except Exception as e:
            logger.error(f"Exception during Telegram broadcast: {e}")
            return False

    async def broadcast_signal(self, signal_data: Dict[str, Any]) -> bool:
        composed = self.format_signal_message(signal_data)
        return await self.send_message(composed["text"], entities=composed.get("entities"))

    async def broadcast_outcome(self, outcome_data: Dict[str, Any]) -> bool:
        text = self.format_outcome_message(outcome_data)
        if not self.bot_token or not self.chat_id:
            logger.info(f"[DRY-RUN / NO BOT CREDENTIALS] Telegram message:\n{text}")
            return True

        url = f"https://api.telegram.org/bot{self.bot_token}/sendMessage"
        payload = {
            "chat_id": self.chat_id,
            "text": text,
            "parse_mode": "HTML",
            "disable_web_page_preview": True,
        }

        try:
            async with aiohttp.ClientSession() as session:
                async with session.post(url, json=payload, timeout=aiohttp.ClientTimeout(total=5)) as resp:
                    if resp.status == 200:
                        return True
                    err = await resp.text()
                    logger.error(f"Telegram dispatch failed (outcome): HTTP {resp.status} - {err}")
                    return False
        except Exception as e:
            logger.error(f"Exception during Telegram broadcast (outcome): {e}")
            return False


telegram_notifier = TelegramNotifier()
