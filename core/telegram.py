import json
import threading
import time
import requests
from datetime import datetime
from core import config

_callback = None
_poll_thread = None
_poll_stop = threading.Event()
_last_update_id = 0


def _get_tg():
    t = config.get("telegram", "token", "")
    c = config.get("telegram", "chat_id", "")
    return (t, c) if t and c else (None, None)


def _send(text, parse_mode="HTML"):
    token, chat_id = _get_tg()
    if not token:
        return False
    try:
        requests.post(f"https://api.telegram.org/bot{token}/sendMessage",
                      data={"chat_id": chat_id, "text": text, "parse_mode": parse_mode}, timeout=10)
        return True
    except Exception:
        return False


def tg_enabled():
    t, c = _get_tg()
    return bool(t and c)


def send_site_found(data):
    now = datetime.utcnow().strftime("%Y-%m-%d %H:%M:%S UTC")
    msg = {
        "type": "site_found", "url": data.get("url", ""),
        "title": data.get("title", "") or "(none)", "category": data.get("category", ""),
        "language": data.get("language", "") or None,
        "duplicate_of": data.get("duplicate_of", "") or None,
        "crawled_links": data.get("crawled_count", 0) or None,
        "ping_ms": data.get("response_time_ms", 0), "attempts": data.get("attempts", 1),
        "server": data.get("server_header", "") or None,
        "checked_at": now, "hash": data.get("content_hash", ""),
    }
    msg = {k: v for k, v in msg.items() if v is not None}
    return _send(f"<b>ghTor</b> | site found\n<pre>{json.dumps(msg, indent=2, ensure_ascii=False)}</pre>")


def send_batch_report(batch):
    if not batch:
        return False
    now = datetime.utcnow().strftime("%Y-%m-%d %H:%M:%S UTC")
    online = [s for s in batch if s.get("status") == "online"]
    msg = {"type": "batch_report", "total_checked": len(batch), "online": len(online),
           "offline": len(batch) - len(online), "report_time": now}
    if online:
        msg["avg_ping_ms"] = round(sum(s.get("response_time_ms", 0) for s in online) / len(online))
        msg["sites"] = [{"url": s["url"], "title": s.get("title","") or "(none)", "category": s.get("category",""), "ping_ms": s.get("response_time_ms",0)} for s in online]
    text = f"<b>ghTor</b> | batch\n<pre>{json.dumps(msg, indent=2, ensure_ascii=False)}</pre>"
    if len(text) > 4000:
        text = text[:4000] + "</pre>"
    return _send(text)


def send_status(stats, running, monitor_on):
    msg = {"type": "status", "scanner": "running" if running else "stopped", "monitor": "on" if monitor_on else "off", "db": stats}
    return _send(f"<b>ghTor</b> | status\n<pre>{json.dumps(msg, indent=2, ensure_ascii=False)}</pre>")


def send_text(text):
    return _send(text)


def send_monitor_alert(went_off, came_on):
    msg = {"type": "monitor", "time": datetime.utcnow().strftime("%Y-%m-%d %H:%M:%S UTC")}
    if came_on:
        msg["back_online"] = [{"url": s["url"], "title": s.get("title","")} for s in came_on]
    if went_off:
        msg["went_offline"] = [s["url"] for s in went_off]
    return _send(f"<b>ghTor</b> | monitor\n<pre>{json.dumps(msg, indent=2, ensure_ascii=False)}</pre>")


def set_command_callback(cb):
    global _callback
    _callback = cb


def start_polling():
    global _poll_thread
    token, chat_id = _get_tg()
    if not token:
        return False
    _poll_stop.clear()
    _poll_thread = threading.Thread(target=_poll_loop, args=(token, chat_id), daemon=True)
    _poll_thread.start()
    return True


def stop_polling():
    _poll_stop.set()


def _poll_loop(token, chat_id):
    global _last_update_id
    while not _poll_stop.is_set():
        try:
            r = requests.get(f"https://api.telegram.org/bot{token}/getUpdates",
                             params={"offset": _last_update_id + 1, "timeout": 5}, timeout=10)
            for u in r.json().get("result", []):
                _last_update_id = u["update_id"]
                msg = u.get("message", {})
                if str(msg.get("chat", {}).get("id")) == str(chat_id):
                    text = msg.get("text", "").strip()
                    if text and _callback:
                        _callback(text)
        except Exception:
            pass
        time.sleep(1)