import sys
import os
import json
import time
import atexit
import threading
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime
from pathlib import Path

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from core.database import Database
from core.checker import check_site, find_tor_port, make_session, renew_circuit, test_tor_connection
from core.categorizer import categorize
from core.discovery import discover_all, discover_from_clearnet, discover_from_tor
from core.language import detect_language
from core.telegram import (
    send_site_found, send_batch_report, load_config, send_status, send_text,
    set_command_callback, start_polling, stop_polling
)
from core.monitor import Monitor
from core.title_filter import is_title_ignored
from core.lang import t, set_lang, STRINGS

LINKS_FILE = Path(__file__).parent / "links.txt"
EXPORT_DIR = Path(__file__).parent / "data"
db = Database()
tor_sessions = []
tor_port = None
total_checked = 0
total_found = 0
total_ignored = 0
lock = threading.Lock()
stop_event = threading.Event()
crawl_queue = []
crawl_lock = threading.Lock()
monitor = None
circuit_counter = 0
CIRCUIT_ROTATE_EVERY = 50
scanning_active = False


def auto_export():
    EXPORT_DIR.mkdir(parents=True, exist_ok=True)
    data = db.export_json()
    if not data:
        return
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    path = EXPORT_DIR / f"export_{ts}.json"
    with open(path, "w", encoding="utf-8") as f:
        json.dump({"exported_at": datetime.utcnow().isoformat(), "total": len(data), "sites": data}, f, indent=2, ensure_ascii=False)
    print(f"\n  {t('auto_exported', len(data), path)}")


atexit.register(auto_export)


def create_sessions(count, port):
    return [make_session(port) for _ in range(count)]


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


def maybe_rotate_circuit():
    global circuit_counter
    with lock:
        circuit_counter += 1
        if circuit_counter % CIRCUIT_ROTATE_EVERY == 0:
            if renew_circuit(tor_port):
                print(f"  {t('circuit_rotated', circuit_counter)}")


def print_stats():
    stats = db.get_stats()
    cq = len(crawl_queue)
    mon = t("on") if monitor and monitor.running else t("off")
    print(f"\n  {t('stats_fmt', total_checked, total_found, stats.get('online',0) or 0, stats.get('offline',0) or 0, stats.get('total',0) or 0, cq, mon)}")


def process_url(url, session, timeout, retries, silent_offline=False):
    global total_checked, total_found, total_ignored

    if stop_event.is_set():
        return None

    maybe_rotate_circuit()
    result = check_site(url, session, timeout, retries)

    with lock:
        total_checked += 1
        count = total_checked

    if not result.is_online:
        if not silent_offline:
            if db.site_exists(url):
                db.update_site(url, status="offline", response_time_ms=result.response_time_ms)
            else:
                db.add_site(url, "", "offline", "uncategorized", result.response_time_ms)
            print(f"  {t('offline_fmt', count, result.error, result.response_time_ms, result.attempts)}")
        return None

    if is_title_ignored(result.title):
        with lock:
            total_ignored += 1
        return None

    cat = categorize(result.title)
    lang = detect_language(result.html)
    dup_of = db.find_by_hash(result.content_hash)
    dup = dup_of if dup_of and dup_of != url else ""

    with lock:
        total_found += 1

    if db.site_exists(url):
        db.update_site(url, title=result.title, status="online", category=cat,
                       response_time_ms=result.response_time_ms, language=lang,
                       content_hash=result.content_hash, duplicate_of=dup)
    else:
        db.add_site(url, result.title, "online", cat, result.response_time_ms,
                    lang, result.content_hash, dup)

    crawled = 0
    if result.found_links:
        new_links = [l for l in result.found_links if not db.site_exists(l)]
        if new_links:
            with crawl_lock:
                crawl_queue.extend(new_links)
            crawled = len(new_links)

    dup_tag = t("dup_fmt", dup[:30]) if dup else ""
    print(f"  {t('online_fmt', count, result.response_time_ms, cat, lang or '?', result.title)}{dup_tag}")
    print(f"         {url}")
    if crawled:
        print(f"  {t('crawled_links', count, crawled)}")

    return {
        "url": result.url, "title": result.title, "status": "online",
        "response_time_ms": result.response_time_ms, "category": cat,
        "attempts": result.attempts, "content_hash": result.content_hash,
        "language": lang, "duplicate_of": dup, "crawled_count": crawled,
    }


