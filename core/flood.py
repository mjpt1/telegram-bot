"""FloodWait handling with exponential backoff.

Telegram returns FLOOD_WAIT_X when we go too fast. Ignoring it, or retrying
instantly, is what gets accounts limited. safe_call() sleeps the exact time
Telegram asks plus a growing safety margin, then retries.
"""
import asyncio
import logging
import random
from typing import Any, Awaitable, Callable

from pyrogram.errors import FloodWait

log = logging.getLogger(__name__)

MAX_RETRIES = 5
MAX_WAIT = 3600  # never sleep longer than 1h for one call; give up instead


async def safe_call(func: Callable[..., Awaitable[Any]], *args, retries: int = MAX_RETRIES, **kwargs) -> Any:
    """Await func(*args, **kwargs); on FloodWait sleep + backoff, then retry."""
    for attempt in range(1, retries + 1):
        try:
            return await func(*args, **kwargs)
        except FloodWait as e:
            wait = int(e.value)  # seconds required by Telegram
            if wait > MAX_WAIT or attempt == retries:
                log.error("FloodWait %ss on %s (attempt %d) - giving up", wait, func.__name__, attempt)
                raise
            # Backoff margin 1s, 2s, 4s... plus jitter so parallel tasks don't retry together
            margin = (2 ** (attempt - 1)) + random.uniform(0, 1)
            log.warning("FloodWait %ss on %s, sleeping %.1fs (attempt %d/%d)",
                        wait, func.__name__, wait + margin, attempt, retries)
            await asyncio.sleep(wait + margin)
