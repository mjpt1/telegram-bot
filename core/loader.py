"""Dynamic plugin loader (importlib).

Every *.py in plugins/ whose name does not start with "_" is imported.
Each coroutine function carrying __userbot_handlers__ becomes a handler.
A module-level `async def on_start(client)` runs as a background task after login.
A broken plugin is logged and skipped; it never stops the bot.
Disable a plugin by renaming it to _name.py.
"""
import functools
import importlib
import inspect
import logging
import sys
from pathlib import Path

from pyrogram import Client

from . import state
from .decorators import ATTR
from .storage import store

# Plugin names switched off from the panel. Their handlers stay registered
# but return at once, so toggling needs no restart.
disabled: list = store.get("disabled_plugins", [])


def _gate(name: str, func):
    @functools.wraps(func)
    async def wrapper(*args, **kwargs):
        if name in disabled:
            return
        return await func(*args, **kwargs)
    return wrapper

log = logging.getLogger("userbot.loader")


def load_plugins(app: Client, plugins_dir: Path) -> list:
    """Register handlers; return list of on_start hooks."""
    hooks = []
    package = plugins_dir.name  # "plugins"
    if str(plugins_dir.parent) not in sys.path:
        sys.path.insert(0, str(plugins_dir.parent))

    for path in sorted(plugins_dir.glob("*.py")):
        if path.name.startswith("_"):
            continue  # skip __init__.py and disabled plugins
        mod_name = f"{package}.{path.stem}"
        try:
            module = importlib.import_module(mod_name)
        except Exception:
            log.exception("Failed to import plugin %s - skipped", mod_name)
            continue

        count = 0
        for _, obj in inspect.getmembers(module, inspect.iscoroutinefunction):
            for handler_cls, flt, group in getattr(obj, ATTR, []):
                cb = _gate(path.stem, obj)
                app.add_handler(handler_cls(cb, flt) if flt is not None else handler_cls(cb), group)
                count += 1
        hook = getattr(module, "on_start", None)
        if inspect.iscoroutinefunction(hook):
            hooks.append(hook)
        state.PLUGINS.append(path.stem)
        log.info("Plugin loaded: %-10s (%d handlers%s)", path.stem, count, ", on_start" if hook else "")
    return hooks
