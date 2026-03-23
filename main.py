import sys
import os
import json
import asyncio
import signal
import atexit
from datetime import datetime
from pathlib import Path
from typing import Optional

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from core import config, __version__
from core.database import Database
from core.fetcher import find_tor_port, create_session, test_tor, fetch, renew_circuit
from core.pipeline import run_pipeline, SiteData
from core.plugins import load_plugins, get_plugins, SourcePlugin
from core.rate_limit import RateLimiter
from core.telegram import (send_site, send_batch, send_status, send_text,
                            tg_enabled, set_callback, start_polling, stop_polling)
from core.lang import t, set_lang, S
from core import log

LINKS_FILE: Path = Path(__file__).parent / "links.txt"
EXPORT_DIR: Path = Path(__file__).parent / config.get("export", "dir", "data")

db: Database = Database()
sessions: list = []
tor_port: Optional[int] = None
limiter: Optional[RateLimiter] = None
total_checked: int = 0
total_found: int = 0
total_ignored: int = 0
crawl_queue: asyncio.Queue = asyncio.Queue()
stop_event: asyncio.Event = asyncio.Event()
scanning: bool = False
monitor_task: Optional[asyncio.Task] = None
_shutdown_done: bool = False


def auto_export() -> None:
    global _shutdown_done
    if _shutdown_done:
        return
    _shutdown_done = True
    if not config.get("export", "auto_export", True):
        return
    EXPORT_DIR.mkdir(parents=True, exist_ok=True)
    data: list[dict] = db.export_json()
    if not data:
        return
    p: Path = EXPORT_DIR / f"export_{datetime.now():%Y%m%d_%H%M%S}.json"
    try:
        with open(p, "w", encoding="utf-8") as f:
            json.dump({"version": __version__, "exported_at": datetime.utcnow().isoformat(),
                        "total": len(data), "sites": data}, f, indent=2, ensure_ascii=False)
        log.info(t("exp", len(data), p))
    except OSError as e:
        log.error(f"Export failed: {e}")


atexit.register(auto_export)


def load_links() -> list[str]:
    if not LINKS_FILE.exists():
        return []
    try:
        urls: list[str] = []
        for line in LINKS_FILE.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            if not line.startswith("http"):
                line = "http://" + line
            if ".onion" in line:
                urls.append(line)
        seen: set[str] = set()
        return [u for u in urls if u not in seen and not seen.add(u)]
    except OSError:
        return []


async def ensure_sessions() -> bool:
    if not sessions:
        log.error(t("first"))
        return False
    try:
        test_sess = sessions[0]
        async with test_sess.get("http://juhanurmihxlp77nkq76byazcldy2hlmovfu2epvl5ankdibsot4csyd.onion", timeout=aiohttp.ClientTimeout(total=10)) as r:
            pass
        return True
    except Exception:
        log.warn(t("tor_dropped"))
        return await do_connect()


import aiohttp


async def process_url(url: str, session: aiohttp.ClientSession,
                      silent_offline: bool = False) -> Optional[dict]:
    global total_checked, total_found, total_ignored

    if stop_event.is_set():
        return None
    if limiter:
        await limiter.acquire()

    retries: int = config.get("tor", "retries", 2)
    retry_delay: int = config.get("tor", "retry_delay", 3)

    try:
        data: SiteData = await fetch(url, session, retries, retry_delay)
    except Exception as e:
        log.debug(f"Fetch exception {url}: {type(e).__name__}: {e}")
        return None

    total_checked += 1
    count: int = total_checked

    if not data.is_online:
        if not silent_offline:
            try:
                run_pipeline(data, db)
            except Exception as e:
                log.debug(f"Pipeline error (offline): {e}")
            log.info(t("off_fmt", count, data.error, data.response_time_ms, data.attempts))
        return None

    try:
        data = run_pipeline(data, db)
    except Exception as e:
        log.error(f"Pipeline error: {type(e).__name__}: {e}")
        return None

    if data.is_ignored:
        total_ignored += 1
        log.debug(t("ign", data.title[:40] if data.title else ""))
        return None

    total_found += 1

    for link in data.found_links:
        if not db.site_exists(link):
            try:
                crawl_queue.put_nowait(link)
            except asyncio.QueueFull:
                break

    dup: str = t("dup", data.duplicate_of[:30]) if data.duplicate_of else ""
    log.info(f"{t('on_fmt', count, data.response_time_ms, data.category, data.language or '?', data.title)}{dup}")
    log.info(f"         {url}")
    if data.found_links:
        new_count: int = len([l for l in data.found_links if not db.site_exists(l)])
        if new_count:
            log.info(t("cr", count, new_count))

    return {
        "url": data.url, "title": data.title, "status": "online",
        "response_time_ms": data.response_time_ms, "category": data.category,
        "attempts": data.attempts, "content_hash": data.content_hash,
        "language": data.language, "duplicate_of": data.duplicate_of,
        "crawled_count": len(data.found_links), "server_header": data.server_header,
    }


