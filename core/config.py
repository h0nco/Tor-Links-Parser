import json
from pathlib import Path

_cfg = None
CONFIG_PATH = Path(__file__).parent.parent / "config.json"

def load():
    global _cfg
    if _cfg is None:
        with open(CONFIG_PATH, "r", encoding="utf-8") as f:
            _cfg = json.load(f)
    return _cfg

def get(section, key=None, default=None):
    c = load()
    if key is None:
        return c.get(section, default)
    return c.get(section, {}).get(key, default)