def _run_threaded(targets, timeout, retries, crawl=True, silent_offline=False, tg_notify=False):
    tg_token, tg_chat = load_config()
    tg_enabled = tg_notify and bool(tg_token and tg_chat)

    print(f"  {t('threads_info', len(tor_sessions), timeout, retries, t('on') if crawl else t('off'))}")
    print(f"  {t('checking_urls', len(targets))}\n")

    stop_event.clear()
    batch_buffer = []

    def _process_batch(urls):
        nonlocal batch_buffer
        with ThreadPoolExecutor(max_workers=len(tor_sessions)) as executor:
            futures = {}
            for i, url in enumerate(urls):
                if stop_event.is_set():
                    break
                sess = tor_sessions[i % len(tor_sessions)]
                futures[executor.submit(process_url, url, sess, timeout, retries, silent_offline)] = url
            for future in as_completed(futures):
                if stop_event.is_set():
                    break
                try:
                    result = future.result()
                    if result:
                        batch_buffer.append(result)
                        if tg_enabled:
                            send_site_found(result)
                        if tg_enabled and len(batch_buffer) >= 10:
                            send_batch_report(batch_buffer)
                            batch_buffer = []
                except Exception:
                    pass

    try:
        _process_batch(targets)
        if crawl:
            round_num = 0
            while not stop_event.is_set():
                with crawl_lock:
                    if not crawl_queue:
                        break
                    new_targets = list(set(crawl_queue))
                    crawl_queue.clear()
                new_targets = [u for u in new_targets if not db.site_exists(u)]
                if not new_targets:
                    break
                round_num += 1
                print(f"\n  {t('crawl_round', round_num, len(new_targets))}\n")
                _process_batch(new_targets)
    except KeyboardInterrupt:
        stop_event.set()
        print(f"\n\n  {t('stopped')}")

    if tg_enabled and batch_buffer:
        send_batch_report(batch_buffer)
    print_stats()


def _ask_int(key, default):
    try:
        return int(input(f"  {t(key, default)}").strip() or str(default))
    except ValueError:
        return default


def handle_bot_command(text):
    global monitor
    cmd = text.strip().lower()
    if cmd == "/status":
        stats = db.get_stats()
        stats["checked_session"] = total_checked
        stats["found_session"] = total_found
        send_status(stats, scanning_active, monitor and monitor.running)
    elif cmd == "/stop":
        stop_event.set()
        send_text("<b>ghTor</b> | stop signal sent")
    elif cmd == "/monitor_on":
        if not tor_sessions:
            send_text("<b>ghTor</b> | Tor not connected")
            return
        if monitor and monitor.running:
            send_text("<b>ghTor</b> | monitor already running")
            return
        monitor = Monitor(db, tor_sessions, interval=300)
        monitor.start()
        send_text("<b>ghTor</b> | monitor started (300s)")
    elif cmd == "/monitor_off":
        if monitor and monitor.running:
            monitor.stop()
            send_text("<b>ghTor</b> | monitor stopped")
        else:
            send_text("<b>ghTor</b> | monitor not running")
    elif cmd == "/stats":
        stats = db.get_stats()
        msg = {"total": stats.get("total", 0) or 0, "online": stats.get("online", 0) or 0,
               "offline": stats.get("offline", 0) or 0, "session_checked": total_checked,
               "session_found": total_found, "session_ignored": total_ignored}
        send_text(f"<b>ghTor</b> | stats\n<pre>{json.dumps(msg, indent=2)}</pre>")
    elif cmd == "/help":
        send_text("<b>ghTor</b> | commands\n\n/status\n/stats\n/stop\n/monitor_on\n/monitor_off\n/help")


def do_connect():
    global tor_sessions, tor_port
    print(f"\n  {t('connecting')}")
    tor_port = find_tor_port()
    if tor_port is None:
        print(f"  {t('tor_not_found')}")
        return False
    print(f"  {t('port_found', tor_port)}")
    sess = make_session(tor_port)
    ok, msg = test_tor_connection(sess)
    if not ok:
        print(f"  {t('tor_error', msg)}")
        return False
    print(f"  {t('tor_ok', msg)}")
    threads = _ask_int("threads_ask", 10)
    threads = max(1, min(threads, 50))
    print(f"  {t('creating_sessions', threads)}")
    tor_sessions = create_sessions(threads, tor_port)
    print(f"  {t('ready', threads)}")
    tg_token, tg_chat = load_config()
    if tg_token and tg_chat:
        set_command_callback(handle_bot_command)
        if start_polling():
            print(f"  {t('tg_enabled')} + bot control")
    return True


def do_scan_file():
    if not tor_sessions:
        print(f"  {t('connect_first')}")
        return
    urls = load_links()
    if not urls:
        print(f"  {t('file_empty', LINKS_FILE)}")
        return
    new_urls = [u for u in urls if not db.site_exists(u)]
    already = len(urls) - len(new_urls)
    print(f"\n  {t('file_info', len(urls), already, len(new_urls))}")
    targets = urls
    if already > 0 and new_urls:
        choice = input(f"  {t('check_new_or_all')}").strip().lower()
        if choice != "a":
            targets = new_urls
    if not targets:
        print(f"  {t('nothing_to_check')}")
        return
    timeout = _ask_int("timeout_ask", 20)
    retries = _ask_int("retries_ask", 3)
    crawl = input(f"  {t('crawl_ask')}").strip().lower() != "n"
    _run_threaded(targets, timeout, retries, crawl, silent_offline=False, tg_notify=False)


