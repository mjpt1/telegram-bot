"""Extra panel API: messages, broadcast, upload, folders, blocked, profile,
privacy, sessions, group members, antispam/welcome/AI/autobio settings,
plugins on/off, backup/restore, restart.

Registered by web.server.start_panel; same auth middleware applies.
"""
import asyncio
import json
import logging
import os
import sys
import tempfile
import time
from pathlib import Path

from aiohttp import web
from pyrogram import enums
from pyrogram.raw import functions, types
from pyrogram.types import ChatPermissions

import config
from core import chat_ref, safe_call, store
from core import chatops

log = logging.getLogger("userbot.panel")
routes = web.RouteTableDef()


def cl(request):
    return request.app["client"]


def bad(msg: str, status: int = 400):
    return web.json_response({"error": msg}, status=status)


async def resolve_id(client, value) -> int:
    """'-100..', 'me', '@user' or 'user' -> numeric chat id."""
    v = chat_ref(value)
    if isinstance(v, int):
        return v
    if not v:
        raise web.HTTPBadRequest(text="chat required")
    return (await safe_call(client.get_chat, v)).id


def _name(u) -> str:
    if not u:
        return ""
    return getattr(u, "title", None) or f"{u.first_name or ''} {u.last_name or ''}".strip() or str(u.id)


# ---------- read & reply in a chat ----------
@routes.get("/api/messages/{chat}")
async def messages(request):
    chat = chat_ref(request.match_info["chat"])
    out = []
    async for m in cl(request).get_chat_history(chat, limit=40):
        out.append({
            "id": m.id, "out": bool(m.outgoing), "date": int(m.date.timestamp()) if m.date else 0,
            "from": _name(m.from_user or m.sender_chat),
            "text": m.text or m.caption or "", "media": m.media.name.lower() if m.media else None,
        })
    return web.json_response(out[::-1])  # oldest first


@routes.post("/api/reply")
async def reply(request):
    d = await request.json()
    chat, text = str(d.get("chat", "")).strip(), str(d.get("text", "")).strip()
    if not chat or not text:
        return bad("چت و متن لازم است")
    msg = await safe_call(cl(request).send_message, chat_ref(chat), text,
                          reply_to_message_id=int(d["reply_to"]) if d.get("reply_to") else None)
    return web.json_response({"ok": True, "id": msg.id})


# ---------- broadcast ----------
@routes.post("/api/broadcast")
async def broadcast(request):
    d = await request.json()
    text = str(d.get("text", "")).strip()
    ids = [int(i) for i in d.get("ids", [])]
    if not text or not ids:
        return bad("متن و حداقل یک چت لازم است")
    if len(ids) > 100:
        return bad("حداکثر ۱۰۰ چت در هر بار")
    ok, failed = 0, {}
    for i in ids:
        try:
            await safe_call(cl(request).send_message, i, text)
            ok += 1
        except Exception as e:
            failed[str(i)] = str(e)
        await asyncio.sleep(1.5)  # slow on purpose: mass sending triggers spam limits
    return web.json_response({"ok": ok, "failed": failed})


# ---------- upload & send a file ----------
@routes.post("/api/upload")
async def upload(request):
    reader = await request.multipart()
    fields, path, fname = {}, None, "file"
    try:
        async for part in reader:
            if part.name == "file":
                fname = os.path.basename(part.filename or "file")
                fd, path = tempfile.mkstemp(suffix="_" + fname)
                with os.fdopen(fd, "wb") as f:
                    while chunk := await part.read_chunk():
                        f.write(chunk)
            else:
                fields[part.name] = (await part.text()).strip()
        if not path or not fields.get("chat"):
            return bad("فایل و چت لازم است")
        c, chat, cap = cl(request), chat_ref(fields["chat"]), fields.get("caption") or None
        if fname.lower().endswith((".jpg", ".jpeg", ".png", ".webp")) and fields.get("as_photo") == "1":
            await safe_call(c.send_photo, chat, path, caption=cap)
        else:
            await safe_call(c.send_document, chat, path, caption=cap, file_name=fname)
        return web.json_response({"ok": True})
    finally:
        if path:
            try:
                os.remove(path)
            except OSError:
                pass


