import json, threading, time, requests
from datetime import datetime
from core import config

_callback = None
_poll_thread = None
_poll_stop = threading.Event()
_last_update_id = 0

def _tg():
    t = config.get("telegram","token","")
    c = config.get("telegram","chat_id","")
    return (t,c) if t and c else (None,None)

def tg_enabled():
    t,c = _tg()
    return bool(t and c)

def _send(text):
    t,c = _tg()
    if not t: return False
    try:
        requests.post(f"https://api.telegram.org/bot{t}/sendMessage", data={"chat_id":c,"text":text,"parse_mode":"HTML"}, timeout=10)
        return True
    except: return False

def send_site(data):
    now = datetime.utcnow().strftime("%Y-%m-%d %H:%M:%S UTC")
    m = {"type":"site_found","url":data.get("url",""),"title":data.get("title","") or "(none)","category":data.get("category",""),
         "language":data.get("language","") or None,"ping_ms":data.get("response_time_ms",0),"attempts":data.get("attempts",1),
         "server":data.get("server_header","") or None,"checked_at":now,"hash":data.get("content_hash","")}
    m = {k:v for k,v in m.items() if v is not None}
    return _send(f"<b>ghTor</b> | found\n<pre>{json.dumps(m,indent=2,ensure_ascii=False)}</pre>")

def send_batch(batch):
    if not batch: return False
    now = datetime.utcnow().strftime("%Y-%m-%d %H:%M:%S UTC")
    on = [s for s in batch if s.get("status")=="online"]
    m = {"type":"batch","total":len(batch),"online":len(on),"offline":len(batch)-len(on),"time":now}
    if on:
        m["avg_ping"] = round(sum(s.get("response_time_ms",0) for s in on)/len(on))
        m["sites"] = [{"url":s["url"],"title":s.get("title","") or "(none)","cat":s.get("category",""),"ms":s.get("response_time_ms",0)} for s in on]
    txt = f"<b>ghTor</b> | batch\n<pre>{json.dumps(m,indent=2,ensure_ascii=False)}</pre>"
    return _send(txt[:4000]+"</pre>" if len(txt)>4000 else txt)

def send_status(stats, running, mon):
    m = {"type":"status","scanner":"running" if running else "stopped","monitor":"on" if mon else "off","db":stats}
    return _send(f"<b>ghTor</b> | status\n<pre>{json.dumps(m,indent=2,ensure_ascii=False)}</pre>")

def send_text(t): return _send(t)

def send_monitor_alert(off, on):
    m = {"type":"monitor","time":datetime.utcnow().strftime("%Y-%m-%d %H:%M:%S UTC")}
    if on: m["back_online"] = [{"url":s["url"],"title":s.get("title","")} for s in on]
    if off: m["went_offline"] = [s["url"] for s in off]
    return _send(f"<b>ghTor</b> | monitor\n<pre>{json.dumps(m,indent=2,ensure_ascii=False)}</pre>")

def set_callback(cb):
    global _callback; _callback = cb

def start_polling():
    global _poll_thread
    t,c = _tg()
    if not t: return False
    _poll_stop.clear()
    _poll_thread = threading.Thread(target=_loop, args=(t,c), daemon=True)
    _poll_thread.start()
    return True

def stop_polling(): _poll_stop.set()

def _loop(token, cid):
    global _last_update_id
    while not _poll_stop.is_set():
        try:
            r = requests.get(f"https://api.telegram.org/bot{token}/getUpdates", params={"offset":_last_update_id+1,"timeout":5}, timeout=10)
            for u in r.json().get("result",[]):
                _last_update_id = u["update_id"]
                msg = u.get("message",{})
                if str(msg.get("chat",{}).get("id")) == str(cid):
                    t = msg.get("text","").strip()
                    if t and _callback: _callback(t)
        except: pass
        time.sleep(1)