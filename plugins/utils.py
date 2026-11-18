"""Everyday utilities.

.remind 30 متن         -> reminder in Saved Messages after 30 minutes
.remind 18:30 متن      -> reminder at 18:30 (Tehran time, today or tomorrow)
.note name متن         -> save note (or reply to a message: .note name)
.note name             -> show note
.notes                 -> list notes      .delnote name -> delete
.qr متن                -> QR code image
.weather تهران         -> weather
.rate                  -> USDT (toman), BTC, ETH prices
.dl https://...        -> download a file from link and send it here (max 50 MB)
"""
import datetime as dt
import io
import logging
import os
import secrets
import tempfile
import time
from urllib.parse import quote, urlparse

import qrcode
from pyrogram import Client
from pyrogram.types import Message

from core import args_text, command, edit, safe_call, store
from core.http import session
from plugins.texttools import TEHRAN

log = logging.getLogger("userbot.utils")
notes: dict = store.get("notes", {})          # name -> text
schedules: list = store.get("schedules", [])  # shared with automation scheduler
MAX_DL = 50 * 1024 * 1024


# ---------- reminder (uses automation's scheduler queue) ----------
def _parse_when(token: str) -> float | None:
    """'30' -> now+30min, '18:30' -> next 18:30 Tehran. None if invalid."""
    if token.isdigit():
        return time.time() + int(token) * 60
    try:
        h, m = map(int, token.split(":"))
        now = dt.datetime.now(TEHRAN)
        at = now.replace(hour=h, minute=m, second=0, microsecond=0)
        if at <= now:
            at += dt.timedelta(days=1)
        return at.timestamp()
    except ValueError:
        return None


@command("remind", "یادآور: .remind 30 متن  یا  .remind 18:30 متن")
async def remind(client: Client, message: Message):
    parts = args_text(message).split(maxsplit=1)
    at = _parse_when(parts[0]) if parts else None
    if not at or len(parts) < 2:
        return await edit(message, "استفاده: `.remind 30 خرید نان`  یا  `.remind 18:30 جلسه`")
    schedules.append({"id": secrets.token_hex(4), "chat": "me", "text": f"⏰ **یادآوری:** {parts[1]}", "at": at})
    store.save()
    when = dt.datetime.fromtimestamp(at, TEHRAN).strftime("%H:%M")
    await edit(message, f"⏰ یادآوری برای ساعت {when} ثبت شد (در Saved Messages).")


# ---------- notes ----------
@command("note", "یادداشت: .note اسم متن  /  .note اسم")
async def note(client: Client, message: Message):
    parts = args_text(message).split(maxsplit=1)
    if not parts:
        return await edit(message, "استفاده: `.note اسم متن`  یا روی پیام ریپلای کن: `.note اسم`")
    name = parts[0].lower()
    reply = message.reply_to_message
    text = parts[1] if len(parts) > 1 else ((reply.text or reply.caption) if reply else None)
    if text:
        notes[name] = text
        store.save()
        return await edit(message, f"📝 یادداشت `{name}` ذخیره شد.")
    if name in notes:
        return await edit(message, notes[name])
    await edit(message, f"یادداشت `{name}` پیدا نشد.")


@command("notes", "فهرست یادداشت‌ها")
async def notes_list(client: Client, message: Message):
    if not notes:
        return await edit(message, "یادداشتی نداری.")
    await edit(message, "📒 **یادداشت‌ها:**\n" + "\n".join(f"• `{n}`" for n in sorted(notes)))


@command("delnote", "حذف یادداشت: .delnote اسم")
async def delnote(client: Client, message: Message):
    name = args_text(message).strip().lower()
    if notes.pop(name, None) is None:
        return await edit(message, "یادداشت پیدا نشد.")
    store.save()
    await edit(message, f"🗑 یادداشت `{name}` حذف شد.")


# ---------- QR ----------
@command("qr", "ساخت QR code: .qr متن یا لینک")
async def qr(client: Client, message: Message):
    reply = message.reply_to_message
    data = args_text(message) or ((reply.text or reply.caption) if reply else "")
    if not data:
        return await edit(message, "استفاده: `.qr https://example.com`")
    buf = io.BytesIO()
    qrcode.make(data).save(buf, format="PNG")
    buf.name = "qr.png"
    buf.seek(0)
    await safe_call(client.send_photo, message.chat.id, buf, caption=f"`{data[:200]}`")
    await safe_call(message.delete)


