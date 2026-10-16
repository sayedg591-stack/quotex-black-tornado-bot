"""Performance metrics, strategy reporting, and kill-switch control."""
from fastapi import APIRouter
from app.config import settings
from app.database.repository import DatabaseRepository

router = APIRouter(tags=["Statistics & Control"])
_repo = DatabaseRepository()


@router.get("/stats")
async def get_performance_stats():
    """Honest statistical metrics (Win Rate, Total Signals, Wins, Losses, Draws)."""
    try:
        stats = await _repo.get_cumulative_stats()
        return stats
    except Exception as e:
        # Return a safe error payload so UI / caller sees the failure reason
        return {"error": "failed to fetch stats", "details": str(e)}


@router.post("/kill-switch/toggle")
async def toggle_kill_switch():
    """Pause or resume new signal dispatches safely."""
    settings.KILL_SWITCH_ACTIVE = not settings.KILL_SWITCH_ACTIVE
    return {
        "kill_switch_active": settings.KILL_SWITCH_ACTIVE,
        "message": "Signal dispatch paused" if settings.KILL_SWITCH_ACTIVE else "Signal dispatch resumed"
    }
