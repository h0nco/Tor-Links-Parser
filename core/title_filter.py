from pathlib import Path

IGNORE_FILE = Path(__file__).parent.parent / "ignore_titles.txt"
_cache = None

def load_ignore_list():
    global _cache
    if _cache is not None:
        return _cache
    if not IGNORE_FILE.exists():
        _cache = []
        return _cache
    _cache = [l.strip().lower() for l in IGNORE_FILE.read_text(encoding="utf-8").splitlines() if l.strip() and not l.startswith("#")]
    return _cache

def is_title_ignored(title):
    if not title:
        return False
    t = title.lower().strip()
    return any(p in t for p in load_ignore_list())