"""Central configuration. Loads values from .env (never hardcode secrets)."""
import os
import sys
from pathlib import Path

from dotenv import load_dotenv

BASE_DIR = Path(__file__).resolve().parent
load_dotenv(BASE_DIR / ".env")  # read .env next to this file


def _require(name: str) -> str:
    """Return env var or exit with a clear message."""
    value = os.getenv(name, "").strip()
    if not value:
        sys.exit(f"[config] Missing required env var: {name} (see .env.example)")
    return value


API_ID: int = int(_require("API_ID"))
API_HASH: str = _require("API_HASH")

# String session wins if set; otherwise a file session is used
SESSION_STRING: str | None = os.getenv("SESSION_STRING", "").strip() or None
SESSION_NAME: str = os.getenv("SESSION_NAME", "userbot").strip()

# Multiple prefixes allowed: CMD_PREFIX=". !"
CMD_PREFIXES: list[str] = os.getenv("CMD_PREFIX", ".").split() or ["."]

LOG_LEVEL: str = os.getenv("LOG_LEVEL", "INFO").upper()
LOG_FILE: str = os.getenv("LOG_FILE", "userbot.log")

AFK_COOLDOWN: int = int(os.getenv("AFK_COOLDOWN", "600"))


def _parse_proxy(url: str) -> dict | None:
    """PROXY=socks5://user:pass@127.0.0.1:1080  ->  Pyrogram proxy dict."""
    if not url:
        return None
    from urllib.parse import urlparse
    u = urlparse(url)
    if u.scheme not in ("socks5", "socks4", "http") or not u.hostname or not u.port:
        sys.exit(f"[config] Bad PROXY value: {url!r} (example: socks5://127.0.0.1:1080)")
    proxy = {"scheme": u.scheme, "hostname": u.hostname, "port": u.port}
    if u.username:
        proxy["username"] = u.username
        proxy["password"] = u.password or ""
    return proxy


# Optional proxy, needed where Telegram is filtered
PROXY_URL: str = os.getenv("PROXY", "").strip()
PROXY: dict | None = _parse_proxy(PROXY_URL)

# Web panel. Empty password = panel disabled.
PANEL_PASSWORD: str = os.getenv("PANEL_PASSWORD", "").strip()
PANEL_HOST: str = os.getenv("PANEL_HOST", "127.0.0.1").strip()
PANEL_PORT: int = int(os.getenv("PANEL_PORT", "8080"))
# Optional HTTPS for the panel (needed if you open it from your phone over the internet)
PANEL_CERT: str = os.getenv("PANEL_CERT", "").strip()
PANEL_KEY: str = os.getenv("PANEL_KEY", "").strip()

PLUGINS_DIR: Path = BASE_DIR / "plugins"
SESSIONS_DIR: Path = BASE_DIR / "sessions"
DATA_DIR: Path = BASE_DIR / "data"
SESSIONS_DIR.mkdir(exist_ok=True)
DATA_DIR.mkdir(exist_ok=True)
