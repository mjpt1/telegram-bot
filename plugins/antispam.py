"""Anti-spam for groups where you are admin.

Settings in store "antispam" (panel tab "ضداسپم"):
  chats    -> list of chat ids (str) where it is active
  links    -> delete messages with links / @usernames / t.me
  forwards -> delete forwarded messages
  flood    -> max messages per user in 10 s (0 = off); offender is muted 1 hour

Admins of the group are never touched. Admin lists are cached 10 minutes.
.antispam on|off   -> enable / disable in current group
"""
import datetime as dt
import logging
import re
import time
from collections import defaultdict, deque

from pyrogram import Client, enums, filters
from pyrogram.types import ChatPermissions, Message

from core import args_text, command, edit, on_message, safe_call, store

log = logging.getLogger("userbot.antispam")
cfg = store.get("antispam", {"chats": [], "links": True, "forwards": True, "flood": 6})
LINK = re.compile(r"(https?://|www\.|t\.me/|telegram\.me/|@\w{4,})", re.I)
_admins: dict[int, tuple[float, set]] = {}
_recent: dict[tuple, deque] = defaultdict(lambda: deque(maxlen=30))


async def _admin_ids(client: Client, chat_id: int) -> set:
    at, ids = _admins.get(chat_id, (0, set()))
    if time.time() - at > 600:
        ids = {m.user.id async for m in client.get_chat_members(chat_id, filter=enums.ChatMembersFilter.ADMINISTRATORS)
               if m.user}
        _admins[chat_id] = (time.time(), ids)
    return ids


def _active(_, __, m: Message) -> bool:
    return bool(m.chat) and str(m.chat.id) in cfg["chats"]


@command("antispam", "ضداسپم گروه: .antispam on / off")
async def antispam_cmd(client: Client, message: Message):
    sub, key = args_text(message).strip().lower(), str(message.chat.id)
    if sub == "on":
        if key not in cfg["chats"]:
            cfg["chats"].append(key)
        store.save()
        return await edit(message, "🛡 ضداسپم در این گروه روشن شد.")
    if sub == "off":
        if key in cfg["chats"]:
            cfg["chats"].remove(key)
        store.save()
        return await edit(message, "ضداسپم خاموش شد.")
    await edit(message, f"ضداسپم اینجا: **{'روشن' if key in cfg['chats'] else 'خاموش'}**\n`.antispam on` / `.antispam off`")


@on_message(filters.group & filters.incoming & ~filters.me & filters.create(_active), group=6)
async def guard(client: Client, message: Message):
    u = message.from_user
    if not u or u.id in await _admin_ids(client, message.chat.id):
        return
    text = message.text or message.caption or ""
    reason = None
    if cfg.get("forwards") and (message.forward_date or message.forward_from_chat):
        reason = "forward"
    elif cfg.get("links") and LINK.search(text):
        reason = "link"

    limit = int(cfg.get("flood") or 0)
    if limit:
        q = _recent[(message.chat.id, u.id)]
        q.append(time.time())
        if len([t for t in q if time.time() - t < 10]) > limit:
            q.clear()
            try:
                await safe_call(client.restrict_chat_member, message.chat.id, u.id, ChatPermissions(),
                                until_date=dt.datetime.now() + dt.timedelta(hours=1))
                log.info("flood mute %s in %s", u.id, message.chat.id)
            except Exception as e:
                log.warning("mute failed: %s", e)
            reason = reason or "flood"

    if reason:
        try:
            await safe_call(message.delete)
        except Exception as e:
            log.warning("delete failed in %s: %s", message.chat.id, e)
