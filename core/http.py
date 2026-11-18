"""aiohttp session; by default goes through the same proxy as Telegram."""
import aiohttp

import config


def session(use_proxy: bool = True, timeout: int = 20) -> aiohttp.ClientSession:
    """use_proxy=False for Iranian services that block foreign IPs."""
    connector = None
    if use_proxy and config.PROXY_URL:
        from aiohttp_socks import ProxyConnector
        connector = ProxyConnector.from_url(config.PROXY_URL)
    return aiohttp.ClientSession(connector=connector, timeout=aiohttp.ClientTimeout(total=timeout),
                                 headers={"User-Agent": "curl/8.5.0"})  # wttr.in returns plain text for curl
