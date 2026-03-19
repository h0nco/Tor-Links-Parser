import threading
from concurrent.futures import ThreadPoolExecutor, as_completed
from core.checker import check_site
from core.categorizer import categorize
from core.telegram import send_monitor_alert, tg_enabled


class Monitor:
    def __init__(self, db, sessions, interval=300):
        self.db = db
        self.sessions = sessions
        self.interval = interval
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
        from core.log import info
        info(f"[monitor] Checking {len(sites)} online sites...")
        went_off, came_on = [], []

        def _check(site):
            url = site["url"]
            s = self.sessions[hash(url) % len(self.sessions)]
            r = check_site(url, s, 20, 2)
            if not r.is_online and site["status"] == "online":
                self.db.update_site(url, status="offline", response_time_ms=r.response_time_ms)
                return "offline", {"url": url}
            elif r.is_online and site["status"] != "online":
                self.db.update_site(url, title=r.title, status="online", category=categorize(r.title), response_time_ms=r.response_time_ms)
                return "online", {"url": url, "title": r.title}
            self.db.update_site(url, response_time_ms=r.response_time_ms)
            return "same", None

        with ThreadPoolExecutor(max_workers=min(len(self.sessions), len(sites))) as ex:
            for f in as_completed({ex.submit(_check, s): s for s in sites}):
                try:
                    st, d = f.result()
                    if st == "offline" and d:
                        went_off.append(d)
                    elif st == "online" and d:
                        came_on.append(d)
                except Exception:
                    pass

        if (went_off or came_on) and tg_enabled():
            send_monitor_alert(went_off, came_on)
        if went_off or came_on:
            info(f"[monitor] {len(went_off)} offline, {len(came_on)} back online")
        else:
            info(f"[monitor] All {len(sites)} still online")