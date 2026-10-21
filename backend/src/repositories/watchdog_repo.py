from datetime import UTC, datetime, timedelta

from sqlalchemy.ext.asyncio import AsyncSession

from src.models.watchdog import WATCHDOG_STATE_ID, WatchdogState


class WatchdogRepository:
    """Состояние watchdog'а: время последнего прохода."""

    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def get_last_run_at(self) -> datetime | None:
        state = await self.session.get(WatchdogState, WATCHDOG_STATE_ID)
        return state.last_run_at if state else None

    async def should_run(self, interval_seconds: int) -> bool:
        """True, если с прошлого прохода прошло не меньше интервала."""
        last_run = await self.get_last_run_at()
        if last_run is None:
            return True
        return datetime.now(UTC) - last_run >= timedelta(seconds=interval_seconds)

    async def mark_run(self) -> None:
        state = await self.session.get(WatchdogState, WATCHDOG_STATE_ID)
        if state is None:
            state = WatchdogState(id=WATCHDOG_STATE_ID)
            self.session.add(state)
        state.last_run_at = datetime.now(UTC)
        await self.session.flush()
