"""Panel API, part 3: global search, channels, alerts, price alerts, contact
watch, auto-translate, daily report, auto-backup, activity chart, live events.
"""
import asyncio
import io
import json
import logging
import time

from aiohttp import web

from core import chat_ref, safe_call, store
from core.events import SUBSCRIBERS

log = logging.getLogger("userbot.panel")
routes = web.RouteTableDef()


def cl(request):
    return request.app["client"]


def bad(msg: str, status: int = 400):
    return web.json_response({"error": msg}, status=status)


def _name(x) -> str:
    if not x:
        return ""
    return getattr(x, "title", None) or f"{x.first_name or ''} {x.last_name or ''}".strip() or str(x.id)


# ---------- search in all chats ----------
@routes.get("/api/search")
async def search(request):
    q = request.query.get("q", "").strip()
    chat = request.query.get("chat", "").strip()
    if len(q) < 2:
        return bad("حداقل ۲ حرف بنویس")
    c = cl(request)
    gen = c.search_messages(chat_ref(chat), query=q, limit=50) if chat else c.search_global(q, limit=50)
    out = []
    async for m in gen:
        out.append({"chat": m.chat.id, "chat_title": _name(m.chat), "id": m.id,
                    "from": _name(m.from_user or m.sender_chat), "date": int(m.date.timestamp()) if m.date else 0,
                    "text": (m.text or m.caption or "")[:300], "link": m.link if m.chat.username else ""})
    return web.json_response(out)


# ---------- channels ----------
@routes.get("/api/channels")
async def channels(request):
    from core.chatops import list_chats
    chs = [c for c in await list_chats(cl(request)) if c["type"] == "channel" and c.get("creator")]
    hist = store.get("chstats", {})
    return web.json_response([{**c, "history": hist.get(str(c["id"]), {})} for c in chs])


@routes.get("/api/channels/{chat}/posts")
async def channel_posts(request):
    from web.extra import resolve_id
    chat = await resolve_id(cl(request), request.match_info["chat"])
    out = []
    async for m in cl(request).get_chat_history(chat, limit=20):
        out.append({"id": m.id, "date": int(m.date.timestamp()) if m.date else 0, "views": m.views or 0,
                    "forwards": m.forwards or 0, "text": (m.text or m.caption or "[رسانه]")[:120]})
    return web.json_response(out)


# ---------- alerts / watch / price alerts / auto-translate ----------
@routes.get("/api/monitor")
async def monitor_get(request):
    from plugins import langtools, monitor
    return web.json_response({"alerts": monitor.alerts, "watch": monitor.watch, "prices": monitor.pricealerts,
                              "autotr": langtools.autotr, "report": monitor.report,
                              "autobackup": monitor.autobackup})


@routes.post("/api/monitor/alerts")
async def alerts_set(request):
    from plugins import monitor
    d = await request.json()
    a = monitor.alerts
    a["on"], a["mentions"] = bool(d.get("on")), bool(d.get("mentions"))
    a["words"] = [str(w).strip() for w in d.get("words", []) if str(w).strip()]
    store.save()
    return web.json_response(a)


@routes.post("/api/monitor/watch")
async def watch_set(request):
    from plugins import monitor
    d = await request.json()
    ids = []
    for x in d.get("ids", []):
        x = str(x).strip()
        if not x:
            continue
        if not x.lstrip("-").isdigit():  # @username -> id
            try:
                x = str((await safe_call(cl(request).get_users, x)).id)
            except Exception:
                return bad(f"کاربر {x} پیدا نشد")
        ids.append(x)
    monitor.watch[:] = ids
    store.save()
    return web.json_response(monitor.watch)


@routes.post("/api/monitor/prices")
async def price_add(request):
    from plugins import monitor
    d = await request.json()
    sym, op = str(d.get("sym", "")).upper().strip(), d.get("op")
    try:
        value = float(d.get("value"))
    except (TypeError, ValueError):
        return bad("عدد نامعتبر")
    if not sym or op not in (">", "<"):
        return bad("نماد و شرط لازم است")
    return web.json_response(monitor.new_alert(sym, op, value))


