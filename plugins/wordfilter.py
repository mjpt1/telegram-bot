"""Bad-word filter for groups where you are admin (delete permission needed).

.filter on / .filter off      -> enable/disable in this group
.filter add کلمه               -> add a word (applies to all enabled groups)
.filter del کلمه / .filter list
Also editable from the web panel.
"""
import logging
import re

from pyrogram import Client, filters
from pyrogram.types import Message

from core import args_text, command, edit, on_message, safe_call, store

log = logging.getLogger("userbot.filter")
cfg = store.get("wordfilter", {"words": [], "chats": [], "warn": True})

# Normalize Arabic/Persian letter variants and remove zero-width chars
_NORM = str.maketrans({"ي": "ی", "ك": "ک", "ة": "ه", "‌": "", "‍": ""})


def _norm(text: str) -> str:
    return re.sub(r"\s+", " ", text.translate(_NORM).lower())


def matches(text: str) -> str | None:
    t = _norm(text)
    for w in cfg["words"]:
        if _norm(w) in t:
            return w
    return None


@command("filter", "فیلتر کلمات گروه: .filter on|off|add|del|list")
async def filter_cmd(client: Client, message: Message):
    parts = args_text(message).split(maxsplit=1)
    sub = parts[0] if parts else "list"
    cid = str(message.chat.id)
    if sub == "on":
        if cid not in cfg["chats"]:
            cfg["chats"].append(cid)
        msg = "✅ فیلتر در این گروه روشن شد."
    elif sub == "off":
        cfg["chats"] = [c for c in cfg["chats"] if c != cid]
        msg = "❌ فیلتر در این گروه خاموش شد."
    elif sub == "add" and len(parts) > 1:
        cfg["words"].extend(w for w in parts[1].split() if w not in cfg["words"])
        msg = f"➕ اضافه شد: {parts[1]}"
    elif sub == "del" and len(parts) > 1:
        cfg["words"] = [w for w in cfg["words"] if w not in parts[1].split()]
        msg = f"➖ حذف شد: {parts[1]}"
    else:
        on = "روشن" if cid in cfg["chats"] else "خاموش"
        words = "، ".join(cfg["words"]) or "خالی"
        return await edit(message, f"🚫 فیلتر این چت: **{on}**\nکلمات: {words}")
    store.save()
    await edit(message, msg)


@on_message(filters.group & filters.incoming & ~filters.me & (filters.text | filters.caption), group=6)
async def check(client: Client, message: Message):
    if str(message.chat.id) not in cfg["chats"] or not cfg["words"]:
        return
    word = matches(message.text or message.caption or "")
    if not word:
        return
    try:
        await safe_call(message.delete)
    except Exception as e:
        log.warning("Cannot delete in %s (admin?): %s", message.chat.id, e)
        return
    log.info("Filtered message in %s (word=%s)", message.chat.id, word)
