import sys
import os
import json
import time
import signal
import atexit
import threading
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime
from pathlib import Path

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from core import config
from core.database import Database
from core.checker import check_site, find_tor_port, make_session, renew_circuit, test_tor_connection
from core.categorizer import categorize
from core.discovery import discover, get_sources
from core.language import detect_language
from core.telegram import send_site_found, send_batch_report, send_status, send_text, tg_enabled, set_command_callback, start_polling, stop_polling
from core.monitor import Monitor
from core.title_filter import is_title_ignored
from core.rate_limit import RateLimiter
from core.lang import t, set_lang, S
from core import log

LINKS_FILE = Path(__file__).parent / "links.txt"
EXPORT_DIR = Path(__file__).parent / config.get("export", "dir", "data")
db = Database()
tor_sessions = []
tor_port = None
total_checked = 0
total_found = 0
total_ignored = 0
lk = threading.Lock()
stop_event = threading.Event()
crawl_queue = []
crawl_lock = threading.Lock()
monitor = None
limiter = None
circuit_counter = 0
scanning_active = False
_shutdown_done = False


def auto_export():
    global _shutdown_done
    if _shutdown_done:
        return
    _shutdown_done = True
    if not config.get("export", "auto_export", True):
        return
    EXPORT_DIR.mkdir(parents=True, exist_ok=True)
    data = db.export_json()
    if not data:
        return
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    path = EXPORT_DIR / f"export_{ts}.json"
    with open(path, "w", encoding="utf-8") as f:
        json.dump({"exported_at": datetime.utcnow().isoformat(), "total": len(data), "sites": data}, f, indent=2, ensure_ascii=False)
    log.info(t("exported", len(data), path))


def graceful_shutdown(signum=None, frame=None):
    log.info("Shutdown signal received")
    stop_event.set()
    if monitor and monitor.running:
        monitor.stop()
    stop_polling()
    auto_export()
    sys.exit(0)


atexit.register(auto_export)
signal.signal(signal.SIGINT, graceful_shutdown)
signal.signal(signal.SIGTERM, graceful_shutdown)


