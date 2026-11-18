"""Text tools: translate, Jalali date, fancy fonts, calculator, clock in name.

.tr fa            -> reply to a message, translate it to Persian
.tr en سلام        -> translate given text
.date             -> Jalali + Gregorian date and Tehran time
.font Hello       -> same text in several Unicode styles
.calc 2*(3+4)     -> safe calculator
Clock: enable "clock" in panel settings -> last name shows HH:MM
"""
import ast
import asyncio
import datetime as dt
import logging
import operator
from zoneinfo import ZoneInfo

import jdatetime
from pyrogram import Client
from pyrogram.types import Message

from core import args_text, command, edit, safe_call, settings
from core.http import session

log = logging.getLogger("userbot.text")
TEHRAN = ZoneInfo("Asia/Tehran")
FA_DIGITS = str.maketrans("0123456789", "۰۱۲۳۴۵۶۷۸۹")


# ---------- translate ----------
async def translate(text: str, target: str) -> str:
    """Free Google Translate endpoint (no key). Goes through the proxy."""
    url = "https://translate.googleapis.com/translate_a/single"
    params = {"client": "gtx", "sl": "auto", "tl": target, "dt": "t", "q": text}
    async with session() as s, s.get(url, params=params) as r:
        r.raise_for_status()
        data = await r.json(content_type=None)
    return "".join(part[0] for part in data[0] if part[0])


@command("tr", "ترجمه: روی پیام ریپلای کن .tr fa  یا  .tr en متن")
async def tr(client: Client, message: Message):
    parts = args_text(message).split(maxsplit=1)
    target = parts[0] if parts else "fa"
    reply = message.reply_to_message
    text = parts[1] if len(parts) > 1 else ((reply.text or reply.caption) if reply else None)
    if not text:
        return await edit(message, "استفاده: روی پیام ریپلای کن و بنویس `.tr fa`")
    await edit(message, "⏳ در حال ترجمه...")
    await edit(message, f"🌐 **ترجمه ({target}):**\n{await translate(text, target)}")


# ---------- date ----------
@command("date", "تاریخ شمسی و میلادی و ساعت تهران")
async def date_cmd(client: Client, message: Message):
    now = dt.datetime.now(TEHRAN)
    j = jdatetime.datetime.fromgregorian(datetime=now.replace(tzinfo=None), locale="fa_IR")
    text = (
        f"📅 **{j.strftime('%A %d %B %Y')}**\n"
        f"🗓 {now.strftime('%Y-%m-%d')}\n"
        f"🕐 {now.strftime('%H:%M:%S')}"
    )
    await edit(message, text.translate(FA_DIGITS) if settings()["clock_fa"] else text)


# ---------- fonts ----------
def _shift(text: str, upper: int, lower: int, digit: int | None = None) -> str:
    """Map A-Z / a-z / 0-9 to a Unicode math alphabet block."""
    out = []
    for ch in text:
        if "A" <= ch <= "Z":
            out.append(chr(upper + ord(ch) - 65))
        elif "a" <= ch <= "z":
            out.append(chr(lower + ord(ch) - 97))
        elif digit and "0" <= ch <= "9":
            out.append(chr(digit + ord(ch) - 48))
        else:
            out.append(ch)
    return "".join(out)


STYLES = {
    "Bold": lambda t: _shift(t, 0x1D400, 0x1D41A, 0x1D7CE),
    "Italic": lambda t: _shift(t, 0x1D434, 0x1D44E),
    "Bold Script": lambda t: _shift(t, 0x1D4D0, 0x1D4EA),
    "Double": lambda t: _shift(t, 0x1D538, 0x1D552, 0x1D7D8),
    "Mono": lambda t: _shift(t, 0x1D670, 0x1D68A, 0x1D7F6),
    "Sans Bold": lambda t: _shift(t, 0x1D5D4, 0x1D5EE, 0x1D7EC),
    "Strike": lambda t: "".join(c + "̶" for c in t),
}


@command("font", "فونت‌های فانتزی انگلیسی: .font Hello")
async def font(client: Client, message: Message):
    text = args_text(message)
    if not text:
        return await edit(message, "استفاده: `.font Hello`")
    lines = [f"**{name}:** `{fn(text)}`" for name, fn in STYLES.items()]
    await edit(message, "🔤 " + "\n".join(lines))


# ---------- calculator ----------
OPS = {ast.Add: operator.add, ast.Sub: operator.sub, ast.Mult: operator.mul, ast.Div: operator.truediv,
       ast.Pow: operator.pow, ast.Mod: operator.mod, ast.FloorDiv: operator.floordiv,
       ast.USub: operator.neg, ast.UAdd: operator.pos}


def _eval(node):
    """Only numbers and arithmetic; anything else raises. No eval()."""
    if isinstance(node, ast.Constant) and isinstance(node.value, (int, float)):
        return node.value
    if isinstance(node, ast.BinOp) and type(node.op) in OPS:
        if isinstance(node.op, ast.Pow) and abs(_eval(node.right)) > 1000:
            raise ValueError("توان خیلی بزرگ است")
        return OPS[type(node.op)](_eval(node.left), _eval(node.right))
    if isinstance(node, ast.UnaryOp) and type(node.op) in OPS:
        return OPS[type(node.op)](_eval(node.operand))
    raise ValueError("عبارت نامعتبر")


@command("calc", "ماشین‌حساب: .calc 2*(3+4)")
async def calc(client: Client, message: Message):
    expr = args_text(message).replace("×", "*").replace("÷", "/")
    if not expr:
        return await edit(message, "استفاده: `.calc 2*(3+4)`")
    result = _eval(ast.parse(expr, mode="eval").body)
    await edit(message, f"🧮 `{expr}` = **{result}**")


# ---------- clock in last name ----------
async def on_start(client: Client):
    """Every 20s check; if clock enabled and minute changed, put HH:MM in last name."""
    last = None
    while True:
        try:
            s = settings()
            if s["clock"]:
                t = dt.datetime.now(TEHRAN).strftime("%H:%M")
                if s["clock_fa"]:
                    t = t.translate(FA_DIGITS)
                if t != last:
                    await safe_call(client.update_profile, last_name=f"| {t}")
                    last = t
            elif last is not None:
                await safe_call(client.update_profile, last_name="")  # clock turned off -> clear
                last = None
        except Exception:
            log.exception("clock update failed")
        await asyncio.sleep(20)
