import json
from pathlib import Path
from typing import Any, Optional

_cfg: Optional[dict] = None
CONFIG_PATH: Path = Path(__file__).parent.parent / "config.json"


def load() -> dict:
    global _cfg
    if _cfg is None:
        try:
            with open(CONFIG_PATH, "r", encoding="utf-8") as f:
                _cfg = json.load(f)
        except FileNotFoundError:
            from core.log import error
            error(f"config.json not found at {CONFIG_PATH}")
            _cfg = {}
        except json.JSONDecodeError as e:
            from core.log import error
            error(f"config.json parse error: {e}")
            _cfg = {}
    return _cfg


def get(section: str, key: Optional[str] = None, default: Any = None) -> Any:
    c = load()
    if key is None:
        return c.get(section, default)
    return c.get(section, {}).get(key, default)