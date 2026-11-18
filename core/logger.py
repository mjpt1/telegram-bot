"""Logging setup: console + rotating file, millisecond timestamps."""
import logging
from logging.handlers import RotatingFileHandler

FMT = "%(asctime)s.%(msecs)03d | %(levelname)-8s | %(name)s | %(message)s"
DATEFMT = "%Y-%m-%d %H:%M:%S"


def setup_logging(level: str = "INFO", logfile: str | None = None) -> None:
    root = logging.getLogger()
    root.setLevel(level)
    formatter = logging.Formatter(FMT, DATEFMT)

    console = logging.StreamHandler()
    console.setFormatter(formatter)
    root.addHandler(console)

    if logfile:
        # 5 MB per file, keep 3 old files
        fh = RotatingFileHandler(logfile, maxBytes=5_000_000, backupCount=3, encoding="utf-8")
        fh.setFormatter(formatter)
        root.addHandler(fh)

    # Pyrogram internals are noisy at INFO
    logging.getLogger("pyrogram").setLevel(logging.WARNING)
