import time
import threading
from concurrent.futures import ThreadPoolExecutor, as_completed

from core.database import Database
from core.checker import check_site
from core.categorizer import categorize
from core.telegram import send_monitor_alert, load_config


class Monitor:
    def __init__(self, db, sessions, interval=300, timeout=20, retries=2):
        self.db = db
        self.sessions = sessions
        self.interval = interval
        self.timeout = timeout
        self.retries = retries
        self._thread = None
        self._stop = threading.Event()

    def start(self):
        if self._thread and self._thread.is_alive():
            return
        self._stop.clear()
        self._thread = threading.Thread(target=self._loop, daemon=True)
        self._thread.start()

    def stop(self):
        self._stop.set()
        if self._thread:
            self._thread.join(timeout=5)

    @property
    def running(self):
        return self._thread is not None and self._thread.is_alive()

    def _loop(self):
        while not self._stop.is_set():
            self._check_all()
            self._stop.wait(self.interval)

    def _check_all(self):
        sites = self.db.get_online_sites()
        if not sites:
            return

        print(f"\n  [monitor] Checking {len(sites)} online sites...")

        went_offline = []
        came_online = []

        def _check_one(site):
            url = site["url"]
            sess = self.sessions[hash(url) % len(self.sessions)]
            result = check_site(url, sess, self.timeout, self.retries)

            if result.is_online and site["status"] != "online":
                cat = categorize(result.title)
                self.db.update_site(url, title=result.title, status="online", category=cat, response_time_ms=result.response_time_ms)
                return "online", {"url": url, "title": result.title}
            elif not result.is_online and site["status"] == "online":
                self.db.update_site(url, status="offline", response_time_ms=result.response_time_ms)
                return "offline", {"url": url}
            else:
                self.db.update_site(url, response_time_ms=result.response_time_ms)
                return "same", None

        with ThreadPoolExecutor(max_workers=min(len(self.sessions), len(sites))) as executor:
            futures = {executor.submit(_check_one, s): s for s in sites}
            for future in as_completed(futures):
                try:
                    status, data = future.result()
                    if status == "offline" and data:
                        went_offline.append(data)
                        print(f"  [monitor] OFFLINE: {data['url']}")
                    elif status == "online" and data:
                        came_online.append(data)
                        print(f"  [monitor] BACK ONLINE: {data['url']}")
                except Exception:
                    pass

        if went_offline or came_online:
            tg_token, tg_chat = load_config()
            if tg_token and tg_chat:
                send_monitor_alert(went_offline, came_online)

        total_off = len(went_offline)
        total_on = len(came_online)
        if total_off or total_on:
            print(f"  [monitor] Changes: {total_off} went offline, {total_on} came online")
        else:
            print(f"  [monitor] No changes. All {len(sites)} sites still online.")