# ---------- delete my messages in one chat ----------
@routes.post("/api/purge")
async def purge(request):
    d = await request.json()
    if not str(d.get("chat") or "").strip():
        return bad("چت را مشخص کن")
    chat, limit = await resolve_id(cl(request), d["chat"]), min(int(d.get("limit") or 1000), 3000)
    n = await chatops.purge_mine(cl(request), chat, limit)
    return web.json_response({"deleted": n})


# ---------- folders & blocked ----------
@routes.get("/api/folders")
async def folders(request):
    return web.json_response(await chatops.list_folders(cl(request)))


@routes.post("/api/folders/add")
async def folders_add(request):
    d = await request.json()
    ids = [int(i) for i in d.get("ids", [])]
    if not ids:
        return bad("هیچ چتی انتخاب نشده")
    n = await chatops.add_to_folder(cl(request), int(d.get("folder")), ids)
    return web.json_response({"added": n})


@routes.get("/api/blocked")
async def blocked(request):
    return web.json_response(await chatops.list_blocked(cl(request)))


# ---------- profile ----------
@routes.get("/api/profile")
async def profile_get(request):
    c = cl(request)
    me = await c.get_me()
    full = await c.get_chat("me")
    return web.json_response({"first_name": me.first_name or "", "last_name": me.last_name or "",
                              "username": me.username or "", "bio": full.bio or "", "phone": me.phone_number})


@routes.post("/api/profile")
async def profile_set(request):
    d, c = await request.json(), cl(request)
    me = await c.get_me()
    kw = {k: str(d[k]) for k in ("first_name", "last_name", "bio") if k in d}
    if "first_name" in kw and not kw["first_name"].strip():
        return bad("نام نمی‌تواند خالی باشد")
    if kw:
        await safe_call(c.update_profile, **kw)
    if "username" in d and (d["username"] or "") != (me.username or ""):
        await safe_call(c.set_username, d["username"].lstrip("@") or None)
    return web.json_response({"ok": True})


@routes.post("/api/profile/photo")
async def profile_photo(request):
    reader = await request.multipart()
    part = await reader.next()
    if not part or part.name != "file":
        return bad("عکس لازم است")
    fd, path = tempfile.mkstemp(suffix=".jpg")
    try:
        with os.fdopen(fd, "wb") as f:
            while chunk := await part.read_chunk():
                f.write(chunk)
        await safe_call(cl(request).set_profile_photo, photo=path)
    finally:
        os.remove(path)
    return web.json_response({"ok": True})


# ---------- privacy ----------
PRIVACY = {
    "last_seen": types.InputPrivacyKeyStatusTimestamp,
    "photo": types.InputPrivacyKeyProfilePhoto,
    "phone": types.InputPrivacyKeyPhoneNumber,
    "forwards": types.InputPrivacyKeyForwards,
    "calls": types.InputPrivacyKeyPhoneCall,
    "invites": types.InputPrivacyKeyChatInvite,
}
RULES_IN = {"all": types.InputPrivacyValueAllowAll, "contacts": types.InputPrivacyValueAllowContacts,
            "nobody": types.InputPrivacyValueDisallowAll}


def _rule_name(rules) -> str:
    names = {type(r).__name__ for r in rules}
    if "PrivacyValueAllowAll" in names:
        return "all"
    if "PrivacyValueAllowContacts" in names:
        return "contacts"
    return "nobody"


@routes.get("/api/privacy")
async def privacy_get(request):
    out = {}
    for k, key_cls in PRIVACY.items():
        res = await safe_call(cl(request).invoke, functions.account.GetPrivacy(key=key_cls()))
        out[k] = _rule_name(res.rules)
        await asyncio.sleep(0.3)
    return web.json_response(out)


@routes.post("/api/privacy")
async def privacy_set(request):
    d = await request.json()
    k, v = d.get("key"), d.get("value")
    if k not in PRIVACY or v not in RULES_IN:
        return bad("مقدار نامعتبر")
    await safe_call(cl(request).invoke, functions.account.SetPrivacy(key=PRIVACY[k](), rules=[RULES_IN[v]()]))
    return web.json_response({"ok": True})


# ---------- active sessions (devices) ----------
@routes.get("/api/sessions")
async def sessions(request):
    res = await safe_call(cl(request).invoke, functions.account.GetAuthorizations())
    return web.json_response([{
        "hash": str(a.hash), "current": bool(a.current), "device": a.device_model, "platform": a.platform,
        "app": f"{a.app_name} {a.app_version}", "ip": a.ip, "country": a.country, "active": a.date_active,
    } for a in res.authorizations])


