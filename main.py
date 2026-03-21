import sys, os, json, asyncio, signal, atexit
from datetime import datetime
from pathlib import Path

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from core import config
from core.database import Database
from core.fetcher import find_tor_port, create_session, test_tor, fetch, renew_circuit
from core.pipeline import run_pipeline, SiteData
from core.plugins import load_plugins, get_plugins
from core.rate_limit import RateLimiter
from core.telegram import send_site, send_batch, send_status, send_text, tg_enabled, set_callback, start_polling, stop_polling
from core.lang import t, set_lang, S
from core import log

LINKS_FILE = Path(__file__).parent / "links.txt"
EXPORT_DIR = Path(__file__).parent / config.get("export", "dir", "data")
db = Database()
sessions = []
tor_port = None
limiter = None
total_checked = 0
total_found = 0
total_ignored = 0
crawl_queue = asyncio.Queue()
stop_event = asyncio.Event()
scanning = False
monitor_task = None
_shutdown_done = False


def auto_export():
    global _shutdown_done
    if _shutdown_done: return
    _shutdown_done = True
    if not config.get("export","auto_export",True): return
    EXPORT_DIR.mkdir(parents=True, exist_ok=True)
    data = db.export_json()
    if not data: return
    p = EXPORT_DIR / f"export_{datetime.now():%Y%m%d_%H%M%S}.json"
    with open(p,"w",encoding="utf-8") as f:
        json.dump({"exported_at":datetime.utcnow().isoformat(),"total":len(data),"sites":data},f,indent=2,ensure_ascii=False)
    log.info(t("exp",len(data),p))

atexit.register(auto_export)


def load_links():
    if not LINKS_FILE.exists(): return []
    urls = []
    for line in LINKS_FILE.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#"): continue
        if not line.startswith("http"): line = "http://" + line
        if ".onion" in line: urls.append(line)
    seen = set()
    return [u for u in urls if u not in seen and not seen.add(u)]


async def process_url(url, session, silent_offline=False):
    global total_checked, total_found, total_ignored

    if stop_event.is_set(): return None
    await limiter.acquire()

    retries = config.get("tor","retries",2)
    retry_delay = config.get("tor","retry_delay",3)
    data = await fetch(url, session, retries, retry_delay)

    total_checked += 1
    count = total_checked

    if not data.is_online:
        if not silent_offline:
            run_pipeline(data, db)
            log.info(t("off_fmt", count, data.error, data.response_time_ms, data.attempts))
        return None

    data = run_pipeline(data, db)

    if data.is_ignored:
        total_ignored += 1
        log.debug(t("ign", data.title[:40]))
        return None

    total_found += 1

    for link in data.found_links:
        if not db.site_exists(link):
            await crawl_queue.put(link)

    dup = t("dup", data.duplicate_of[:30]) if data.duplicate_of else ""
    log.info(f"{t('on_fmt', count, data.response_time_ms, data.category, data.language or '?', data.title)}{dup}")
    log.info(f"         {url}")
    if data.found_links:
        new_count = len([l for l in data.found_links if not db.site_exists(l)])
        if new_count:
            log.info(t("cr", count, new_count))

    return {"url":data.url,"title":data.title,"status":"online","response_time_ms":data.response_time_ms,
            "category":data.category,"attempts":data.attempts,"content_hash":data.content_hash,
            "language":data.language,"duplicate_of":data.duplicate_of,"crawled_count":len(data.found_links),
            "server_header":data.server_header}


async def run_batch(urls, silent_offline=False, tg_notify=False):
    batch_buf = []
    sem = asyncio.Semaphore(config.get("tor","threads",20))

    async def _worker(url, sess):
        async with sem:
            return await process_url(url, sess, silent_offline)

    tasks = []
    for i, url in enumerate(urls):
        if stop_event.is_set(): break
        sess = sessions[i % len(sessions)]
        tasks.append(asyncio.create_task(_worker(url, sess)))

    for coro in asyncio.as_completed(tasks):
        if stop_event.is_set(): break
        try:
            result = await coro
            if result:
                batch_buf.append(result)
                if tg_notify and tg_enabled():
                    send_site(result)
                if tg_notify and tg_enabled() and len(batch_buf) >= 10:
                    send_batch(batch_buf)
                    batch_buf = []
        except Exception:
            pass

    if tg_notify and tg_enabled() and batch_buf:
        send_batch(batch_buf)
    return batch_buf


