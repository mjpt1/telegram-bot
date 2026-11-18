"""Tools plugin: .purge, .edit"""
import asyncio

from pyrogram import Client
from pyrogram.types import Message

from core import command, edit, safe_call

MAX_PURGE = 500  # hard cap so a typo can't wipe a whole chat


@command("purge", "Delete your last N messages here: .purge 10")
async def purge(client: Client, message: Message):
    args = message.command[1:]  # message.command = ["purge", "10"]
    if not args or not args[0].isdigit():
        return await edit(message, "Usage: `.purge <count>`")
    count = min(int(args[0]), MAX_PURGE)

    # Collect ONLY my own recent messages in this chat (skip the command itself)
    ids: list[int] = []
    async for msg in client.get_chat_history(message.chat.id, limit=count * 10 + 50):
        if msg.id == message.id:
            continue
        if msg.from_user and msg.from_user.is_self:
            ids.append(msg.id)
            if len(ids) >= count:
                break

    # Telegram allows max 100 ids per delete call; pause between batches
    for i in range(0, len(ids), 100):
        await safe_call(client.delete_messages, message.chat.id, ids[i:i + 100])
        await asyncio.sleep(1)

    await edit(message, f"🧹 Deleted `{len(ids)}` messages.")
    await asyncio.sleep(3)
    await safe_call(message.delete)  # remove the status message too


@command("edit", "Replace text: .edit <text> (reply to own msg to edit that one)")
async def edit_text(client: Client, message: Message):
    # Text after the command, keeping user formatting (markdown / html)
    parts = message.text.split(maxsplit=1)
    if len(parts) < 2:
        return await edit(message, "Usage: `.edit <text>`")
    new_text = parts[1]

    target = message.reply_to_message
    if target and target.from_user and target.from_user.is_self:
        # Edit the replied message, then remove the command message
        await safe_call(target.edit_text, new_text)
        await safe_call(message.delete)
    else:
        await edit(message, new_text)
