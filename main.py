"""Userbot entry point: config -> logging -> client -> plugins -> panel -> idle."""
import asyncio
import logging

from pyrogram import Client, idle

import config
from core import state
from core.loader import load_plugins
from core.logger import setup_logging

setup_logging(config.LOG_LEVEL, config.LOG_FILE)
log = logging.getLogger("userbot")


def build_client() -> Client:
    common = dict(
        api_id=config.API_ID,
        api_hash=config.API_HASH,
        workdir=str(config.SESSIONS_DIR),
        sleep_threshold=60,  # Pyrogram itself auto-sleeps FloodWaits <= 60s
        proxy=config.PROXY,  # None = direct connection
    )
    if config.PROXY:
        log.info("Using proxy %s://%s:%s", config.PROXY["scheme"], config.PROXY["hostname"], config.PROXY["port"])
    if config.SESSION_STRING:
        return Client(config.SESSION_NAME, session_string=config.SESSION_STRING, in_memory=True, **common)
    # File session: asks phone + code on first run, then reuses sessions/<name>.session
    return Client(config.SESSION_NAME, **common)


async def main() -> None:
    app = build_client()
    hooks = load_plugins(app, config.PLUGINS_DIR)
    await app.start()
    me = await app.get_me()
    log.info("Logged in as %s (id=%s). Plugins: %s. Prefix: %s",
             me.first_name, me.id, ", ".join(state.PLUGINS), " ".join(config.CMD_PREFIXES))

    # Background tasks from plugins (scheduler, clock, ...)
    tasks = [asyncio.create_task(h(app)) for h in hooks]

    runner = None
    if config.PANEL_PASSWORD:
        from web.server import start_panel
        runner = await start_panel(app)
    else:
        log.info("Web panel disabled (set PANEL_PASSWORD in .env to enable)")

    await idle()  # block until Ctrl+C / SIGTERM

    for t in tasks:
        t.cancel()
    if runner:
        await runner.cleanup()
    await app.stop()
    log.info("Stopped cleanly")


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        pass
