"""Bulk chat operations used by the web panel: mute, leave, block bots, archive...

Every action goes through safe_call and a small pause between chats so a
bulk operation on hundreds of chats never triggers a FloodWait ban.
"""
import asyncio
import logging
import time

from pyrogram import Client
from pyrogram.raw import functions, types

from .flood import safe_call

log = logging.getLogger("userbot.chatops")
MUTE_FOREVER = 2**31 - 1


def _muted(dialog) -> bool:
    ns = getattr(dialog.raw, "notify_settings", None) if dialog.raw else None
    until = getattr(ns, "mute_until", None) or 0
    return until > time.time()


# One shared cache for every dialog list (panel tabs, stats). GetDialogs is a
# heavy call and Telegram answers repeated full scans with FloodWait.
CACHE_TTL = 300
_cache: dict = {"at": 0.0, "data": None}
_lock = asyncio.Lock()


def invalidate() -> None:
    _cache["at"] = 0.0


async def list_chats(client: Client, force: bool = False) -> list[dict]:
    """All dialogs, cached 5 min. Concurrent callers wait for one fetch."""
    async with _lock:
        if not force and _cache["data"] is not None and time.time() - _cache["at"] < CACHE_TTL:
            return _cache["data"]
        _cache["data"] = await _fetch(client)
        _cache["at"] = time.time()
        return _cache["data"]


async def _fetch(client: Client) -> list[dict]:
    out = []
    async for d in client.get_dialogs():
        c = d.chat
        title = c.title or f"{c.first_name or ''} {c.last_name or ''}".strip() or str(c.id)
        out.append({
            "id": c.id, "title": title, "type": c.type.name.lower(), "username": c.username,
            "muted": _muted(d), "unread": d.unread_messages_count or 0,
            "archived": d.folder_id == 1, "members": getattr(c, "members_count", None),
            "pinned": bool(d.is_pinned), "creator": bool(getattr(c, "is_creator", False)),
            "last": int(d.top_message.date.timestamp()) if d.top_message and d.top_message.date else 0,
        })
    return out


async def _set_mute(client: Client, chat_id: int, mute: bool):
    peer = await client.resolve_peer(chat_id)
    await client.invoke(functions.account.UpdateNotifySettings(
        peer=types.InputNotifyPeer(peer=peer),
        settings=types.InputPeerNotifySettings(mute_until=MUTE_FOREVER if mute else 0),
    ))


async def _delete_history(client: Client, chat_id: int):
    """Delete the chat for me only (bots / private chats)."""
    peer = await client.resolve_peer(chat_id)
    await client.invoke(functions.messages.DeleteHistory(peer=peer, max_id=0, just_clear=False, revoke=False))


async def _stop_bot(client: Client, chat_id: int):
    """Block the bot (it can no longer message you) and remove the chat."""
    await client.block_user(chat_id)
    await _delete_history(client, chat_id)


async def _leave(client: Client, chat_id: int):
    """Groups/channels: leave. Private chats/bots (positive id): delete the chat."""
    if chat_id > 0:
        await _delete_history(client, chat_id)
    else:
        await client.leave_chat(chat_id)


async def _pin(client: Client, chat_id: int, on: bool):
    peer = await client.resolve_peer(chat_id)
    await client.invoke(functions.messages.ToggleDialogPin(peer=types.InputDialogPeer(peer=peer), pinned=on))


ACTIONS = {
    "pin": (lambda c, i: _pin(c, i, True), 0.5),
    "unpin": (lambda c, i: _pin(c, i, False), 0.5),
    "mute": (lambda c, i: _set_mute(c, i, True), 0.4),
    "unmute": (lambda c, i: _set_mute(c, i, False), 0.4),
    "leave": (_leave, 1.5),  # leaving is slow on purpose (anti-flood)
    "block": (lambda c, i: c.block_user(i), 0.8),
    "unblock": (lambda c, i: c.unblock_user(i), 0.8),
    "stopbot": (_stop_bot, 1.0),
    "delete": (_delete_history, 1.0),
    "archive": (lambda c, i: c.archive_chats(i), 0.4),
    "unarchive": (lambda c, i: c.unarchive_chats(i), 0.4),
    "read": (lambda c, i: c.read_chat_history(i), 0.3),
}


async def run_action(client: Client, action: str, ids: list[int]) -> dict:
    """Apply action to each chat; return {"ok": [...], "failed": {id: error}}."""
    func, pause = ACTIONS[action]
    ok, failed = [], {}
    for chat_id in ids:
        try:
            await safe_call(func, client, chat_id)
            ok.append(chat_id)
        except Exception as e:
            failed[chat_id] = f"{type(e).__name__}: {e}"
            log.warning("%s failed on %s: %s", action, chat_id, e)
        await asyncio.sleep(pause)
    invalidate()  # next list shows the new state
    log.info("chat action %s: %d ok, %d failed", action, len(ok), len(failed))
    return {"ok": ok, "failed": failed}


# ---------- folders ----------
def _title(f) -> str:
    t = getattr(f, "title", "")
    return getattr(t, "text", t) or ""


async def _filters(client: Client) -> list:
    res = await safe_call(client.invoke, functions.messages.GetDialogFilters())
    items = getattr(res, "filters", res)  # newer layers wrap the list
    return [f for f in items if isinstance(f, types.DialogFilter)]


async def list_folders(client: Client) -> list[dict]:
    return [{"id": f.id, "title": _title(f), "count": len(f.include_peers)} for f in await _filters(client)]


async def add_to_folder(client: Client, folder_id: int, ids: list[int]) -> int:
    f = next((x for x in await _filters(client) if x.id == folder_id), None)
    if f is None:
        raise ValueError("پوشه پیدا نشد")
    added = 0
    for chat_id in ids:
        peer = await client.resolve_peer(chat_id)
        if peer not in f.include_peers:
            f.include_peers.append(peer)
            added += 1
    await safe_call(client.invoke, functions.messages.UpdateDialogFilter(id=f.id, filter=f))
    return added


# ---------- blocked users ----------
async def list_blocked(client: Client) -> list[dict]:
    out, offset = [], 0
    while True:
        res = await safe_call(client.invoke, functions.contacts.GetBlocked(offset=offset, limit=100))
        for u in res.users:
            out.append({"id": u.id, "title": f"{u.first_name or ''} {u.last_name or ''}".strip() or str(u.id),
                        "username": u.username, "bot": bool(u.bot)})
        if len(res.users) < 100 or offset > 2000:
            return out
        offset += 100
        await asyncio.sleep(1)


# ---------- delete my own messages in one chat ----------
async def purge_mine(client: Client, chat_id: int, limit: int = 1000) -> int:
    ids = [m.id async for m in client.search_messages(chat_id, from_user="me", limit=limit)]
    for i in range(0, len(ids), 100):
        await safe_call(client.delete_messages, chat_id, ids[i:i + 100])
        await asyncio.sleep(1)
    return len(ids)
