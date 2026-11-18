"""Tiny in-process event bus for live panel notifications (Server-Sent Events).

Plugins call publish({...}); every open panel tab has a queue in SUBSCRIBERS.
"""
import asyncio

SUBSCRIBERS: set[asyncio.Queue] = set()


def publish(event: dict) -> None:
    for q in list(SUBSCRIBERS):
        if q.qsize() < 100:  # a stuck tab never grows memory forever
            q.put_nowait(event)