# ---------- weather ----------
@command("weather", "آب‌وهوا: .weather تهران")
async def weather(client: Client, message: Message):
    city = args_text(message).strip() or "Tehran"
    await edit(message, "⏳ ...")
    fmt = "%l\n%c %C\n🌡 دما: %t (احساس %f)\n💧 رطوبت: %h\n💨 باد: %w"
    async with session() as s, s.get(f"https://wttr.in/{quote(city)}", params={"format": fmt, "lang": "fa"}) as r:
        text = (await r.text()).strip()
    if r.status != 200 or "Unknown location" in text:
        return await edit(message, f"شهر «{city}» پیدا نشد.")
    await edit(message, f"🌤 **آب‌وهوا**\n{text}")


# ---------- prices ----------
async def _wallex() -> dict:
    """All Wallex markets: symbol -> last price (works direct and via proxy)."""
    async with session(timeout=10) as s, s.get("https://api.wallex.ir/v1/markets") as r:
        data = await r.json(content_type=None)
    prices = {}
    for k, v in data["result"]["symbols"].items():
        try:
            prices[k] = float(v["stats"]["lastPrice"])
        except (KeyError, TypeError, ValueError):
            pass  # inactive markets report "-"
    return prices


async def _tetherland_usdt() -> float:
    """Fallback for USDT price in toman."""
    async with session(timeout=10) as s, s.get("https://api.tetherland.com/currencies") as r:
        data = await r.json(content_type=None)
    return float(data["data"]["currencies"]["USDT"]["price"])


async def _coingecko(coin_id: str) -> float:
    """Fallback for BTC/ETH in USD."""
    url = "https://api.coingecko.com/api/v3/simple/price"
    async with session(timeout=10) as s, s.get(url, params={"ids": coin_id, "vs_currencies": "usd"}) as r:
        data = await r.json(content_type=None)
    return float(data[coin_id]["usd"])


@command("rate", "قیمت تتر (تومان)، بیت‌کوین و اتریوم")
async def rate(client: Client, message: Message):
    await edit(message, "⏳ ...")
    try:
        w = await _wallex()
    except Exception as e:
        log.warning("wallex failed: %s", e)
        w = {}

    lines = []
    usdt = w.get("USDTTMN")
    if not usdt:
        try:
            usdt = await _tetherland_usdt()
        except Exception as e:
            log.warning("tetherland failed: %s", e)
    lines.append(f"💵 تتر: **{usdt:,.0f}** تومان" if usdt else "💵 تتر: دریافت نشد")

    for sym, cg_id, label in (("BTC", "bitcoin", "₿ بیت‌کوین"), ("ETH", "ethereum", "◆ اتریوم")):
        price = w.get(f"{sym}USDT")
        if not price:
            try:
                price = await _coingecko(cg_id)
            except Exception as e:
                log.warning("%s price failed: %s", sym, e)
        if price:
            toman = f" (≈ {price * usdt:,.0f} تومان)" if usdt else ""
            lines.append(f"{label}: **${price:,.0f}**{toman}")
        else:
            lines.append(f"{label}: دریافت نشد")
    await edit(message, "📈 **قیمت‌ها** (والکس / تترلند)\n" + "\n".join(lines))


# ---------- download from link ----------
@command("dl", "دانلود فایل از لینک و ارسال (حداکثر ۵۰ مگ): .dl https://...")
async def dl(client: Client, message: Message):
    url = args_text(message).strip()
    if urlparse(url).scheme not in ("http", "https"):
        return await edit(message, "استفاده: `.dl https://example.com/file.zip`")
    await edit(message, "⬇️ در حال دانلود...")
    name = os.path.basename(urlparse(url).path) or "file"
    fd, path = tempfile.mkstemp(suffix="_" + name)
    os.close(fd)  # reopen by path below; avoids leaking the handle on early return
    size = 0
    try:
        async with session(timeout=600) as s, s.get(url) as r:
            r.raise_for_status()
            if int(r.headers.get("Content-Length") or 0) > MAX_DL:
                return await edit(message, "❌ فایل بزرگ‌تر از ۵۰ مگابایت است.")
            with open(path, "wb") as f:
                async for chunk in r.content.iter_chunked(64 * 1024):
                    size += len(chunk)
                    if size > MAX_DL:
                        return await edit(message, "❌ فایل بزرگ‌تر از ۵۰ مگابایت است.")
                    f.write(chunk)
        await edit(message, f"⬆️ در حال آپلود ({size / 1048576:.1f} MB)...")
        await safe_call(client.send_document, message.chat.id, path, file_name=name)
        await safe_call(message.delete)
    finally:
        try:
            os.remove(path)
        except OSError:
            pass