@routes.post("/api/sessions/kill")
async def sessions_kill(request):
    h = int((await request.json()).get("hash"))
    if h == 0:
        return bad("نشست فعلی را نمی‌شود از اینجا بست")
    await safe_call(cl(request).invoke, functions.account.ResetAuthorization(hash=h))
    return web.json_response({"ok": True})


# ---------- group members ----------
STATUS = {"OWNER": "مالک", "ADMINISTRATOR": "ادمین", "MEMBER": "عضو", "RESTRICTED": "محدود", "BANNED": "بن", "LEFT": "خارج‌شده"}


@routes.get("/api/members/{chat}")
async def members(request):
    chat = await resolve_id(cl(request), request.match_info["chat"])
    q = request.query.get("q", "")
    out = []
    async for m in cl(request).get_chat_members(chat, query=q, limit=200):
        if m.user:
            out.append({"id": m.user.id, "name": _name(m.user), "username": m.user.username,
                        "bot": m.user.is_bot, "status": STATUS.get(m.status.name, m.status.name)})
    return web.json_response(out)


@routes.post("/api/members/action")
async def members_action(request):
    d, c = await request.json(), cl(request)
    chat, action = await resolve_id(c, d.get("chat")), d.get("action")
    ids = [int(i) for i in d.get("ids", [])][:100]
    funcs = {
        "ban": lambda u: c.ban_chat_member(chat, u),
        "unban": lambda u: c.unban_chat_member(chat, u),
        "kick": None,
        "mute": lambda u: c.restrict_chat_member(chat, u, ChatPermissions()),
        "unmute": lambda u: c.restrict_chat_member(chat, u, ChatPermissions(
            can_send_messages=True, can_send_media_messages=True, can_send_other_messages=True,
            can_add_web_page_previews=True, can_send_polls=True, can_invite_users=True)),
    }
    if action not in funcs or not ids:
        return bad("عملیات یا کاربر نامعتبر")
    ok, failed = 0, {}
    for u in ids:
        try:
            if action == "kick":
                await safe_call(c.ban_chat_member, chat, u)
                await asyncio.sleep(0.5)
                await safe_call(c.unban_chat_member, chat, u)
            else:
                await safe_call(funcs[action], u)
            ok += 1
        except Exception as e:
            failed[str(u)] = str(e)
        await asyncio.sleep(0.7)
    return web.json_response({"ok": ok, "failed": failed})


# ---------- simple config objects edited by the panel ----------
def _cfg(key: str, default: dict) -> dict:
    return store.get(key, default)


CONFIGS = {
    "antispam": ({"chats": [], "links": True, "forwards": True, "flood": 6},
                 {"chats": list, "links": bool, "forwards": bool, "flood": int}),
    "ai": ({"key": "", "model": "claude-haiku-5-5", "afk_ai": False, "prompt": ""},
           {"key": str, "model": str, "afk_ai": bool, "prompt": str}),
    "autobio": ({"on": False, "texts": [], "interval": 30},
                {"on": bool, "texts": list, "interval": int}),
}


@routes.get("/api/config/{key}")
async def config_get(request):
    key = request.match_info["key"]
    if key not in CONFIGS:
        raise web.HTTPNotFound()
    data = dict(_cfg(key, CONFIGS[key][0]))
    if key == "ai" and data.get("key"):
        data["key"] = "••••" + data["key"][-4:]  # never send the full API key back
    return web.json_response(data)


@routes.post("/api/config/{key}")
async def config_set(request):
    key = request.match_info["key"]
    if key not in CONFIGS:
        raise web.HTTPNotFound()
    default, schema = CONFIGS[key]
    cfg, d = _cfg(key, default), await request.json()
    for k, typ in schema.items():
        if k not in d:
            continue
        v = d[k]
        if key == "ai" and k == "key" and (not v or str(v).startswith("••••")):
            continue  # unchanged masked key
        try:
            if typ is list:
                v = [str(x).strip() for x in v if str(x).strip()]
            elif typ is bool:
                v = bool(v)
            else:
                v = typ(v)
        except (TypeError, ValueError):
            return bad(f"مقدار نامعتبر برای {k}")
        cfg[k] = v  # mutate in place: plugins hold the same dict
    if key == "autobio":
        cfg["interval"] = max(5, cfg["interval"])
    store.save()
    return web.json_response({"ok": True})


