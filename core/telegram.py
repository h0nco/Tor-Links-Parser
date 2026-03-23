import json
import threading
import time
from typing import Optional, Callable
from datetime import datetime

import requests

from core import config

_callback: Optional[Callable[[str], None]] = None
_poll_thread: Optional[threading.Thread] = None
_poll_stop: threading.Event = threading.Event()
_last_update_id: int = 0


def _tg() -> tuple[Optional[str], Optional[str]]:
    t: str = config.get("telegram", "token", "")
    c: str = config.get("telegram", "chat_id", "")
    return (t, c) if t and c else (None, None)


def tg_enabled() -> bool:
    t, c = _tg()
    return bool(t and c)


def _send(text: str) -> bool:
    t, c = _tg()
    if not t or not c:
        return False
    try:
        requests.post(f"https://api.telegram.org/bot{t}/sendMessage",
                      data={"chat_id": c, "text": text, "parse_mode": "HTML"}, timeout=10)
        return True
    except requests.RequestException:
        return False
    except Exception:
        return False


def send_site(data: dict) -> bool:
    now: str = datetime.utcnow().strftime("%Y-%m-%d %H:%M:%S UTC")
    m: dict = {
        "type": "site_found", "url": data.get("url", ""),
        "title": data.get("title", "") or "(none)", "category": data.get("category", ""),
        "language": data.get("language", "") or None,
        "ping_ms": data.get("response_time_ms", 0), "attempts": data.get("attempts", 1),
        "server": data.get("server_header", "") or None,
        "checked_at": now, "hash": data.get("content_hash", ""),
    }
    m = {k: v for k, v in m.items() if v is not None}
    return _send(f"<b>Tor-Link-Parser</b> | found\n<pre>{json.dumps(m, indent=2, ensure_ascii=False)}</pre>")


def send_batch(batch: list[dict]) -> bool:
    if not batch:
        return False
    now: str = datetime.utcnow().strftime("%Y-%m-%d %H:%M:%S UTC")
    on: list[dict] = [s for s in batch if s.get("status") == "online"]
    m: dict = {"type": "batch", "total": len(batch), "online": len(on),
               "offline": len(batch) - len(on), "time": now}
    if on:
        m["avg_ping"] = round(sum(s.get("response_time_ms", 0) for s in on) / len(on))
        m["sites"] = [{"url": s["url"], "title": s.get("title", "") or "(none)",
                        "cat": s.get("category", ""), "ms": s.get("response_time_ms", 0)} for s in on]
    txt: str = f"<b>Tor-Link-Parser</b> | batch\n<pre>{json.dumps(m, indent=2, ensure_ascii=False)}</pre>"
    return _send(txt[:4000] + "</pre>" if len(txt) > 4000 else txt)


def send_status(stats: dict, running: bool, mon: bool) -> bool:
    m: dict = {"type": "status", "scanner": "running" if running else "stopped",
               "monitor": "on" if mon else "off", "db": stats}
    return _send(f"<b>Tor-Link-Parser</b> | status\n<pre>{json.dumps(m, indent=2, ensure_ascii=False)}</pre>")


def send_text(t: str) -> bool:
    return _send(t)


def send_monitor_alert(off: list[dict], on: list[dict]) -> bool:
    m: dict = {"type": "monitor", "time": datetime.utcnow().strftime("%Y-%m-%d %H:%M:%S UTC")}
    if on:
        m["back_online"] = [{"url": s["url"], "title": s.get("title", "")} for s in on]
    if off:
        m["went_offline"] = [s["url"] for s in off]
    return _send(f"<b>Tor-Link-Parser</b> | monitor\n<pre>{json.dumps(m, indent=2, ensure_ascii=False)}</pre>")


def set_callback(cb: Callable[[str], None]) -> None:
    global _callback
    _callback = cb


def start_polling() -> bool:
    global _poll_thread
    t, c = _tg()
    if not t or not c:
        return False
    _poll_stop.clear()
    _poll_thread = threading.Thread(target=_loop, args=(t, c), daemon=True)
    _poll_thread.start()
    return True


def stop_polling() -> None:
    _poll_stop.set()


def _loop(token: str, cid: str) -> None:
    global _last_update_id
    while not _poll_stop.is_set():
        try:
            r = requests.get(f"https://api.telegram.org/bot{token}/getUpdates",
                             params={"offset": _last_update_id + 1, "timeout": 5}, timeout=10)
            for u in r.json().get("result", []):
                _last_update_id = u["update_id"]
                msg = u.get("message", {})
                if str(msg.get("chat", {}).get("id")) == str(cid):
                    text: str = msg.get("text", "").strip()
                    if text and _callback:
                        _callback(text)
        except requests.RequestException:
            pass
        except Exception:
            pass
        time.sleep(1)