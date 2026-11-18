"""Group management. You must be admin with the right permissions.

Reply to a user's message, then:
.ban  .unban  .kick  .mute  .unmute  .pin  .unpin  .del
.id                    -> chat id / replied user id (useful for panel rules)
.welcome on <text>     -> greet new members ({name} = their name)
.welcome off
"""
import asyncio

from pyrogram import Client, filters
from pyrogram.types import ChatPermissions, Message

from core import args_text, command, edit, on_message, safe_call, store

# chat_id (str) -> welcome text
welcome = store.get("welcome", {})


def _target(message: Message):
    r = message.reply_to_message
    return r.from_user if r and r.from_user else None


async def _need_target(message: Message):
    user = _target(message)
    if not user:
        await edit(message, "روی پیام کاربر ریپلای کن.")
    return user


@command("ban", "بن کاربر (ریپلای)")
async def ban(client: Client, message: Message):
    if user := await _need_target(message):
        await safe_call(client.ban_chat_member, message.chat.id, user.id)
        await edit(message, f"⛔ {user.mention} بن شد.")


@command("unban", "آزاد کردن بن (ریپلای)")
async def unban(client: Client, message: Message):
    if user := await _need_target(message):
        await safe_call(client.unban_chat_member, message.chat.id, user.id)
        await edit(message, f"✅ {user.mention} آزاد شد.")


@command("kick", "اخراج بدون بن (ریپلای)")
async def kick(client: Client, message: Message):
    if user := await _need_target(message):
        await safe_call(client.ban_chat_member, message.chat.id, user.id)
        await asyncio.sleep(1)
        await safe_call(client.unban_chat_member, message.chat.id, user.id)
        await edit(message, f"👢 {user.mention} اخراج شد.")


@command("mute", "سکوت کاربر (ریپلای)")
async def mute(client: Client, message: Message):
    if user := await _need_target(message):
        await safe_call(client.restrict_chat_member, message.chat.id, user.id, ChatPermissions())
        await edit(message, f"🔇 {user.mention} ساکت شد.")


@command("unmute", "برداشتن سکوت (ریپلای)")
async def unmute(client: Client, message: Message):
    if user := await _need_target(message):
        perms = ChatPermissions(can_send_messages=True, can_send_media_messages=True,
                                can_send_other_messages=True, can_add_web_page_previews=True)
        await safe_call(client.restrict_chat_member, message.chat.id, user.id, perms)
        await edit(message, f"🔊 {user.mention} آزاد شد.")


@command("pin", "پین پیام (ریپلای)")
async def pin(client: Client, message: Message):
    if not message.reply_to_message:
        return await edit(message, "روی پیام ریپلای کن.")
    await safe_call(message.reply_to_message.pin, disable_notification=True)
    await safe_call(message.delete)


@command("unpin", "برداشتن پین (ریپلای)")
async def unpin(client: Client, message: Message):
    if not message.reply_to_message:
        return await edit(message, "روی پیام ریپلای کن.")
    await safe_call(message.reply_to_message.unpin)
    await safe_call(message.delete)


@command("del", "حذف پیام ریپلای‌شده")
async def delete(client: Client, message: Message):
    if message.reply_to_message:
        await safe_call(message.reply_to_message.delete)
    await safe_call(message.delete)


@command("id", "نمایش آیدی چت و کاربر")
async def show_id(client: Client, message: Message):
    lines = [f"🆔 چت: `{message.chat.id}`"]
    if user := _target(message):
        lines.append(f"👤 کاربر: `{user.id}`")
    r = message.reply_to_message
    if r and r.forward_from_chat:
        lines.append(f"📢 منبع فوروارد: `{r.forward_from_chat.id}`")
    await edit(message, "\n".join(lines))


@command("welcome", "خوشامد گروه: .welcome on متن  /  .welcome off")
async def welcome_cmd(client: Client, message: Message):
    parts = args_text(message).split(maxsplit=1)
    key = str(message.chat.id)
    if parts and parts[0] == "on":
        welcome[key] = parts[1] if len(parts) > 1 else "سلام {name} عزیز، خوش اومدی 🌹"
        store.save()
        await edit(message, f"✅ خوشامد فعال شد:\n{welcome[key]}")
    elif parts and parts[0] == "off":
        welcome.pop(key, None)
        store.save()
        await edit(message, "❌ خوشامد خاموش شد.")
    else:
        await edit(message, "استفاده: `.welcome on متن`  یا  `.welcome off`")


@on_message(filters.group & filters.new_chat_members, group=2)
async def greet(client: Client, message: Message):
    text = welcome.get(str(message.chat.id))
    if not text:
        return
    for user in message.new_chat_members:
        if not user.is_bot:
            await safe_call(message.reply_text, text.replace("{name}", user.mention))
