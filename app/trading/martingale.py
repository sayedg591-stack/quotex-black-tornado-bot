import json
import logging
from typing import Optional, Dict, Any
from app.config import settings
from app.database.repository import DatabaseRepository

logger = logging.getLogger(__name__)


class MartingaleManager:
    """Simple martingale manager implementing 2^n stake progression and automated recovery signal creation."""

    def __init__(self, repo: DatabaseRepository):
        self.repo = repo
        self.enabled = settings.MARTINGALE_ENABLED
        self.base_stake = float(settings.MARTINGALE_BASE_STAKE)
        self.max_steps = int(settings.MARTINGALE_MAX_STEPS)
        self.max_stake = float(settings.MARTINGALE_MAX_STAKE)
        self.mode = settings.MARTINGALE_MODE

    def next_stake(self, step: int) -> float:
        """Compute the stake for a given martingale step (0-based)."""
        stake = self.base_stake * (2 ** step)
        if stake > self.max_stake:
            return self.max_stake
        return stake

    async def handle_loss(self, parent_signal: Dict[str, Any]) -> Optional[str]:
        """
        Called when a primary signal resolves with LOSS. This will:
        - read parent details_json for current mtg step
        - if within limits, create a recovery signal (MTG step +1) with computed stake
        - mark parent as PENDING_RECOVERY (so global ACTIVE lock is released)
        Returns the new recovery signal_id or None if not created.
        """
        if not self.enabled:
            return None

        try:
            parent_id = parent_signal.get("signal_id") if isinstance(parent_signal, dict) else getattr(parent_signal, "signal_id", None)
            symbol = parent_signal.get("symbol") if isinstance(parent_signal, dict) else getattr(parent_signal, "symbol", None)
            direction = parent_signal.get("direction") if isinstance(parent_signal, dict) else getattr(parent_signal, "direction", None)

            # read existing details
            details_json = None
            if isinstance(parent_signal, dict):
                details_json = parent_signal.get("details_json")
            else:
                details_json = getattr(parent_signal, "details_json", None)

            try:
                details = json.loads(details_json or "{}")
            except Exception:
                details = {}

            mtg = details.get("mtg", {})
            step = int(mtg.get("step", 0))
            base = float(mtg.get("base_stake", self.base_stake))

            next_step = step + 1
            if next_step > self.max_steps:
                logger.info(f"Martingale max steps reached for {parent_id}; not creating recovery signal.")
                return None

            stake = self.next_stake(next_step)

            # prepare recovery signal payload
            recovery_id = f"{parent_id}_MTG{next_step}"
            now_ts = int(time.time())
            intended_entry = now_ts + settings.SIGNAL_LEAD_SECONDS + 2
            intended_expiry = intended_entry + settings.EXPIRY_SECONDS

            recovery_details = {
                "parent": parent_id,
                "mtg": {"step": next_step, "base_stake": base, "stake": stake}
            }

            created = await self.repo.acquire_signal_lock_and_create(
                signal_id=recovery_id,
                symbol=symbol,
                direction=direction,
                strategy_name=f"MTG_RECOVERY_{parent_id}",
                setup_score=0.0,
                signal_sent_time=now_ts,
                intended_entry_time=intended_entry,
                intended_expiry_time=intended_expiry,
                signal_price=None,
                details=recovery_details,
            )

            if created:
                # mark parent pending recovery (merge a flag into details_json)
                await self.repo.mark_signal_pending_recovery(parent_id, {"mtg_pending": True, "mtg_step": next_step})
                logger.info(f"Created martingale recovery {recovery_id} for parent {parent_id} stake={stake}")
                return recovery_id
            else:
                logger.warning(f"Failed to create recovery signal {recovery_id} for parent {parent_id}")
                return None

        except Exception as e:
            logger.error(f"Martingale handle_loss error: {e}")
            return None

    async def finalize(self, parent_signal_id: str, mtg_outcome: str, info: Optional[Dict[str, Any]] = None) -> bool:
        """
        Finalize parent signal with an MTG outcome ("MTG_WIN" / "MTG_LOSS").
        This will create an OutcomeRecord for the parent and mark it RESOLVED.
        """
        try:
            # Create outcome data and use repository.resolve_signal to persist
            outcome_data = {
                "outcome": mtg_outcome,
                "entry_quote": info.get("entry_quote") if info else None,
                "expiry_quote": info.get("expiry_quote") if info else None,
                "price_delta": info.get("price_delta") if info else None,
                "is_verified": info.get("is_verified", False) if info else False,
                "reason": info.get("reason") if info else "MTG Resolution",
                "evaluated_at": int(time.time()),
            }
            res = await self.repo.resolve_signal(parent_signal_id, outcome_data)
            return res is not None
        except Exception as e:
            logger.error(f"Martingale finalize error for {parent_signal_id}: {e}")
            return False
