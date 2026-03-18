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
    patterns = []
    with open(IGNORE_FILE, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip().lower()
            if line and not line.startswith("#"):
                patterns.append(line)
    _cache = patterns
    return _cache


def reload_ignore_list():
    global _cache
    _cache = None
    return load_ignore_list()


def is_title_ignored(title):
    if not title:
        return False
    t = title.lower().strip()
    for pattern in load_ignore_list():
        if pattern in t:
            return True
    return False