@routes.delete("/api/monitor/prices/{id}")
async def price_del(request):
    from plugins import monitor
    monitor.pricealerts[:] = [a for a in monitor.pricealerts if a["id"] != request.match_info["id"]]
    store.save()
    return web.json_response({"ok": True})


@routes.get("/api/prices")
async def prices_now(request):
    from plugins.utils import _wallex
    p = await _wallex()
    keep = ("USDTTMN", "BTCUSDT", "ETHUSDT", "BTCTMN", "TONUSDT", "NOTUSDT", "DOGEUSDT", "SOLUSDT", "TRXUSDT")
    return web.json_response({k: p[k] for k in keep if k in p})


@routes.post("/api/monitor/autotr")
async def autotr_set(request):
    from plugins import langtools
    d = await request.json()
    from web.extra import resolve_id
    if not str(d.get("chat", "")).strip():
        return bad("چت را مشخص کن")
    chat = str(await resolve_id(cl(request), d["chat"]))
    if d.get("off"):
        langtools.autotr.pop(chat, None)
    else:
        lang, mode = str(d.get("lang", "")).strip(), d.get("mode")
        if not lang or mode not in ("in", "out"):
            return bad("زبان و حالت لازم است")
        langtools.autotr[chat] = {"lang": lang, "mode": mode}
    store.save()
    return web.json_response(langtools.autotr)


# ---------- report & backup ----------
@routes.post("/api/monitor/report")
async def report_set(request):
    from plugins import monitor
    d = await request.json()
    monitor.report["on"] = bool(d.get("on"))
    monitor.report["hour"] = min(23, max(0, int(d.get("hour", 22))))
    store.save()
    return web.json_response(monitor.report)


@routes.post("/api/monitor/report/now")
async def report_now(request):
    from plugins import monitor
    text = await monitor.build_report(cl(request))
    await safe_call(cl(request).send_message, "me", text)
    return web.json_response({"text": text})


@routes.post("/api/monitor/autobackup")
async def autobackup_set(request):
    from plugins import monitor
    d = await request.json()
    monitor.autobackup["on"] = bool(d.get("on"))
    if d.get("now"):
        buf = io.BytesIO(monitor.build_backup())
        buf.name = time.strftime("userbot-backup-%Y%m%d-%H%M.json")
        await safe_call(cl(request).send_document, "me", buf, caption="💾 پشتیبان سلف‌بات")
        monitor.autobackup["last"] = time.time()
    store.save()
    return web.json_response(monitor.autobackup)


# ---------- activity chart data ----------
@routes.get("/api/activity")
async def activity(request):
    act = store.get("activity", {})
    days = sorted(act)[-30:]
    daily = [{"date": d, "sent": sum(h[0] for h in act[d]["hours"]), "recv": sum(h[1] for h in act[d]["hours"])}
             for d in days]
    hourly = [[0, 0] for _ in range(24)]
    for d in days:
        for i, h in enumerate(act[d]["hours"]):
            hourly[i][0] += h[0]
            hourly[i][1] += h[1]
    return web.json_response({"daily": daily, "hourly": hourly})


# ---------- live events (Server-Sent Events) ----------
@routes.get("/api/events")
async def events(request):
    resp = web.StreamResponse(headers={"Content-Type": "text/event-stream", "Cache-Control": "no-cache"})
    await resp.prepare(request)
    q: asyncio.Queue = asyncio.Queue()
    SUBSCRIBERS.add(q)
    try:
        while True:
            try:
                ev = await asyncio.wait_for(q.get(), timeout=25)
                await resp.write(f"data: {json.dumps(ev, ensure_ascii=False)}\n\n".encode())
            except asyncio.TimeoutError:
                await resp.write(b": ping\n\n")  # keep the connection alive
    except (ConnectionResetError, asyncio.CancelledError):
        pass
    finally:
        SUBSCRIBERS.discard(q)
    return resp
