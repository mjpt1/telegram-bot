"""Runtime info shared between core, plugins and the panel."""
import time

START_TIME: float = time.time()
PLUGINS: list[str] = []