def load_links():
    if not LINKS_FILE.exists():
        return []
    urls = []
    with open(LINKS_FILE, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            if not line.startswith("http"):
                line = "http://" + line
            if ".onion" in line:
                urls.append(line)
    seen = set()
    return [u for u in urls if u not in seen and not seen.add(u)]


def maybe_rotate():
    global circuit_counter
    every = config.get("tor", "circuit_rotate_every", 50)
    with lk:
        circuit_counter += 1
        if circuit_counter % every == 0:
            if renew_circuit(tor_port):
                log.debug(t("circuit", circuit_counter))


def print_stats():
    s = db.get_stats()
    cq = len(crawl_queue)
    mon = t("on") if monitor and monitor.running else t("off")
    log.info(t("stats_fmt", total_checked, total_found, s.get("online",0) or 0, s.get("offline",0) or 0, s.get("total",0) or 0, cq, mon))


def process_url(url, session, timeout, retries, silent_offline=False):
    global total_checked, total_found, total_ignored

    if stop_event.is_set():
        return None

    if limiter:
        limiter.acquire()
    maybe_rotate()
    result = check_site(url, session, timeout, retries, config.get("tor", "retry_delay", 3))

    with lk:
        total_checked += 1
        count = total_checked

    if not result.is_online:
        if not silent_offline:
            if db.site_exists(url):
                db.update_site(url, status="offline", response_time_ms=result.response_time_ms)
            else:
                db.add_site(url, status="offline", response_time_ms=result.response_time_ms)
            log.info(t("offline_fmt", count, result.error, result.response_time_ms, result.attempts))
        return None

    if is_title_ignored(result.title):
        with lk:
            total_ignored += 1
        log.debug(t("ignored", result.title[:40]))
        return None

    cat = categorize(result.title)
    lang = detect_language(result.html)
    dup_of = db.find_by_hash(result.content_hash)
    dup = dup_of if dup_of and dup_of != url else ""

    with lk:
        total_found += 1

    kw = dict(title=result.title, status="online", category=cat, response_time_ms=result.response_time_ms,
              language=lang, content_hash=result.content_hash, duplicate_of=dup,
              server_header=result.server_header, powered_by=result.powered_by, content_type=result.content_type)

    if db.site_exists(url):
        db.update_site(url, **kw)
    else:
        db.add_site(url, **kw)

    crawled = 0
    if result.found_links:
        new = [l for l in result.found_links if not db.site_exists(l)]
        if new:
            with crawl_lock:
                crawl_queue.extend(new)
            crawled = len(new)

    dup_tag = t("dup_fmt", dup[:30]) if dup else ""
    log.info(f"{t('online_fmt', count, result.response_time_ms, cat, lang or '?', result.title)}{dup_tag}")
    log.info(f"         {url}")
    if crawled:
        log.info(t("crawled", count, crawled))

    return {"url": result.url, "title": result.title, "status": "online", "response_time_ms": result.response_time_ms,
            "category": cat, "attempts": result.attempts, "content_hash": result.content_hash,
            "language": lang, "duplicate_of": dup, "crawled_count": crawled, "server_header": result.server_header}


def _ask_int(key, default):
    try:
        return int(input(f"  {t(key, default)}").strip() or str(default))
    except ValueError:
        return default


def handle_bot_command(text):
    global monitor
    cmd = text.strip().lower()
    if cmd == "/status":
        s = db.get_stats()
        s["checked"] = total_checked
        s["found"] = total_found
        send_status(s, scanning_active, monitor and monitor.running)
    elif cmd == "/stop":
        stop_event.set()
        send_text("<b>ghTor</b> | stop sent")
    elif cmd == "/monitor_on":
        if not tor_sessions:
            send_text("<b>ghTor</b> | Tor not connected")
        elif monitor and monitor.running:
            send_text("<b>ghTor</b> | already running")
        else:
            iv = config.get("monitor", "interval", 300)
            monitor = Monitor(db, tor_sessions, interval=iv)
            monitor.start()
            send_text(f"<b>ghTor</b> | monitor started ({iv}s)")
    elif cmd == "/monitor_off":
        if monitor and monitor.running:
            monitor.stop()
            send_text("<b>ghTor</b> | monitor stopped")
        else:
            send_text("<b>ghTor</b> | not running")
    elif cmd == "/stats":
        s = db.get_stats()
        m = {"total": s.get("total",0) or 0, "online": s.get("online",0) or 0, "offline": s.get("offline",0) or 0,
             "checked": total_checked, "found": total_found, "ignored": total_ignored}
        send_text(f"<b>ghTor</b> | stats\n<pre>{json.dumps(m, indent=2)}</pre>")
    elif cmd == "/help":
        send_text("<b>ghTor</b>\n/status\n/stats\n/stop\n/monitor_on\n/monitor_off\n/help")


def do_connect():
    global tor_sessions, tor_port, limiter
    log.info(t("connecting"))
    ports = config.get("tor", "ports", [9150, 9050])
    tor_port = find_tor_port(ports)
    if tor_port is None:
        log.error(t("tor_not_found"))
        return False
    log.info(t("port_found", tor_port))
    sess = make_session(tor_port)
    ok, msg = test_tor_connection(sess)
    if not ok:
        log.error(t("tor_error", msg))
        return False
    log.info(t("tor_ok", msg))
    threads = _ask_int("threads_ask", config.get("tor", "threads", 10))
    threads = max(1, min(threads, 50))
    log.info(t("creating", threads))
    tor_sessions = [make_session(tor_port) for _ in range(threads)]
    rps = config.get("rate_limit", "requests_per_second", 5)
    burst = config.get("rate_limit", "burst", 10)
    limiter = RateLimiter(rps, burst)
    log.info(t("ready", threads))
    if tg_enabled():
        set_command_callback(handle_bot_command)
        start_polling()
        log.info("Telegram: enabled + bot control")
    return True


def do_scan_file():
    if not tor_sessions:
        log.info(t("connect_first"))
        return
    urls = load_links()
    if not urls:
        log.info(t("file_empty", LINKS_FILE))
        return
    new = [u for u in urls if not db.site_exists(u)]
    log.info(t("file_info", len(urls), len(urls) - len(new), len(new)))
    targets = urls
    if len(urls) != len(new) and new:
        c = input(f"  {t('check_new_all')}").strip().lower()
        if c != "a":
            targets = new
    if not targets:
        log.info(t("nothing"))
        return
    timeout = _ask_int("timeout_ask", config.get("tor", "timeout", 20))
    retries = _ask_int("retries_ask", config.get("tor", "retries", 2))
    crawl = input(f"  {t('crawl_ask')}").strip().lower() != "n"
    log.info(t("threads_info", len(tor_sessions), timeout, retries))
    log.info(t("checking", len(targets)))
    stop_event.clear()
    _run_batch(targets, timeout, retries, crawl, False, False)
    print_stats()


def do_discover():
    global scanning_active
    if not tor_sessions:
        log.info(t("connect_first"))
        return
    sources = get_sources()
    if not sources:
        log.info("No sources in config.json")
        return
    timeout = _ask_int("timeout_ask", config.get("tor", "timeout", 20))
    retries = _ask_int("retries_ask", config.get("tor", "retries", 2))
    rescan = config.get("discovery", "rescan_interval", 120)

    log.info(t("phase1", len(sources)))
    found = discover(tor_sessions[0], timeout)
    new = [u for u in found if not db.site_exists(u)]
    log.info(t("collected", len(found), len(new)))
    if not new:
        log.info(t("nothing"))
        return

    log.info(t("phase2", len(new)))
    log.info(t("stop_hint"))

    scanning_active = True
    stop_event.clear()
    tg = tg_enabled()
    batch_buffer = []
    round_num = 0

    def _batch(urls):
        nonlocal batch_buffer
        with ThreadPoolExecutor(max_workers=len(tor_sessions)) as ex:
            futs = {ex.submit(process_url, u, tor_sessions[i % len(tor_sessions)], timeout, retries, True): u
                    for i, u in enumerate(urls) if not stop_event.is_set()}
            for f in as_completed(futs):
                if stop_event.is_set():
                    break
                try:
                    r = f.result()
                    if r:
                        batch_buffer.append(r)
                        if tg:
                            send_site_found(r)
                        if tg and len(batch_buffer) >= 10:
                            send_batch_report(batch_buffer)
                            batch_buffer = []
                except Exception:
                    pass

    try:
        _batch(new)
        while not stop_event.is_set():
            with crawl_lock:
                if not crawl_queue:
                    log.info(t("rescraping"))
                    refound = discover(tor_sessions[0], timeout)
                    refound = [u for u in refound if not db.site_exists(u)]
                    if not refound:
                        log.info(t("no_new", rescan))
                        stop_event.wait(rescan)
                        if stop_event.is_set():
                            break
                        continue
                    targets = refound
                else:
                    targets = list(set(crawl_queue))
                    crawl_queue.clear()
            targets = [u for u in targets if not db.site_exists(u)]
            if not targets:
                continue
            round_num += 1
            log.info(t("crawl_round", round_num, len(targets)))
            _batch(targets)
            print_stats()
    except KeyboardInterrupt:
        stop_event.set()
        log.info(t("stopped"))

    scanning_active = False
    if tg and batch_buffer:
        send_batch_report(batch_buffer)
    print_stats()


def _run_batch(targets, timeout, retries, crawl, silent, tg_notify):
    stop_event.clear()
    def _batch(urls):
        with ThreadPoolExecutor(max_workers=len(tor_sessions)) as ex:
            futs = {ex.submit(process_url, u, tor_sessions[i % len(tor_sessions)], timeout, retries, silent): u
                    for i, u in enumerate(urls) if not stop_event.is_set()}
            for f in as_completed(futs):
                if stop_event.is_set():
                    break
                try:
                    f.result()
                except Exception:
                    pass
    try:
        _batch(targets)
        if crawl:
            rn = 0
            while not stop_event.is_set():
                with crawl_lock:
                    if not crawl_queue:
                        break
                    nt = list(set(crawl_queue))
                    crawl_queue.clear()
                nt = [u for u in nt if not db.site_exists(u)]
                if not nt:
                    break
                rn += 1
                log.info(t("crawl_round", rn, len(nt)))
                _batch(nt)
    except KeyboardInterrupt:
        stop_event.set()
        log.info(t("stopped"))


def do_monitor():
    global monitor
    if not tor_sessions:
        log.info(t("connect_first"))
        return
    if monitor and monitor.running:
        monitor.stop()
        log.info(t("mon_stopped"))
        return
    iv = _ask_int("monitor_ask", config.get("monitor", "interval", 300))
    monitor = Monitor(db, tor_sessions, interval=iv)
    monitor.start()
    log.info(t("mon_started", iv))


def main():
    print(f"\n  {S['pick_lang']}")
    try:
        c = input("\n  > ").strip()
    except (KeyboardInterrupt, EOFError):
        c = "1"
    set_lang("ru" if c == "2" else "en")

    log.info(t("title"))

    while True:
        conn = t("connected") if tor_sessions else t("not_connected")
        th = len(tor_sessions)
        mon = t("on") if monitor and monitor.running else t("off")
        links = len(load_links())
        src = len(get_sources())

        print(f"\n  [Tor: {conn}, {th} threads] [mon: {mon}] [{src} sources]")
        print()
        print(f"  1  {t('menu_1')}")
        if links > 0:
            print(f"  2  {t('menu_2')} ({links})")
        print(f"  3  {t('menu_3')} ({src})")
        print(f"  4  {t('menu_4')}")
        print(f"  0  {t('menu_0')}")

        try:
            ch = input("\n  > ").strip()
        except (KeyboardInterrupt, EOFError):
            break

        if ch == "0":
            break
        elif ch == "1":
            do_connect()
        elif ch == "2":
            do_scan_file()
        elif ch == "3":
            do_discover()
        elif ch == "4":
            do_monitor()

    graceful_shutdown()


if __name__ == "__main__":
    main()