def print_stats():
    s = db.get_stats()
    q = crawl_queue.qsize()
    m = t("on") if monitor_task and not monitor_task.done() else t("off")
    log.info(t("st", total_checked, total_found, s.get("online",0) or 0, s.get("offline",0) or 0, s.get("total",0) or 0, q, m))


def _ask_int(key, default):
    try: return int(input(f"  {t(key,default)}").strip() or str(default))
    except ValueError: return default


def handle_bot_cmd(text):
    cmd = text.strip().lower()
    if cmd == "/status":
        s = db.get_stats(); s["checked"]=total_checked; s["found"]=total_found
        send_status(s, scanning, monitor_task and not monitor_task.done())
    elif cmd == "/stop":
        stop_event.set(); send_text("<b>ghTor</b> | stop sent")
    elif cmd == "/stats":
        s = db.get_stats()
        send_text(f"<b>ghTor</b> | stats\n<pre>{json.dumps({'total':s.get('total',0) or 0,'online':s.get('online',0) or 0,'offline':s.get('offline',0) or 0,'checked':total_checked,'found':total_found,'ignored':total_ignored},indent=2)}</pre>")
    elif cmd == "/help":
        send_text("<b>ghTor</b>\n/status\n/stats\n/stop\n/help")


async def do_connect():
    global sessions, tor_port, limiter
    # close old sessions
    for s in sessions:
        try: await s.close()
        except: pass
    sessions = []

    log.info(t("conn"))
    tor_port = find_tor_port()
    if not tor_port:
        log.error(t("nf")); return False
    log.info(t("port", tor_port))

    test_sess = await create_session(tor_port)
    try:
        ok, msg = await test_tor(test_sess)
    finally:
        await test_sess.close()

    if not ok:
        log.error(t("err", msg)); return False
    log.info(t("ok", msg))
    n = _ask_int("thr", config.get("tor","threads",20))
    n = max(1, min(n, 50))
    log.info(t("creating", n))
    sessions = [await create_session(tor_port) for _ in range(n)]
    limiter = RateLimiter(config.get("rate_limit","requests_per_second",10), config.get("rate_limit","burst",20))
    log.info(t("ready", n))

    plugins = load_plugins()
    if plugins:
        names = ", ".join(p.name for p in plugins)
        log.info(t("pl", len(plugins), names))

    if tg_enabled():
        set_callback(handle_bot_cmd)
        start_polling()
        log.info("Telegram: enabled + bot control")
    return True


async def do_scan_file():
    if not sessions: log.info(t("first")); return
    urls = load_links()
    if not urls: log.info(t("fe", LINKS_FILE)); return
    new = [u for u in urls if not db.site_exists(u)]
    log.info(t("fi", len(urls), len(urls)-len(new), len(new)))
    targets = urls
    if len(urls) != len(new) and new:
        c = input(f"  {t('na')}").strip().lower()
        if c != "a": targets = new
    if not targets: log.info(t("no")); return
    crawl = input(f"  {t('ca')}").strip().lower() != "n"
    log.info(t("ck", len(targets)))
    stop_event.clear()
    await run_batch(targets, silent_offline=False, tg_notify=False)
    if crawl:
        rn = 0
        while not stop_event.is_set() and not crawl_queue.empty():
            batch = []
            while not crawl_queue.empty() and len(batch) < 200:
                try: batch.append(crawl_queue.get_nowait())
                except: break
            batch = [u for u in set(batch) if not db.site_exists(u)]
            if not batch: break
            rn += 1
            log.info(t("crr", rn, len(batch)))
            await run_batch(batch, silent_offline=False, tg_notify=False)
    print_stats()


