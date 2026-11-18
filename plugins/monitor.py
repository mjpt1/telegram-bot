"""Watchers and reports. All settings are edited from the panel.

- alerts      : notify in Saved Messages on mentions/replies to you and on chosen keywords
- watch       : notify when chosen contacts come online
- pricealerts : notify when a Wallex price crosses a value (checked every 5 min)
- activity    : messages sent/received per day and hour (for panel charts)
- report      : daily summary in Saved Messages at a chosen hour (Tehran)
- autobackup  : weekly backup file in Saved Messages
- chstats     : daily member count of channels you own (for growth charts)
- live events : new private messages are pushed to open panel tabs
"""
import asyncio
import datetime as dt
import io
import json
import logging
import secrets
import time

from pyrogram import Client, enums, filters
from pyrogram.handlers import UserStatusHandler
from pyrogram.types import Message, User

from core import on_message, safe_call, store
from core.decorators import _raw
from core.events import publish
from plugins.texttools import TEHRAN

log = logging.getLogger("userbot.monitor")

alerts = store.get("alerts", {"mentions": True, "words": [], "on": True})
watch: list = store.get("watch", [])                # user ids (str)
pricealerts: list = store.get("pricealerts", [])    # {id, sym, op, value}
activity: dict = store.get("activity", {})          # "YYYY-MM-DD" -> {"hours": [[sent, recv]*24]}
report = store.get("report", {"on": False, "hour": 22, "last": ""})
autobackup = store.get("autobackup", {"on": False, "last": 0.0})
chstats: dict = store.get("chstats", {})            # chat_id -> {date: members}
today_counts = {"date": "", "mentions": 0}
_online: dict[int, bool] = {}
_dirty = {"v": False}


def _today() -> str:
    return dt.datetime.now(TEHRAN).strftime("%Y-%m-%d")


def _title(chat) -> str:
    return chat.title or f"{chat.first_name or ''} {chat.last_name or ''}".strip() or str(chat.id)


# ---------- activity counter ----------
@on_message(filters.all, group=98)
async def track(client: Client, message: Message):
    if not message.chat:
        return
    now = dt.datetime.now(TEHRAN)
    day = activity.setdefault(now.strftime("%Y-%m-%d"), {"hours": [[0, 0] for _ in range(24)]})
    day["hours"][now.hour][0 if message.outgoing else 1] += 1
    _dirty["v"] = True
    if (message.chat.type == enums.ChatType.PRIVATE and not message.outgoing
            and message.from_user and not message.from_user.is_bot):
        publish({"type": "pm", "chat": message.chat.id, "from": _title(message.chat),
                 "text": (message.text or message.caption or "[رسانه]")[:200]})


# ---------- mentions & keywords ----------
@on_message(filters.incoming & ~filters.me & ~filters.private, group=7)
async def alert(client: Client, message: Message):
    if not alerts.get("on"):
        return
    text = message.text or message.caption or ""
    low = text.lower()
    hit = None
    if alerts.get("mentions") and message.mentioned:
        hit = "منشن / ریپلای"
    else:
        hit = next((w for w in alerts.get("words", []) if w and w.lower() in low), None)
    if not hit:
        return
    if today_counts["date"] != _today():
        today_counts.update(date=_today(), mentions=0)
    today_counts["mentions"] += 1
    who = _title(message.from_user) if message.from_user else _title(message.sender_chat or message.chat)
    link = message.link if message.chat.type != enums.ChatType.PRIVATE else ""
    await safe_call(client.send_message, "me",
                    f"🔔 **{hit}** در «{_title(message.chat)}»\n👤 {who}:\n{text[:800]}\n{link}",
                    disable_web_page_preview=True)
    publish({"type": "alert", "chat": message.chat.id, "from": _title(message.chat), "text": text[:200]})


# ---------- contact online ----------
@_raw(UserStatusHandler, None, 8)
async def status_watch(client: Client, user: User):
    if str(user.id) not in watch:
        return
    online = user.status == enums.UserStatus.ONLINE
    if online and not _online.get(user.id):
        await safe_call(client.send_message, "me", f"🟢 **{_title(user)}** آنلاین شد.")
        publish({"type": "online", "chat": user.id, "from": _title(user), "text": "آنلاین شد"})
    _online[user.id] = online


