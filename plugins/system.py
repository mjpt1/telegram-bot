"""System plugin: .ping, .alive, .help"""
import platform
import random
import time

import pyrogram
from pyrogram import Client
from pyrogram.raw import functions
from pyrogram.types import Message

import config
from core import command, edit
from core.decorators import COMMANDS
from core.state import START_TIME  # set when the bot starts


def _fmt_uptime(seconds: float) -> str:
    """Turn seconds into '1d 2h 3m 4s'."""
    seconds = int(seconds)
    d, seconds = divmod(seconds, 86400)
    h, seconds = divmod(seconds, 3600)
    m, s = divmod(seconds, 60)
    parts = [f"{d}d"] if d else []
    parts += [f"{h}h", f"{m}m", f"{s}s"]
    return " ".join(parts)


@command("ping", "MTProto latency to Telegram servers")
async def ping(client: Client, message: Message):
    # 1) Raw MTProto ping: pure round-trip to the DC, no message logic
    t0 = time.perf_counter()
    await client.invoke(functions.Ping(ping_id=random.randint(0, 2**62)))
    rtt = (time.perf_counter() - t0) * 1000

    # 2) Edit round-trip: what you feel in the chat
    t1 = time.perf_counter()
    await edit(message, "🏓 ...")
    edit_ms = (time.perf_counter() - t1) * 1000

    await edit(message, f"🏓 **Pong!**\nMTProto RTT: `{rtt:.1f} ms`\nEdit RTT: `{edit_ms:.1f} ms`")


@command("alive", "Bot status, Python version, uptime")
async def alive(client: Client, message: Message):
    me = await client.get_me()
    text = (
        "✅ **Userbot is alive**\n"
        f"👤 Account: `{me.first_name}`\n"
        f"🐍 Python: `{platform.python_version()}`\n"
        f"📦 Pyrogram: `{pyrogram.__version__}`\n"
        f"💻 System: `{platform.system()} {platform.release()}`\n"
        f"⏱ Uptime: `{_fmt_uptime(time.time() - START_TIME)}`"
    )
    await edit(message, text)


@command("help", "List all commands")
async def help_cmd(client: Client, message: Message):
    p = config.CMD_PREFIXES[0]
    lines = [f"`{p}{name}` - {desc}" for name, desc in sorted(COMMANDS.items())]
    await edit(message, "📖 **Commands**\n" + "\n".join(lines))
