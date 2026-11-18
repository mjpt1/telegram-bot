"""Rotating / live bio.

Settings in store "autobio" (panel tab "پروفایل"):
  on       -> enabled
  texts    -> list of bios; one is used per turn, in order
  interval -> minutes between changes (min 5, Telegram limits profile edits)
Placeholders: {time} {date} (Tehran, Persian digits). Bio max 70 chars.
"""
import asyncio
import datetime as dt
import logging

import jdatetime
from pyrogram import Client

from core import safe_call, store
from plugins.texttools import FA_DIGITS, TEHRAN

log = logging.getLogger("userbot.autobio")
cfg = store.get("autobio", {"on": False, "texts": [], "interval": 30})


def render(text: str) -> str:
    now = dt.datetime.now(TEHRAN)
    jd = jdatetime.datetime.fromgregorian(datetime=now)
    out = text.replace("{time}", now.strftime("%H:%M")).replace("{date}", jd.strftime("%Y/%m/%d"))
    return out.translate(FA_DIGITS)[:70]


async def on_start(client: Client):
    i = 0
    while True:
        wait = max(5, int(cfg.get("interval") or 30)) * 60
        if cfg.get("on") and cfg.get("texts"):
            text = render(cfg["texts"][i % len(cfg["texts"])])
            i += 1
            try:
                await safe_call(client.update_profile, bio=text)
                log.info("bio set: %s", text)
            except Exception as e:
                log.warning("bio update failed: %s", e)
            await asyncio.sleep(wait)
        else:
            await asyncio.sleep(30)
