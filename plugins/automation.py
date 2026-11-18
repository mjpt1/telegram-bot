"""Automation: keyword auto-replies, scheduled messages, channel forwarding.

All rules live in core.store and are editable from the web panel too.

.ar add کلمه | پاسخ     -> auto-reply when someone writes the keyword
.ar list / .ar del <n>
.sched <minutes> <text>  -> send text to this chat after N minutes
.sched list
"""
import asyncio
import logging
import secrets
import time

from pyrogram import Client, filters
from pyrogram.types import Message

from core import args_text, chat_ref, command, edit, on_message, safe_call, store

log = logging.getLogger("userbot.auto")

# Each item has an "id" so the panel can delete it
autoreplies: list = store.get("autoreplies", [])  # {id, keyword, reply, exact, scope: private|all}
schedules: list = store.get("schedules", [])      # {id, chat, text, at: epoch, repeat: seconds|0}
forwards: list = store.get("forwards", [])        # {id, source, target}

COOLDOWN = 60  # seconds between replies of the same rule in the same chat
_last: dict[tuple, float] = {}


def new_id() -> str:
    return secrets.token_hex(4)


# ---------- keyword auto-replies ----------
@command("ar", "پاسخ خودکار: .ar add کلمه | پاسخ  /  .ar list  /  .ar del 1")
async def ar_cmd(client: Client, message: Message):
    parts = args_text(message).split(maxsplit=1)
    sub = parts[0] if parts else "list"
    if sub == "add" and len(parts) > 1 and "|" in parts[1]:
        kw, reply = (x.strip() for x in parts[1].split("|", 1))
        autoreplies.append({"id": new_id(), "keyword": kw, "reply": reply, "exact": False, "scope": "private"})
        store.save()
        return await edit(message, f"✅ اضافه شد: `{kw}` ← {reply}")
    if sub == "del" and len(parts) > 1 and parts[1].isdigit():
        i = int(parts[1]) - 1
        if 0 <= i < len(autoreplies):
            item = autoreplies.pop(i)
            store.save()
            return await edit(message, f"🗑 حذف شد: `{item['keyword']}`")
        return await edit(message, "شماره نامعتبر است.")
    if not autoreplies:
        return await edit(message, "هیچ پاسخ خودکاری ثبت نشده.\n`.ar add سلام | سلام، خوبی؟`")
    lines = [f"{i}. `{r['keyword']}` ← {r['reply']}" for i, r in enumerate(autoreplies, 1)]
    await edit(message, "🤖 **پاسخ‌های خودکار:**\n" + "\n".join(lines))


@on_message(filters.incoming & ~filters.me & ~filters.bot & filters.text, group=3)
async def auto_reply(client: Client, message: Message):
    if not autoreplies:
        return
    text = message.text.lower().strip()
    for rule in autoreplies:
        if rule.get("scope", "private") == "private" and message.chat.type.name != "PRIVATE":
            continue
        kw = rule["keyword"].lower()
        if (text == kw) if rule.get("exact") else (kw in text):
            key = (message.chat.id, rule["id"])
            if time.time() - _last.get(key, 0) < COOLDOWN:
                return  # no spam
            _last[key] = time.time()
            await safe_call(message.reply_text, rule["reply"], quote=True)
            return  # one reply per message


# ---------- scheduled messages ----------
@command("sched", "ارسال زمان‌بندی‌شده: .sched 30 متن  (۳۰ دقیقه بعد)")
async def sched_cmd(client: Client, message: Message):
    parts = args_text(message).split(maxsplit=1)
    if parts and parts[0] == "list":
        if not schedules:
            return await edit(message, "پیام زمان‌بندی‌شده‌ای نیست.")
        lines = [f"• {int((s['at'] - time.time()) // 60)} دقیقه دیگر ← `{s['chat']}`: {s['text'][:40]}"
                 for s in schedules]
        return await edit(message, "⏰ **صف ارسال:**\n" + "\n".join(lines))
    if len(parts) < 2 or not parts[0].isdigit():
        return await edit(message, "استفاده: `.sched 30 متن پیام`")
    schedules.append({"id": new_id(), "chat": str(message.chat.id), "text": parts[1],
                      "at": time.time() + int(parts[0]) * 60})
    store.save()
    await edit(message, f"⏰ ثبت شد. {parts[0]} دقیقه دیگر ارسال می‌شود.")


async def on_start(client: Client):
    """Scheduler loop: send due messages every 15s."""
    while True:
        now = time.time()
        for item in [s for s in schedules if s["at"] <= now]:
            try:
                await safe_call(client.send_message, chat_ref(item["chat"]), item["text"])
                log.info("Scheduled message sent to %s", item["chat"])
            except Exception:
                log.exception("Scheduled send failed for %s", item["chat"])
            if item.get("repeat"):  # repeating: move to the next future slot
                while item["at"] <= now:
                    item["at"] += item["repeat"]
            else:
                schedules.remove(item)
            store.save()
        await asyncio.sleep(15)


# ---------- forwarding (copy) from source chat to target chat ----------
def _is_source(_, __, message: Message) -> bool:
    cid = str(message.chat.id) if message.chat else ""
    return any(str(f["source"]) == cid for f in forwards)


@on_message(filters.create(_is_source), group=4)
async def forwarder(client: Client, message: Message):
    for rule in forwards:
        if str(rule["source"]) == str(message.chat.id):
            await safe_call(message.copy, chat_ref(rule["target"]))
            await asyncio.sleep(1)  # gentle pace between targets
