"""Decorators plugins use to declare handlers.

Decorators do NOT touch the client. They only attach metadata to the
function; core.loader finds it later and registers it. So adding or removing
a plugin never requires editing the core.
"""
import functools
import logging
import traceback

from pyrogram import Client, filters
from pyrogram.filters import Filter
from pyrogram.handlers import DeletedMessagesHandler, EditedMessageHandler, MessageHandler
from pyrogram.types import Message

import config
from .flood import safe_call

log = logging.getLogger("userbot.cmd")

ATTR = "__userbot_handlers__"  # list of (handler_class, filter, group) on the function

# Registry used by .help: command name -> description
COMMANDS: dict[str, str] = {}


def _raw(handler_cls, flt: Filter | None, group: int):
    """Generic wrapper: log exceptions so one bad update never kills the bot."""
    def deco(func):
        @functools.wraps(func)
        async def wrapper(client: Client, update):
            try:
                await func(client, update)
            except Exception:
                log.exception("Handler %s failed", func.__name__)
        setattr(wrapper, ATTR, [(handler_cls, flt, group)])
        return wrapper
    return deco


def on_message(flt: Filter, group: int = 0):
    """New message handler for non-command logic (e.g. AFK auto-reply)."""
    return _raw(MessageHandler, flt, group)


def on_edited(flt: Filter, group: int = 0):
    """Edited message handler."""
    return _raw(EditedMessageHandler, flt, group)


def on_deleted(flt: Filter | None = None, group: int = 0):
    """Deleted messages handler; func receives (client, list[Message])."""
    return _raw(DeletedMessagesHandler, flt, group)


def command(name: str | list[str], description: str = "", group: int = 0):
    """Owner-only command handler.

    - filters.me      : only messages sent by the account owner
    - filters.command : matches <prefix><name>; prefixes come from config
    - Errors are caught and shown by editing the command message in place
    """
    names = [name] if isinstance(name, str) else name
    flt = filters.me & filters.command(names, prefixes=config.CMD_PREFIXES)

    def deco(func):
        for n in names:
            COMMANDS[n] = description

        @functools.wraps(func)
        async def wrapper(client: Client, message: Message):
            log.info("cmd %s in chat %s", message.command[0], message.chat.id)
            try:
                await func(client, message)
            except Exception as e:
                log.error("Command %s crashed:\n%s", names[0], traceback.format_exc())
                try:
                    await safe_call(message.edit_text, f"❌ `{type(e).__name__}: {e}`")
                except Exception:
                    pass  # message may be deleted already
        setattr(wrapper, ATTR, [(MessageHandler, flt, group)])
        return wrapper
    return deco


async def edit(message: Message, text: str, **kwargs) -> Message:
    """Edit own message in place, FloodWait-safe. Plugins should use this."""
    return await safe_call(message.edit_text, text, **kwargs)


def args_text(message: Message) -> str:
    """Everything after the command word, formatting kept."""
    parts = (message.text or "").split(maxsplit=1)
    return parts[1] if len(parts) > 1 else ""