# ---------- background loops ----------
async def _prices(client: Client):
    from plugins.utils import _wallex
    if not pricealerts:
        return
    try:
        prices = await _wallex()
    except Exception as e:
        log.warning("price check failed: %s", e)
        return
    for a in list(pricealerts):
        p = prices.get(a["sym"])
        if p is None:
            continue
        if (a["op"] == ">" and p >= a["value"]) or (a["op"] == "<" and p <= a["value"]):
            await safe_call(client.send_message, "me",
                            f"📈 **هشدار قیمت** {a['sym']}: {p:,.0f} ({'بالای' if a['op'] == '>' else 'زیر'} {a['value']:,.0f})")
            pricealerts.remove(a)
            store.save()


def build_backup() -> bytes:
    data = json.loads(json.dumps(store.data))
    data.get("ai", {}).pop("key", None)
    return json.dumps(data, ensure_ascii=False, indent=2).encode("utf-8")


async def _backup(client: Client):
    if not autobackup.get("on") or time.time() - autobackup.get("last", 0) < 7 * 86400:
        return
    buf = io.BytesIO(build_backup())
    buf.name = time.strftime("userbot-backup-%Y%m%d.json")
    await safe_call(client.send_document, "me", buf, caption="💾 پشتیبان هفتگی سلف‌بات")
    autobackup["last"] = time.time()
    store.save()


async def build_report(client: Client) -> str:
    from core.chatops import list_chats
    day = activity.get(_today(), {"hours": [[0, 0]] * 24})["hours"]
    sent, recv = sum(h[0] for h in day), sum(h[1] for h in day)
    chats = await list_chats(client)
    unread = [c for c in chats if c["unread"] and not c["muted"]]
    top = "\n".join(f"  • {c['title']}: {c['unread']}" for c in sorted(unread, key=lambda c: -c["unread"])[:8]) or "  -"
    soon = [s for s in store.get("schedules", []) if s["at"] - time.time() < 86400]
    mentions = today_counts["mentions"] if today_counts["date"] == _today() else 0
    return (f"🗒 **گزارش روزانه** {_today()}\n"
            f"ارسال: {sent}  /  دریافت: {recv}\n"
            f"منشن و هشدار امروز: {mentions}\n"
            f"چت‌های بادار خوانده‌نشده ({len(unread)}):\n{top}\n"
            f"⏰ زمان‌بندی‌های ۲۴ ساعت آینده: {len(soon)}")


async def _report(client: Client):
    now = dt.datetime.now(TEHRAN)
    if report.get("on") and now.hour == int(report.get("hour", 22)) and report.get("last") != _today():
        report["last"] = _today()
        store.save()
        await safe_call(client.send_message, "me", await build_report(client))


async def _channels(client: Client):
    from core.chatops import list_chats
    today = _today()
    owned = [c for c in await list_chats(client) if c["type"] == "channel" and c.get("creator")]
    for c in owned[:30]:
        hist = chstats.setdefault(str(c["id"]), {})
        if today in hist:
            continue
        try:
            hist[today] = (await safe_call(client.get_chat, c["id"])).members_count or 0
        except Exception as e:
            log.warning("channel stat %s: %s", c["id"], e)
        for old in sorted(hist)[:-90]:  # keep 90 days
            hist.pop(old)
        await asyncio.sleep(2)
    store.save()


async def on_start(client: Client):
    tick = 0
    await asyncio.sleep(20)  # let startup settle
    while True:
        for name, func, every in (("prices", _prices, 5), ("backup", _backup, 60), ("report", _report, 1),
                                  ("channels", _channels, 360)):
            if tick % every == 0:
                try:
                    await func(client)
                except Exception:
                    log.exception("monitor %s failed", name)
        if _dirty["v"]:
            for old in sorted(activity)[:-60]:  # keep 60 days
                activity.pop(old)
            _dirty["v"] = False
            store.save()
        tick += 1
        await asyncio.sleep(60)


def new_alert(sym: str, op: str, value: float) -> dict:
    item = {"id": secrets.token_hex(4), "sym": sym.upper(), "op": op, "value": float(value)}
    pricealerts.append(item)
    store.save()
    return item
