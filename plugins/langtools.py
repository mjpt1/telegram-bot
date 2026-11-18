"""Voice-to-text and per-chat auto translation.

.stt (reply to a voice / video note) -> Telegram's own transcription
    (needs Telegram Premium; free accounts get a few trials per week)
.autotr fa in   -> incoming messages of this chat are translated to Persian in Saved Messages
.autotr en out  -> your own messages in this chat are replaced by their English translation
.autotr off     -> stop in this chat
Settings in store "autotr": chat_id -> {"lang": "en", "mode": "in"|"out"} (also in panel).
"""
import asyncio
import logging

from pyrogram import Client, filters
from pyrogram.raw import functions
from pyrogram.types import Message

import config
from core import args_text, command, edit, on_message, safe_call, store
from plugins.texttools import translate

log = logging.getLogger("userbot.lang")
autotr: dict = store.get("autotr", {})


async def transcribe(client: Client, message: Message) -> str:
    peer = await client.resolve_peer(message.chat.id)
    res = await safe_call(client.invoke, functions.messages.TranscribeAudio(peer=peer, msg_id=message.id))
    for _ in range(15):  # long audio: Telegram finishes the text in the background
        if not getattr(res, "pending", False):
            break
        await asyncio.sleep(2)
        res = await safe_call(client.invoke, functions.messages.TranscribeAudio(peer=peer, msg_id=message.id))
    return res.text or ""


@command("stt", "تبدیل ویس به متن: روی ویس ریپلای کن و بنویس .stt")
async def stt(client: Client, message: Message):
    r = message.reply_to_message
    if not r or not (r.voice or r.video_note or r.audio):
        return await edit(message, "روی یک ویس یا ویدیو مسیج ریپلای کن و بنویس `.stt`")
    await edit(message, "🎙 در حال تبدیل...")
    try:
        text = await transcribe(client, r)
    except Exception as e:
        if "PREMIUM" in str(e).upper():
            return await edit(message, "❌ تبدیل ویس به متن تلگرام برای این اکانت فعال نیست (نیاز به پریمیوم).")
        raise
    await edit(message, f"🎙 **متن ویس:**\n{text or '(متنی تشخیص داده نشد)'}")


@command("autotr", "ترجمه خودکار این چت: .autotr fa in  /  .autotr en out  /  .autotr off")
async def autotr_cmd(client: Client, message: Message):
    parts = args_text(message).split()
    key = str(message.chat.id)
    if parts and parts[0] == "off":
        autotr.pop(key, None)
        store.save()
        return await edit(message, "ترجمه خودکار این چت خاموش شد.")
    if len(parts) == 2 and parts[1] in ("in", "out"):
        autotr[key] = {"lang": parts[0], "mode": parts[1]}
        store.save()
        what = "پیام‌های دریافتی (در Saved Messages)" if parts[1] == "in" else "پیام‌های خودت"
        return await edit(message, f"🌐 ترجمه خودکار {what} به `{parts[0]}` روشن شد.")
    await edit(message, "استفاده: `.autotr fa in`  یا  `.autotr en out`  یا  `.autotr off`")


def _has_rule(_, __, m: Message) -> bool:
    return bool(m.chat) and str(m.chat.id) in autotr and bool(m.text)


@on_message(filters.text & filters.create(_has_rule), group=9)
async def auto_translate(client: Client, message: Message):
    rule = autotr[str(message.chat.id)]
    if message.outgoing:
        if rule["mode"] != "out" or message.text.startswith(tuple(config.CMD_PREFIXES)):
            return
        out = await translate(message.text, rule["lang"])
        if out and out.strip() != message.text.strip():
            await safe_call(message.edit_text, out)
    elif rule["mode"] == "in" and message.chat.id != client.me.id:
        out = await translate(message.text, rule["lang"])
        title = message.chat.title or message.chat.first_name or str(message.chat.id)
        await safe_call(client.send_message, "me", f"🌐 **{title}**\n{out}\n\n__{message.text[:300]}__")