async def run_batch(urls: list[str], silent_offline: bool = False,
                    tg_notify: bool = False) -> list[dict]:
    batch_buf: list[dict] = []
    sem = asyncio.Semaphore(config.get("tor", "threads", 20))

    async def _worker(url: str, sess: aiohttp.ClientSession) -> Optional[dict]:
        async with sem:
            return await process_url(url, sess, silent_offline)

    tasks: list[asyncio.Task] = []
    for i, url in enumerate(urls):
        if stop_event.is_set():
            break
        sess = sessions[i % len(sessions)]
        tasks.append(asyncio.create_task(_worker(url, sess)))

    for coro in asyncio.as_completed(tasks):
        if stop_event.is_set():
            break
        try:
            result: Optional[dict] = await coro
            if result:
                batch_buf.append(result)
                if tg_notify and tg_enabled():
                    send_site(result)
                if tg_notify and tg_enabled() and len(batch_buf) >= 10:
                    send_batch(batch_buf)
                    batch_buf = []
        except Exception as e:
            log.debug(f"Batch worker error: {e}")

    if tg_notify and tg_enabled() and batch_buf:
        send_batch(batch_buf)
    return batch_buf


def print_stats() -> None:
    s: dict = db.get_stats()
    q: int = crawl_queue.qsize()
    m: str = t("on") if monitor_task and not monitor_task.done() else t("off")
    log.info(t("st", total_checked, total_found, s.get("online", 0) or 0,
               s.get("offline", 0) or 0, s.get("total", 0) or 0, q, m))


def _ask_int(key: str, default: int) -> int:
    try:
        return int(input(f"  {t(key, default)}").strip() or str(default))
    except (ValueError, EOFError):
        return default


def handle_bot_cmd(text: str) -> None:
    cmd: str = text.strip().lower()
    if cmd == "/status":
        s = db.get_stats()
        s["checked"] = total_checked
        s["found"] = total_found
        s["version"] = __version__
        send_status(s, scanning, bool(monitor_task and not monitor_task.done()))
    elif cmd == "/stop":
        stop_event.set()
        send_text("<b>Tor-Link-Parser</b> | stop sent")
    elif cmd == "/stats":
        s = db.get_stats()
        send_text(f"<b>Tor-Link-Parser</b> | stats\n<pre>{json.dumps({'version': __version__, 'total': s.get('total', 0) or 0, 'online': s.get('online', 0) or 0, 'offline': s.get('offline', 0) or 0, 'checked': total_checked, 'found': total_found, 'ignored': total_ignored}, indent=2)}</pre>")
    elif cmd == "/help":
        send_text(f"<b>Tor-Link-Parser v{__version__}</b>\n/status\n/stats\n/stop\n/help")


