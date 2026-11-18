"""Tiny JSON key-value store shared by plugins and the web panel.

store.get(key, default) returns the SAME mutable object every time, so a
change made by the panel is seen by plugins immediately. Call store.save()
after mutating. Writes are atomic (temp file + replace).
"""
import copy
import json
import logging
import os

import config

log = logging.getLogger("userbot.store")


class Store:
    def __init__(self, path):
        self.path = path
        self.data: dict = {}
        if path.exists():
            try:
                self.data = json.loads(path.read_text(encoding="utf-8"))
            except Exception:
                log.warning("%s is corrupt, starting empty", path)

    def get(self, key: str, default=None):
        """Return stored value; create it from default if missing."""
        if key not in self.data:
            self.data[key] = copy.deepcopy(default)
        elif isinstance(default, dict) and isinstance(self.data[key], dict):
            for k, v in default.items():  # add new default fields after upgrades
                self.data[key].setdefault(k, copy.deepcopy(v))
        return self.data[key]

    def save(self) -> None:
        tmp = self.path.with_suffix(".tmp")
        tmp.write_text(json.dumps(self.data, ensure_ascii=False, indent=2), encoding="utf-8")
        os.replace(tmp, self.path)


store = Store(config.DATA_DIR / "store.json")

# Global toggles used by several plugins and the panel
SETTINGS_DEFAULT = {
    "clock": False,       # show time in last name
    "clock_fa": True,     # Persian digits for the clock
    "panel_2fa": False,   # panel login also needs a code sent to Saved Messages
}


def settings() -> dict:
    return store.get("settings", SETTINGS_DEFAULT)


def chat_ref(value):
    """'-100123' -> int, '@user' / 'me' stay strings."""
    v = str(value).strip()
    return int(v) if v.lstrip("-").isdigit() else v
