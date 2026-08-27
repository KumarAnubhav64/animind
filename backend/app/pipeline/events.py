"""Per-project pub/sub for SSE progress events."""

import asyncio
from collections import defaultdict, deque

_subscribers: dict[str, set[asyncio.Queue]] = defaultdict(set)
_history: dict[str, deque[dict]] = defaultdict(lambda: deque(maxlen=250))


def subscribe(project_id: str) -> asyncio.Queue:
    q: asyncio.Queue = asyncio.Queue()
    _subscribers[project_id].add(q)
    return q


def unsubscribe(project_id: str, q: asyncio.Queue):
    _subscribers[project_id].discard(q)


def history(project_id: str) -> list[dict]:
    return list(_history.get(project_id, ()))


async def publish(project_id: str, event: dict):
    _history[project_id].append(event)
    for q in list(_subscribers.get(project_id, ())):
        await q.put(event)