async def do_connect() -> bool:
    global sessions, tor_port, limiter

    for s in sessions:
        try:
            await s.close()
        except Exception:
            pass
    sessions = []

    log.info(t("conn"))
    tor_port = find_tor_port()
    if not tor_port:
        log.error(t("nf"))
        return False
    log.info(t("port", tor_port))

    test_sess = await create_session(tor_port)
    try:
        ok, msg = await test_tor(test_sess)
    finally:
        await test_sess.close()

    if not ok:
        log.error(t("err", msg))
        return False
    log.info(t("ok", msg))

    n: int = _ask_int("thr", config.get("tor", "threads", 20))
    n = max(1, min(n, 50))
    log.info(t("creating", n))
    sessions = [await create_session(tor_port) for _ in range(n)]
    limiter = RateLimiter(
        config.get("rate_limit", "requests_per_second", 10),
        config.get("rate_limit", "burst", 20),
    )
    log.info(t("ready", n))

    plugins = load_plugins()
    if plugins:
        names: str = ", ".join(p.name for p in plugins)
        log.info(t("pl", len(plugins), names))

    if tg_enabled():
        set_callback(handle_bot_cmd)
        start_polling()
        log.info("Telegram: enabled + bot control")
    return True


async def do_scan_file() -> None:
    if not sessions:
        log.info(t("first"))
        return
    urls: list[str] = load_links()
    if not urls:
        log.info(t("fe", LINKS_FILE))
        return
    new: list[str] = [u for u in urls if not db.site_exists(u)]
    log.info(t("fi", len(urls), len(urls) - len(new), len(new)))
    targets: list[str] = urls
    if len(urls) != len(new) and new:
        c = input(f"  {t('na')}").strip().lower()
        if c != "a":
            targets = new
    if not targets:
        log.info(t("no"))
        return
    crawl: bool = input(f"  {t('ca')}").strip().lower() != "n"
    log.info(t("ck", len(targets)))
    stop_event.clear()
    await run_batch(targets, silent_offline=False, tg_notify=False)
    if crawl:
        rn: int = 0
        while not stop_event.is_set() and not crawl_queue.empty():
            batch: list[str] = []
            while not crawl_queue.empty() and len(batch) < 200:
                try:
                    batch.append(crawl_queue.get_nowait())
                except asyncio.QueueEmpty:
                    break
            batch = [u for u in set(batch) if not db.site_exists(u)]
            if not batch:
                break
            rn += 1
            log.info(t("crr", rn, len(batch)))
            await run_batch(batch, silent_offline=False, tg_notify=False)
    print_stats()


async def do_discover() -> None:
    global scanning
    if not sessions:
        log.info(t("first"))
        return
    plugins: list[SourcePlugin] = get_plugins()
    if not plugins:
        log.info("No plugins loaded")
        return

    log.info(t("p1", len(plugins)))
    all_found: set[str] = set()
    for plugin in plugins:
        if stop_event.is_set():
            break
        try:
            links: list[str] = await asyncio.wait_for(plugin.scrape(sessions[0]), timeout=90)
            if links:
                all_found.update(links)
                log.info(f"  {plugin.name}: +{len(links)} total")
            else:
                log.info(f"  {plugin.name}: 0 (source may be down)")
        except asyncio.TimeoutError:
            log.warn(f"  {plugin.name}: timeout (90s)")
        except Exception as e:
            log.error(f"  {plugin.name} failed: {type(e).__name__}: {e}")

    new: list[str] = [u for u in all_found if not db.site_exists(u)]
    log.info(t("coll", len(all_found), len(new)))
    if not new:
        log.info(t("no"))
        return

    log.info(t("p2", len(new)))
    log.info(t("sh"))

    scanning = True
    stop_event.clear()
    rescan: int = config.get("discovery", "rescan_interval", 120)

    await run_batch(new, silent_offline=True, tg_notify=True)

    while not stop_event.is_set():
        batch: list[str] = []
        while not crawl_queue.empty() and len(batch) < 300:
            try:
                batch.append(crawl_queue.get_nowait())
            except asyncio.QueueEmpty:
                break

        if not batch:
            log.info(t("resc"))
            re_found: set[str] = set()
            for plugin in plugins:
                if stop_event.is_set():
                    break
                try:
                    links = await asyncio.wait_for(plugin.scrape(sessions[0]), timeout=90)
                    if links:
                        re_found.update(links)
                except asyncio.TimeoutError:
                    log.debug(f"  {plugin.name} rescrape timeout")
                except Exception as e:
                    log.debug(f"  {plugin.name} rescrape error: {e}")
            re_new: list[str] = [u for u in re_found if not db.site_exists(u)]
            if not re_new:
                log.info(t("nn", rescan))
                try:
                    await asyncio.wait_for(stop_event.wait(), timeout=rescan)
                except asyncio.TimeoutError:
                    pass
                if stop_event.is_set():
                    break
                continue
            batch = re_new

        batch = [u for u in set(batch) if not db.site_exists(u)]
        if not batch:
            continue
        log.info(t("crr", "~", len(batch)))
        await run_batch(batch, silent_offline=True, tg_notify=True)
        print_stats()

    scanning = False
    print_stats()