@routes.get("/api/welcome")
async def welcome_get(request):
    return web.json_response(store.get("welcome", {}))


@routes.post("/api/welcome")
async def welcome_set(request):
    d = await request.json()
    w = store.get("welcome", {})
    chat, text = str(d.get("chat", "")).strip(), str(d.get("text", "")).strip()
    if not chat:
        return bad("آیدی گروه لازم است")
    if text:
        w[chat] = text
    else:
        w.pop(chat, None)
    store.save()
    return web.json_response(w)


# ---------- AI ----------
@routes.post("/api/ai/summary")
async def ai_summary(request):
    from plugins import ai
    chat = chat_ref((await request.json()).get("chat"))
    lines = []
    async for m in cl(request).get_chat_history(chat, limit=150):
        t = m.text or m.caption
        if t:
            lines.append(f"{_name(m.from_user or m.sender_chat)}: {t}")
    if not lines:
        return bad("پیام متنی در این چت نیست")
    try:
        return web.json_response({"summary": await ai.summarize(lines[::-1])})
    except RuntimeError as e:
        return bad(str(e))


@routes.post("/api/ai/ask")
async def ai_ask(request):
    from plugins import ai
    q = str((await request.json()).get("q", "")).strip()
    if not q:
        return bad("سوال خالی است")
    try:
        return web.json_response({"answer": await ai.ask(q, "به فارسی جواب بده.")})
    except RuntimeError as e:
        return bad(str(e))


# ---------- plugins on/off ----------
@routes.get("/api/plugins")
async def plugins_get(request):
    from core.loader import disabled
    names = sorted(p.stem for p in config.PLUGINS_DIR.glob("*.py") if not p.name.startswith("_"))
    return web.json_response([{"name": n, "on": n not in disabled} for n in names])


@routes.post("/api/plugins")
async def plugins_set(request):
    from core.loader import disabled
    d = await request.json()
    name = str(d.get("name", ""))
    if not (config.PLUGINS_DIR / f"{name}.py").exists():
        return bad("پلاگین پیدا نشد")
    if d.get("on"):
        while name in disabled:
            disabled.remove(name)
    elif name not in disabled:
        disabled.append(name)
    store.save()
    return web.json_response({"ok": True})


# ---------- backup / restore ----------
@routes.get("/api/backup")
async def backup(request):
    data = json.loads(json.dumps(store.data))
    data.get("ai", {}).pop("key", None)  # keep secrets out of backup files
    body = json.dumps(data, ensure_ascii=False, indent=2)
    name = time.strftime("userbot-backup-%Y%m%d-%H%M.json")
    return web.Response(text=body, content_type="application/json",
                        headers={"Content-Disposition": f'attachment; filename="{name}"'})


@routes.post("/api/restore")
async def restore(request):
    try:
        data = await request.json()
        assert isinstance(data, dict)
    except Exception:
        return bad("فایل پشتیبان نامعتبر است")
    for k, v in data.items():
        cur = store.data.get(k)
        if isinstance(cur, dict) and isinstance(v, dict):
            keep = cur.get("key") if k == "ai" else None
            cur.clear()
            cur.update(v)  # in place: plugins keep their reference
            if keep and not cur.get("key"):
                cur["key"] = keep
        elif isinstance(cur, list) and isinstance(v, list):
            cur[:] = v
        else:
            store.data[k] = v
    store.save()
    return web.json_response({"ok": True, "keys": len(data)})


# ---------- restart ----------
@routes.post("/api/restart")
async def restart(request):
    c = cl(request)

    async def later():
        await asyncio.sleep(1)
        log.info("Restart requested from panel")
        try:
            await c.stop()
        finally:
            if os.getenv("USERBOT_SUPERVISED"):
                os._exit(0)  # run_forever.bat starts it again; execv here would make two copies
            os.execv(sys.executable, [sys.executable, str(Path(config.BASE_DIR) / "main.py")])

    asyncio.get_running_loop().create_task(later())
    return web.json_response({"ok": True})
