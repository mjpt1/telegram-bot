"""Run once locally to create a SESSION_STRING. Keep the output secret."""
import asyncio

from pyrogram import Client

import config


async def run():
    async with Client("gen", api_id=config.API_ID, api_hash=config.API_HASH, in_memory=True) as app:
        s = await app.export_session_string()
        await app.send_message("me", f"SESSION_STRING (secret, never share):\n`{s}`")
        print("\nSession string sent to your Saved Messages. Put it in .env as SESSION_STRING.")


asyncio.run(run())