async def do_monitor() -> None:
    global monitor_task
    if not sessions:
        log.info(t("first"))
        return
    if monitor_task and not monitor_task.done():
        monitor_task.cancel()
        log.info(t("mt"))
        monitor_task = None
        return
    iv: int = _ask_int("mi", config.get("monitor", "interval", 300))

    async def _monitor_loop() -> None:
        while True:
            sites: list[dict] = db.get_online_sites()
            if sites:
                log.info(f"[monitor] Checking {len(sites)}")
                went_off: list[dict] = []
                came_on: list[dict] = []
                for site in sites:
                    url: str = site["url"]
                    sess = sessions[hash(url) % len(sessions)]
                    try:
                        data: SiteData = await fetch(url, sess, 2, 2)
                    except Exception:
                        continue
                    if not data.is_online and site["status"] == "online":
                        db.update_site(url, status="offline", response_time_ms=data.response_time_ms)
                        went_off.append({"url": url})
                    elif data.is_online and site["status"] != "online":
                        db.update_site(url, title=data.title or "", status="online",
                                       response_time_ms=data.response_time_ms)
                        came_on.append({"url": url, "title": data.title or ""})
                    else:
                        db.update_site(url, response_time_ms=data.response_time_ms)
                if (went_off or came_on) and tg_enabled():
                    from core.telegram import send_monitor_alert
                    send_monitor_alert(went_off, came_on)
                log.info(f"[monitor] {len(went_off)} off, {len(came_on)} on")
            await asyncio.sleep(iv)

    monitor_task = asyncio.create_task(_monitor_loop())
    log.info(t("ms", iv))


async def cleanup() -> None:
    for s in sessions:
        try:
            await s.close()
        except Exception:
            pass
    await asyncio.sleep(0.25)
    stop_polling()
    auto_export()


async def main() -> None:
    print(f"\n  {S['pick']}")
    try:
        c: str = input("\n  > ").strip()
    except (KeyboardInterrupt, EOFError):
        c = "1"
    set_lang("ru" if c == "2" else "en")
    log.info(t("title"))

    loop = asyncio.get_event_loop()
    for sig in (signal.SIGINT, signal.SIGTERM):
        try:
            loop.add_signal_handler(sig, lambda: stop_event.set())
        except NotImplementedError:
            pass

    while True:
        co: str = t("co") if sessions else t("nc")
        th: int = len(sessions)
        mo: str = t("on") if monitor_task and not monitor_task.done() else t("off")
        links: int = len(load_links())
        pl: int = len(get_plugins())

        print(f"\n  [Tor: {co}, {th}] [mon: {mo}] [{pl} plugins]")
        print()
        print(f"  1  {t('m1')}")
        if links > 0:
            print(f"  2  {t('m2')} ({links})")
        print(f"  3  {t('m3')} ({pl} plugins)")
        print(f"  4  {t('m4')}")
        print(f"  0  {t('m0')}")

        try:
            ch: str = await asyncio.get_event_loop().run_in_executor(
                None, lambda: input("\n  > ").strip()
            )
        except (KeyboardInterrupt, EOFError):
            break

        if ch == "0":
            break
        elif ch == "1":
            await do_connect()
        elif ch == "2":
            await do_scan_file()
        elif ch == "3":
            await do_discover()
        elif ch == "4":
            await do_monitor()

    await cleanup()
    print(f"\n  {t('bye')}\n")


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        auto_export()   