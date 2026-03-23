from pathlib import Path
from typing import Optional

IGNORE_FILE: Path = Path(__file__).parent.parent / "ignore_titles.txt"
_cache: Optional[list[str]] = None


def load_ignore_list() -> list[str]:
    global _cache
    if _cache is not None:
        return _cache
    if not IGNORE_FILE.exists():
        _cache = []
        return _cache
    try:
        _cache = [l.strip().lower() for l in IGNORE_FILE.read_text(encoding="utf-8").splitlines()
                  if l.strip() and not l.startswith("#")]
    except OSError:
        _cache = []
    return _cache


def is_title_ignored(title: str) -> bool:
    if not title:
        return False
    t: str = title.lower().strip()
    return any(p in t for p in load_ignore_list())