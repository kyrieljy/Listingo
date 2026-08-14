from __future__ import annotations

import asyncio
from contextlib import asynccontextmanager
from dataclasses import dataclass
from typing import AsyncIterator


@dataclass
class _LimiterState:
    capacity: int
    semaphore: asyncio.Semaphore
    active: int = 0


_state: _LimiterState | None = None


def get_provider_limiter(capacity: int) -> _LimiterState:
    global _state
    normalized = max(1, int(capacity))
    if _state is None or _state.capacity != normalized:
        _state = _LimiterState(capacity=normalized, semaphore=asyncio.Semaphore(normalized))
    return _state


@asynccontextmanager
async def provider_slot(capacity: int) -> AsyncIterator[None]:
    state = get_provider_limiter(capacity)
    await state.semaphore.acquire()
    state.active += 1
    try:
        yield
    finally:
        state.active -= 1
        state.semaphore.release()
