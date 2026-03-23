import logging
import sys
from datetime import datetime
from pathlib import Path

LOG_DIR: Path = Path(__file__).parent.parent / "logs"
_logger: logging.Logger | None = None


def get_logger() -> logging.Logger:
    global _logger
    if _logger:
        return _logger
    LOG_DIR.mkdir(parents=True, exist_ok=True)
    _logger = logging.getLogger("Tor-Link-Parser")
    _logger.setLevel(logging.DEBUG)

    fh = logging.FileHandler(LOG_DIR / f"Tor-Link-Parser_{datetime.now():%Y-%m-%d}.log", encoding="utf-8")
    fh.setLevel(logging.DEBUG)
    fh.setFormatter(logging.Formatter("%(asctime)s [%(levelname)s] %(message)s", datefmt="%H:%M:%S"))

    sh = logging.StreamHandler(sys.stdout)
    sh.setLevel(logging.INFO)
    sh.setFormatter(logging.Formatter("  %(message)s"))

    _logger.addHandler(fh)
    _logger.addHandler(sh)
    return _logger


def info(m: str) -> None:
    get_logger().info(m)

def warn(m: str) -> None:
    get_logger().warning(m)

def error(m: str) -> None:
    get_logger().error(m)

def debug(m: str) -> None:
    get_logger().debug(m)