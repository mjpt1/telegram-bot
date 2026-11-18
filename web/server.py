"""Web panel backend. Runs inside the bot's asyncio loop, shares core.store.

Security:
- Binds to 127.0.0.1 by default (only this computer can open it).
- Password from PANEL_PASSWORD; session token in an HttpOnly cookie.
- Every /api/* route except /api/login needs a valid token.
"""
import asyncio
import hmac
import logging
import platform
import secrets
import time
from pathlib import Path

from aiohttp import web
from pyrogram import Client

import config
from core import chat_ref, safe_call, settings, state, store
from core.decorators import COMMANDS

log = logging.getLogger("userbot.panel")
HERE = Path(__file__).parent
TOKENS: set[str] = set()
COOKIE = "ub_token"

# Lists editable from the panel: key -> required fields
LISTS = {
    "autoreplies": ("keyword", "reply"),
    "schedules": ("chat", "text", "at"),
    "forwards": ("source", "target"),
    "templates": ("name", "text"),
}

routes = web.RouteTableDef()


@web.middleware
async def auth(request: web.Request, handler):
    if request.path.startswith("/api/") and request.path not in ("/api/login", "/api/login/code"):
        if request.cookies.get(COOKIE) not in TOKENS:
            return web.json_response({"error": "ابتدا وارد شوید"}, status=401)
    try:
        return await handler(request)
    except web.HTTPException:
        raise
    except Exception as e:
        log.exception("panel error")
        return web.json_response({"error": str(e)}, status=500)


def client(request) -> Client:
    return request.app["client"]


@routes.get("/")
async def index(request):
    return web.FileResponse(HERE / "index.html")


@routes.post("/api/login")
async def login(request):
    data = await request.json()
    if not hmac.compare_digest(str(data.get("password", "")), config.PANEL_PASSWORD):
        await asyncio.sleep(1.5)  # slow down guessing
        return web.json_response({"error": "رمز اشتباه است"}, status=403)
    if settings().get("panel_2fa"):
        # Second step: a one-time code goes to the owner's Saved Messages
        code = f"{secrets.randbelow(10**6):06d}"
        PENDING.update(code=code, exp=time.time() + 300, tries=0)
        await safe_call(client(request).send_message, "me",
                        f"🔐 کد ورود پنل سلف‌بات: `{code}`\nاگر خودت نبودی، رمز پنل را عوض کن.")
        return web.json_response({"need_code": True})
    return _session_response()


PENDING: dict = {"code": None, "exp": 0, "tries": 0}


def _session_response():
    token = secrets.token_urlsafe(32)
    TOKENS.add(token)
    resp = web.json_response({"ok": True})
    resp.set_cookie(COOKIE, token, httponly=True, samesite="Strict", max_age=7 * 86400,
                    secure=bool(config.PANEL_CERT))
    return resp


@routes.post("/api/login/code")
async def login_code(request):
    data = await request.json()
    if not PENDING["code"] or time.time() > PENDING["exp"] or PENDING["tries"] >= 5:
        PENDING["code"] = None
        return web.json_response({"error": "کد منقضی شده؛ دوباره رمز را وارد کن"}, status=403)
    PENDING["tries"] += 1
    if not hmac.compare_digest(str(data.get("code", "")).strip(), PENDING["code"]):
        await asyncio.sleep(1.5)
        return web.json_response({"error": "کد اشتباه است"}, status=403)
    PENDING["code"] = None
    return _session_response()


@routes.post("/api/logout")
async def logout(request):
    TOKENS.discard(request.cookies.get(COOKIE))
    resp = web.json_response({"ok": True})
    resp.del_cookie(COOKIE)
    return resp


@routes.get("/api/status")
async def status(request):
    me = await client(request).get_me()
    afk = store.get("afk", {})
    return web.json_response({
        "name": f"{me.first_name or ''} {me.last_name or ''}".strip(),
        "username": me.username, "id": me.id,
        "uptime": int(time.time() - state.START_TIME),
        "python": platform.python_version(),
        "plugins": state.PLUGINS,
        "commands": [{"name": k, "desc": v, "prefix": config.CMD_PREFIXES[0]} for k, v in sorted(COMMANDS.items())],
        "afk": afk.get("on", False),
        "counts": {k: len(store.get(k, [])) for k in LISTS},
    })


@routes.get("/api/afk")
async def afk_get(request):
    return web.json_response(store.get("afk", {}))


@routes.post("/api/afk")
async def afk_set(request):
    from plugins.afk import set_afk  # same function the .afk command uses
    data = await request.json()
    set_afk(bool(data.get("on")), (data.get("reason") or "").strip() or None)
    return web.json_response(store.get("afk", {}))


@routes.get("/api/settings")
async def settings_get(request):
    return web.json_response(settings())


@routes.post("/api/settings")
async def settings_set(request):
    data = await request.json()
    s = settings()
    for k, v in data.items():
        if k in s and isinstance(v, type(s[k])):  # only known keys, same type
            s[k] = v
    store.save()
    return web.json_response(s)


@routes.get("/api/list/{key}")
async def list_get(request):
    key = request.match_info["key"]
    if key not in LISTS:
        raise web.HTTPNotFound()
    return web.json_response(store.get(key, []))