async def do_discover():
    global scanning
    if not sessions: log.info(t("first")); return
    plugins = get_plugins()
    if not plugins: log.info("No plugins loaded. Add .py files to plugins/"); return

    log.info(t("p1", len(plugins)))
    all_found = set()
    for plugin in plugins:
        if stop_event.is_set(): break
        try:
            links = await plugin.scrape(sessions[0])
            if links:
                all_found.update(links)
                log.info(f"  {plugin.name}: +{len(links)} total")
            else:
                log.info(f"  {plugin.name}: 0 (source may be down)")
        except Exception as e:
            log.error(f"  {plugin.name} failed: {type(e).__name__}: {e}")

    new = [u for u in all_found if not db.site_exists(u)]
    log.info(t("coll", len(all_found), len(new)))
    if not new: log.info(t("no")); return

    log.info(t("p2", len(new)))
    log.info(t("sh"))

    scanning = True
    stop_event.clear()
    rescan = config.get("discovery","rescan_interval",120)

    await run_batch(new, silent_offline=True, tg_notify=True)

    while not stop_event.is_set():
        batch = []
        while not crawl_queue.empty() and len(batch) < 300:
            try: batch.append(crawl_queue.get_nowait())
            except: break

        if not batch:
            log.info(t("resc"))
            re_found = set()
            for plugin in plugins:
                if stop_event.is_set(): break
                try:
                    links = await plugin.scrape(sessions[0])
                    if links:
                        re_found.update(links)
                except Exception as e:
                    log.debug(f"  {plugin.name} rescrape error: {e}")
            re_new = [u for u in re_found if not db.site_exists(u)]
            if not re_new:
                log.info(t("nn", rescan))
                try: await asyncio.wait_for(stop_event.wait(), timeout=rescan)
                except asyncio.TimeoutError: pass
                if stop_event.is_set(): break
                continue
            batch = re_new

        batch = [u for u in set(batch) if not db.site_exists(u)]
        if not batch: continue
        log.info(t("crr", "~", len(batch)))
        await run_batch(batch, silent_offline=True, tg_notify=True)
        print_stats()

    scanning = False
    print_stats()


async def do_monitor():
    global monitor_task
    if not sessions: log.info(t("first")); return
    if monitor_task and not monitor_task.done():
        monitor_task.cancel()
        log.info(t("mt")); monitor_task = None; return
    iv = _ask_int("mi", config.get("monitor","interval",300))

    async def _monitor_loop():
        while True:
            sites = db.get_online_sites()
            if sites:
                log.info(f"[monitor] Checking {len(sites)}")
                went_off, came_on = [], []
                for site in sites:
                    url = site["url"]
                    sess = sessions[hash(url) % len(sessions)]
                    data = await fetch(url, sess, 2, 2)
                    if not data.is_online and site["status"] == "online":
                        db.update_site(url, status="offline", response_time_ms=data.response_time_ms)
                        went_off.append({"url":url})
                    elif data.is_online and site["status"] != "online":
                        db.update_site(url, title=data.title or "", status="online", response_time_ms=data.response_time_ms)
                        came_on.append({"url":url,"title":data.title or ""})
                    else:
                        db.update_site(url, response_time_ms=data.response_time_ms)
                if (went_off or came_on) and tg_enabled():
                    from core.telegram import send_monitor_alert
                    send_monitor_alert(went_off, came_on)
                log.info(f"[monitor] {len(went_off)} off, {len(came_on)} on")
            await asyncio.sleep(iv)

    monitor_task = asyncio.create_task(_monitor_loop())
    log.info(t("ms", iv))


async def cleanup():
    for s in sessions:
        try: await s.close()
        except: pass
    await asyncio.sleep(0.25)
    stop_polling()
    auto_export()


async def main():
    print(f"\n  {S['pick']}")
    try: c = input("\n  > ").strip()
    except: c = "1"
    set_lang("ru" if c == "2" else "en")
    log.info(t("title"))

    loop = asyncio.get_event_loop()
    for sig in (signal.SIGINT, signal.SIGTERM):
        try: loop.add_signal_handler(sig, lambda: stop_event.set())
        except: pass

    while True:
        co = t("co") if sessions else t("nc")
        th = len(sessions)
        mo = t("on") if monitor_task and not monitor_task.done() else t("off")
        links = len(load_links())
        pl = len(get_plugins())

        print(f"\n  [Tor: {co}, {th}] [mon: {mo}] [{pl} plugins]")
        print()
        print(f"  1  {t('m1')}")
        if links > 0:
            print(f"  2  {t('m2')} ({links})")
        print(f"  3  {t('m3')} ({pl} plugins)")
        print(f"  4  {t('m4')}")
        print(f"  0  {t('m0')}")

        try:
            ch = await asyncio.get_event_loop().run_in_executor(None, lambda: input("\n  > ").strip())
        except (KeyboardInterrupt, EOFError):
            break

        if ch == "0": break
        elif ch == "1": await do_connect()
        elif ch == "2": await do_scan_file()
        elif ch == "3": await do_discover()
        elif ch == "4": await do_monitor()

    await cleanup()
    print(f"\n  {t('bye')}\n")


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        auto_export()