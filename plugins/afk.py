"""AFK / auto-secretary plugin.

.afk on [reason]  -> enable auto-reply in private chats
.afk off          -> disable, show how many people wrote
.afk              -> show status

Anti-spam: each user gets at most one reply per AFK_COOLDOWN seconds.
State lives in core.store ("afk") so the web panel can change it live.
"""
import logging
import time

from pyrogram import Client, filters
from pyrogram.types import Message

import config
from core import command, edit, on_message, safe_call, store

log = logging.getLogger("userbot.afk")
DEFAULT_REASON = "الان در دسترس نیستم، به‌زودی جواب می‌دم 🙏"

# Shared with web panel: {"on": bool, "reason": str, "since": epoch}
afk = store.get("afk", {"on": False, "reason": DEFAULT_REASON, "since": 0.0})
last_reply: dict[int, float] = {}  # user_id -> last auto-reply time (not persisted)
missed: set[int] = set()           # users who wrote while AFK


def set_afk(on: bool, reason: str | None = None) -> None:
    """Used by both the command and the panel."""
    afk["on"] = on
    if on:
        afk["since"] = time.time()
        afk["reason"] = reason or afk.get("reason") or DEFAULT_REASON
        last_reply.clear()
        missed.clear()
    store.save()


def _ago(ts: float) -> str:
    m = int(time.time() - ts) // 60
    return f"{m // 60} ساعت و {m % 60} دقیقه" if m >= 60 else f"{m} دقیقه"


@command("afk", "منشی خودکار پی‌وی: .afk on [متن] / .afk off")
async def afk_cmd(client: Client, message: Message):
    args = message.text.split(maxsplit=2)  # [".afk", "on", "reason..."]
    sub = args[1].lower() if len(args) > 1 else ""

    if sub == "on":
        set_afk(True, args[2] if len(args) > 2 else DEFAULT_REASON)
        await edit(message, f"💤 **منشی روشن شد**\nمتن: {afk['reason']}")
    elif sub == "off":
        was = _ago(afk["since"]) if afk["on"] else "۰ دقیقه"
        set_afk(False)
        await edit(message, f"👋 **منشی خاموش شد**\nمدت غیبت: {was}\nتعداد افرادی که پیام دادند: {len(missed)}")
    else:
        status = f"روشن ({_ago(afk['since'])})" if afk["on"] else "خاموش"
        await edit(message, f"وضعیت منشی: **{status}**\nاستفاده: `.afk on [متن]` / `.afk off`")


# Private, incoming, not from me, not from bots -> candidate for auto-reply.
# group=1 so it never blocks command handlers in group 0.
@on_message(filters.private & filters.incoming & ~filters.me & ~filters.bot, group=1)
async def afk_reply(client: Client, message: Message):
    if not afk["on"] or not message.from_user:
        return
    u = message.from_user
    if u.is_self or u.is_verified or u.id == 777000:
        return  # skip Telegram service account (login codes!) and verified accounts

    missed.add(u.id)
    now = time.time()
    if now - last_reply.get(u.id, 0) < config.AFK_COOLDOWN:
        return  # replied recently -> no spam
    last_reply[u.id] = now

    text = f"🤖 **پاسخ خودکار**\n{afk['reason']}\n\n__غایب از {_ago(afk['since'])} پیش__"
    try:  # smart reply when enabled in panel (plugins/ai.py); falls back to fixed text
        from plugins import ai
        if ai.cfg.get("afk_ai") and ai.ready():
            text = "🤖 " + await ai.afk_reply(message, afk["reason"])
    except Exception as e:
        log.warning("AI AFK reply failed, using fixed text: %s", e)
    await safe_call(message.reply_text, text, quote=True)
    log.info("AFK reply sent to %s", u.id)
