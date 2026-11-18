"""Activity counters (in memory, since last start) and .stats command.

Counts messages you send and receive per chat type. The panel dashboard
reads `counters` and calls `dialog_stats()` for account-wide numbers.
"""
import time
from collections import Counter

from pyrogram import Client, filters
from pyrogram.types import Message

from core import command, edit, on_message
from core.chatops import list_chats

counters = {"sent": 0, "received": 0, "by_type": Counter(), "by_chat": Counter(), "titles": {}}


@on_message(filters.all, group=99)  # last group: never interferes with other handlers
async def count(client: Client, message: Message):
    if not message.chat:
        return
    counters["sent" if message.outgoing else "received"] += 1
    counters["by_type"][message.chat.type.name.lower()] += 1
    counters["by_chat"][message.chat.id] += 1
    counters["titles"][message.chat.id] = message.chat.title or message.chat.first_name or str(message.chat.id)


async def dialog_stats(client: Client) -> dict:
    """Count dialogs by type + unread, from the shared 5-minute dialog cache."""
    chats = await list_chats(client)
    types = Counter(c["type"] for c in chats)
    return {"types": dict(types), "total": len(chats), "unread": sum(c["unread"] for c in chats)}


def top_chats(n: int = 5) -> list:
    return [{"id": cid, "title": counters["titles"].get(cid, str(cid)), "count": c}
            for cid, c in counters["by_chat"].most_common(n)]


@command("stats", "آمار اکانت و فعالیت از زمان روشن شدن")
async def stats(client: Client, message: Message):
    await edit(message, "⏳ در حال شمارش چت‌ها...")
    d = await dialog_stats(client)
    t = d["types"]
    top = "\n".join(f"  {i}. {c['title']} — {c['count']}" for i, c in enumerate(top_chats(), 1)) or "  -"
    await edit(message, (
        "📊 **آمار**\n"
        f"کل چت‌ها: {d['total']}\n"
        f"👤 شخصی: {t.get('private', 0)}  🤖 ربات: {t.get('bot', 0)}\n"
        f"👥 گروه: {t.get('group', 0) + t.get('supergroup', 0)}  📢 کانال: {t.get('channel', 0)}\n"
        f"📩 خوانده‌نشده: {d['unread']}\n\n"
        f"از زمان روشن شدن: ارسال {counters['sent']} / دریافت {counters['received']}\n"
        f"پرکارترین چت‌ها:\n{top}"
    ))