def do_discover():
    global scanning_active
    if not tor_sessions:
        print(f"  {t('connect_first')}")
        return

    timeout = _ask_int("timeout_ask", 20)
    retries = _ask_int("retries_ask", 2)

    print(f"\n  Phase 1: Collecting .onion addresses from clearnet sources...")
    clearnet_links = discover_from_clearnet()
    print(f"  Found {len(clearnet_links)} addresses from clearnet")

    print(f"  Phase 2: Collecting from Tor directories...")
    tor_links = discover_from_tor(tor_sessions[0])
    print(f"  Found {len(tor_links)} addresses from Tor")

    all_links = list(set(clearnet_links + tor_links))
    new_links = [u for u in all_links if not db.site_exists(u)]
    print(f"  Total unique: {len(all_links)}, New: {len(new_links)}")

    if not new_links:
        print(f"  {t('nothing_to_check')}")
        return

    print(f"\n  Phase 3: Checking {len(new_links)} sites + crawling for more...")
    print(f"  {t('bruteforce_stop')}\n")

    scanning_active = True
    stop_event.clear()

    tg_token, tg_chat = load_config()
    tg_enabled = bool(tg_token and tg_chat)
    batch_buffer = []
    round_num = 0

    def _check_batch(urls):
        nonlocal batch_buffer
        with ThreadPoolExecutor(max_workers=len(tor_sessions)) as executor:
            futures = {}
            for i, url in enumerate(urls):
                if stop_event.is_set():
                    break
                sess = tor_sessions[i % len(tor_sessions)]
                futures[executor.submit(process_url, url, sess, timeout, retries, True)] = url
            for future in as_completed(futures):
                if stop_event.is_set():
                    break
                try:
                    result = future.result()
                    if result:
                        batch_buffer.append(result)
                        if tg_enabled:
                            send_site_found(result)
                        if tg_enabled and len(batch_buffer) >= 10:
                            send_batch_report(batch_buffer)
                            batch_buffer = []
                except Exception:
                    pass

    try:
        _check_batch(new_links)

        while not stop_event.is_set():
            with crawl_lock:
                if not crawl_queue:
                    print("\n  Crawl queue empty. Re-discovering...")
                    new_found = discover_all(tor_sessions[0])
                    new_found = [u for u in new_found if not db.site_exists(u)]
                    if not new_found:
                        print("  No new addresses found. Waiting 60s...")
                        stop_event.wait(60)
                        if stop_event.is_set():
                            break
                        continue
                    targets = new_found
                else:
                    targets = list(set(crawl_queue))
                    crawl_queue.clear()

            targets = [u for u in targets if not db.site_exists(u)]
            if not targets:
                continue

            round_num += 1
            print(f"\n  {t('crawl_round', round_num, len(targets))}\n")
            _check_batch(targets)
            print_stats()

    except KeyboardInterrupt:
        stop_event.set()
        print(f"\n\n  {t('stopped')}")

    scanning_active = False
    if tg_enabled and batch_buffer:
        send_batch_report(batch_buffer)
    print_stats()


def do_monitor():
    global monitor
    if not tor_sessions:
        print(f"  {t('connect_first')}")
        return
    if monitor and monitor.running:
        monitor.stop()
        print(f"  {t('monitor_stopped')}")
        return
    interval = _ask_int("monitor_ask", 300)
    monitor = Monitor(db, tor_sessions, interval=interval)
    monitor.start()
    print(f"  {t('monitor_started', interval)}")


def pick_language():
    print(f"\n  {STRINGS['pick_lang']}")
    try:
        choice = input("\n  > ").strip()
    except (KeyboardInterrupt, EOFError):
        choice = "1"
    set_lang("ru" if choice == "2" else "en")


def main():
    pick_language()
    print(f"\n  {t('title')}")

    while True:
        connected = t("connected") if tor_sessions else t("not_connected")
        threads = len(tor_sessions)
        mon = t("on") if monitor and monitor.running else t("off")
        links = len(load_links())

        print(f"\n  [Tor: {connected}, {threads} threads] [monitor: {mon}]")
        print()
        print(f"  1  {t('menu_1')}")
        if links > 0:
            print(f"  2  {t('menu_2')} ({links})")
        print(f"  3  {t('menu_3')}")
        print(f"  4  {t('menu_6')}")
        print(f"  0  {t('menu_0')}")

        try:
            choice = input("\n  > ").strip()
        except (KeyboardInterrupt, EOFError):
            break

        if choice == "0":
            break
        elif choice == "1":
            do_connect()
        elif choice == "2":
            do_scan_file()
        elif choice == "3":
            do_discover()
        elif choice == "4":
            do_monitor()

    if monitor and monitor.running:
        monitor.stop()
    stop_polling()
    print(f"\n  {t('bye')}\n")


if __name__ == "__main__":
    main()