@routes.post("/api/list/{key}")
async def list_add(request):
    key = request.match_info["key"]
    if key not in LISTS:
        raise web.HTTPNotFound()
    data = await request.json()
    missing = [f for f in LISTS[key] if str(data.get(f, "")).strip() == ""]
    if missing:
        return web.json_response({"error": "فیلدهای خالی: " + ", ".join(missing)}, status=400)
    item = {"id": secrets.token_hex(4)}
    for f in LISTS[key]:
        item[f] = data[f] if f == "at" else str(data[f]).strip()
    if key == "schedules":
        item["at"] = float(data["at"])
        item["repeat"] = max(0, int(float(data.get("repeat") or 0))) * 60  # minutes -> seconds
        if item["repeat"] and item["repeat"] < 300:
            return web.json_response({"error": "حداقل فاصله تکرار ۵ دقیقه است"}, status=400)
    if key == "autoreplies":
        item["exact"] = bool(data.get("exact"))
        item["scope"] = "all" if data.get("scope") == "all" else "private"
    store.get(key, []).append(item)  # same list object plugins use
    store.save()
    return web.json_response(item)


@routes.delete("/api/list/{key}/{id}")
async def list_del(request):
    key, item_id = request.match_info["key"], request.match_info["id"]
    if key not in LISTS:
        raise web.HTTPNotFound()
    items = store.get(key, [])
    items[:] = [i for i in items if i.get("id") != item_id]  # mutate in place
    store.save()
    return web.json_response({"ok": True})


@routes.get("/api/dialogs")
async def dialogs(request):
    from core.chatops import list_chats
    return web.json_response((await list_chats(client(request)))[:50])  # shared cache


@routes.post("/api/send")
async def send(request):
    data = await request.json()
    chat, text = str(data.get("chat", "")).strip(), str(data.get("text", "")).strip()
    if not chat or not text:
        return web.json_response({"error": "چت و متن لازم است"}, status=400)
    msg = await safe_call(client(request).send_message, chat_ref(chat), text)
    return web.json_response({"ok": True, "id": msg.id})


@routes.get("/api/notes")
async def notes_get(request):
    return web.json_response(store.get("notes", {}))


@routes.post("/api/notes")
async def notes_set(request):
    data = await request.json()
    name, text = str(data.get("name", "")).strip().lower(), str(data.get("text", "")).strip()
    if not name or not text:
        return web.json_response({"error": "اسم و متن لازم است"}, status=400)
    store.get("notes", {})[name] = text
    store.save()
    return web.json_response({"ok": True})


@routes.delete("/api/notes/{name}")
async def notes_del(request):
    store.get("notes", {}).pop(request.match_info["name"], None)
    store.save()
    return web.json_response({"ok": True})


@routes.get("/api/filter")
async def filter_get(request):
    return web.json_response(store.get("wordfilter", {"words": [], "chats": []}))


@routes.post("/api/filter")
async def filter_set(request):
    data = await request.json()
    cfg = store.get("wordfilter", {"words": [], "chats": []})
    for key in ("words", "chats"):
        if isinstance(data.get(key), list):
            cfg[key] = [str(x).strip() for x in data[key] if str(x).strip()]
    store.save()
    return web.json_response(cfg)


@routes.get("/api/stats")
async def stats_get(request):
    from plugins import stats as st
    d = await st.dialog_stats(client(request))
    return web.json_response({**d, "sent": st.counters["sent"], "received": st.counters["received"],
                              "top": st.top_chats(8)})


@routes.get("/api/chats")
async def chats_get(request):
    from core.chatops import list_chats
    force = request.query.get("force") == "1"  # "refresh" button
    return web.json_response(await list_chats(client(request), force=force))


@routes.post("/api/chats/action")
async def chats_action(request):
    from core.chatops import ACTIONS, run_action
    data = await request.json()
    action = data.get("action")
    if action not in ACTIONS:
        return web.json_response({"error": "عملیات نامعتبر"}, status=400)
    try:
        ids = [int(i) for i in data.get("ids", [])]
    except (TypeError, ValueError):
        return web.json_response({"error": "آیدی نامعتبر"}, status=400)
    if not ids:
        return web.json_response({"error": "هیچ چتی انتخاب نشده"}, status=400)
    if len(ids) > 300:
        return web.json_response({"error": "حداکثر ۳۰۰ چت در هر بار"}, status=400)
    result = await run_action(client(request), action, ids)
    return web.json_response({"ok": result["ok"], "failed": {str(k): v for k, v in result["failed"].items()}})


@routes.get("/api/logs")
async def logs(request):
    path = Path(config.LOG_FILE)
    if not path.is_absolute():
        path = config.BASE_DIR / path
    if not path.exists():
        return web.json_response({"lines": []})
    lines = path.read_text(encoding="utf-8", errors="replace").splitlines()[-200:]
    return web.json_response({"lines": lines})


async def start_panel(app_client: Client) -> web.AppRunner:
    from web.extra import routes as extra_routes
    from web.extra2 import routes as extra2_routes
    app = web.Application(middlewares=[auth], client_max_size=60 * 1024 * 1024)  # uploads up to 50 MB
    app["client"] = app_client
    app.add_routes(routes)
    app.add_routes(extra_routes)
    app.add_routes(extra2_routes)
    runner = web.AppRunner(app, access_log=None)
    await runner.setup()
    ssl_ctx = None
    if config.PANEL_CERT and config.PANEL_KEY:
        import ssl
        ssl_ctx = ssl.create_default_context(ssl.Purpose.CLIENT_AUTH)
        ssl_ctx.load_cert_chain(config.PANEL_CERT, config.PANEL_KEY)
    await web.TCPSite(runner, config.PANEL_HOST, config.PANEL_PORT, ssl_context=ssl_ctx).start()
    log.info("Web panel: %s://%s:%s", "https" if ssl_ctx else "http", config.PANEL_HOST, config.PANEL_PORT)
    if config.PANEL_HOST not in ("127.0.0.1", "localhost"):
        log.warning("Panel is reachable from the network. Use a strong PANEL_PASSWORD, HTTPS and panel_2fa.")
        if not ssl_ctx:
            log.warning("Panel has no HTTPS: password travels in plain text on the network.")
    return runner
