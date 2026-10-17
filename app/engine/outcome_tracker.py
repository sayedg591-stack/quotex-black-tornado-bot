"""Settlement engine tracking 1-minute expiry prices and calculating honest outcomes."""
import time
import logging
from typing import Dict, Any, Optional, Any as AnyType
from app.config import settings
from app.feed.candle_store import candle_store
from app.database.repository import DatabaseRepository
from app.notifications.telegram import telegram_notifier
from app.trading.martingale import MartingaleManager

logger = logging.getLogger(__name__)


class OutcomeTracker:
    def __init__(self, db_repo: DatabaseRepository):
        self.db = db_repo
        # instantiate martingale manager for automated recovery handling
        self.mtg = MartingaleManager(db_repo)

    def _get_field(self, obj: AnyType, *keys, default=None):
        """Helper to retrieve a value from either a mapping or an ORM object.
        Checks keys in order and returns the first found value; otherwise default.
        """
        # Mapping-like access
        try:
            if isinstance(obj, dict):
                for k in keys:
                    if k in obj:
                        return obj[k]
                return default
        except Exception:
            pass

        # Attribute access for ORM objects
        for k in keys:
            if hasattr(obj, k):
                return getattr(obj, k)
        return default

    async def settle_signal(self, active_sig: Dict[str, Any]) -> bool:
        """
        Evaluate candle prices for entry and expiry, record result, and broadcast.
        Accepts either a dict-like active_sig (legacy) or an ORM SignalRecord instance.
        """
        sig_id = self._get_field(active_sig, "signal_id", "id")
        symbol = self._get_field(active_sig, "symbol")
        direction = self._get_field(active_sig, "direction")
        entry_ts = self._get_field(active_sig, "intended_entry_time", "entry_time")
        expiry_ts = self._get_field(active_sig, "intended_expiry_time", "expiry_time")

        now_ts = int(time.time())
        # Check if enough time has passed (expiry time + small buffer for feed to settle)
        if expiry_ts is None or now_ts < (expiry_ts + 2):
            return False  # not ready to settle yet

        # Retrieve closed candles for this pair
        candles = candle_store.get_closed_candles(symbol, limit=20)
        candle_map = {c["time"]: c for c in candles}

        entry_candle = candle_map.get(entry_ts)
        expiry_candle = candle_map.get(expiry_ts)

        # Fallback to last recorded quotes if exact candle boundary is missing
        entry_quote: Optional[float] = None
        expiry_quote: Optional[float] = None
        outcome = "UNVERIFIED"
        reason = None
        delta: Optional[float] = None
        verified = False

        if entry_candle:
            entry_quote = entry_candle.get("open")
        else:
            entry_quote = self._get_field(active_sig, "signal_price", "entry_price_est")

        # Prefer explicit expiry candle when available
        if expiry_candle:
            expiry_quote = expiry_candle.get("open")
        elif entry_candle:
            # Fallback behavior: use the close of the entry candle if that's all we have
            expiry_quote = entry_candle.get("close")

        if entry_quote is not None and expiry_quote is not None:
            delta = expiry_quote - entry_quote
            verified = True

            if abs(delta) < 1e-6:
                outcome = "DRAW"
                reason = "Entry and Expiry prices were identical"
            elif direction == "CALL":
                if delta > 0:
                    outcome = "WIN"
                    reason = f"Bullish close: +{delta:.5f}"
                else:
                    outcome = "LOSS"
                    reason = f"Bearish close: {delta:.5f}"
            elif direction == "PUT":
                if delta < 0:
                    outcome = "WIN"
                    reason = f"Bearish close: {delta:.5f}"
                else:
                    outcome = "LOSS"
                    reason = f"Bullish close: +{delta:.5f}"
        else:
            outcome = "UNVERIFIED"
            reason = "Missing reliable tick/candle feed observation at settlement time"

        logger.info(f"Settling signal #{sig_id} ({symbol} {direction}): {outcome} (Entry={entry_quote}, Expiry={expiry_quote})")

        # Prepare outcome payload for DB call (repository.resolve_signal expects signal_id + outcome_data dict)
        outcome_data = {
            "outcome": outcome,
            "entry_quote": entry_quote,
            "expiry_quote": expiry_quote,
            "price_delta": delta,
            "is_verified": verified,
            "reason": reason,
            "evaluated_at": now_ts,
        }

        # Determine if this signal is a martingale recovery (has parent)
        details_json = self._get_field(active_sig, "details_json")
        parent_id = None
        try:
            details = json.loads(details_json) if details_json else {}
            parent_id = details.get("parent")
        except Exception:
            details = {}
            parent_id = None

        # If this is a primary signal that LOST, we DO NOT finalize it here.
        # Instead, create an MTG recovery attempt and mark the parent PENDING_RECOVERY.
        if outcome == "LOSS" and not parent_id:
            # create recovery and mark parent pending; do not broadcast now
            created = await self.mtg.handle_loss(active_sig)
            if created:
                logger.info(f"Parent {sig_id} marked for MTG recovery (created {created}); deferring final outcome broadcast")
                return True
            else:
                # if for some reason recovery wasn't created, we fallback to resolving as LOSS
                await self.db.resolve_signal(sig_id, outcome_data)
                # broadcast regular LOSS
        else:
            # For all other cases (WIN, DRAW, UNVERIFIED) OR for recovery signals, persist the result
            await self.db.resolve_signal(sig_id, outcome_data)

        # If this was a recovery signal with a parent, we should finalize the parent's outcome accordingly
        if parent_id:
            # parent exists -> this was a recovery attempt
            # If recovery won, parent is MTG_WIN; otherwise parent is LOSS
            if outcome == "WIN":
                parent_outcome = "MTG_WIN"
            else:
                parent_outcome = "LOSS"

            # finalize parent via martingale manager (this will resolve parent and insert outcome)
            ok = await self.mtg.finalize(parent_id, parent_outcome, info={
                "entry_quote": outcome_data.get("entry_quote"),
                "expiry_quote": outcome_data.get("expiry_quote"),
                "price_delta": outcome_data.get("price_delta"),
                "is_verified": outcome_data.get("is_verified", False),
                "reason": f"MTG resolution from {sig_id}",
            })

            if ok:
                # broadcast final parent outcome
                stats = await self.db.get_cumulative_stats()
                wins_count = stats.get("wins", 0)
                losses_count = stats.get("losses", 0)
                win_rate = stats.get("win_rate", 0.0)

                outcome_payload = {
                    "signal_id": parent_id,
                    "symbol": symbol,
                    "direction": direction,
                    "outcome": parent_outcome,
                    "entry_quote": outcome_data.get("entry_quote"),
                    "expiry_quote": outcome_data.get("expiry_quote"),
                    "price_delta": outcome_data.get("price_delta"),
                    "strategy_name": details.get("strategy_name", self._get_field(active_sig, "strategy_name", default="Black Tornado")),
                    "intended_entry_time": entry_ts,
                    "intended_expiry_time": expiry_ts,
                    "wins_count": wins_count,
                    "losses_count": losses_count,
                    "win_rate_percent": win_rate,
                }
                await telegram_notifier.broadcast_outcome(outcome_payload)
                return True
            else:
                logger.error(f"Failed to finalize parent MTG for {parent_id}")
                return True

        # For non-parent signals that were finalized above, broadcast normal outcome
        stats = await self.db.get_cumulative_stats()
        wins_count = stats.get("wins", 0)
        losses_count = stats.get("losses", 0)
        win_rate = stats.get("win_rate", 0.0)

        outcome_payload = {
            "signal_id": sig_id,
            "symbol": symbol,
            "direction": direction,
            "outcome": outcome,
            "entry_quote": entry_quote,
            "expiry_quote": expiry_quote,
            "price_delta": delta,
            "strategy_name": self._get_field(active_sig, "strategy_name", default="Black Tornado"),
            "intended_entry_time": entry_ts,
            "intended_expiry_time": expiry_ts,
            "wins_count": wins_count,
            "losses_count": losses_count,
            "win_rate_percent": win_rate,
        }
        await telegram_notifier.broadcast_outcome(outcome_payload)
        return True
