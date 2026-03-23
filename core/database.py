import sqlite3
import threading
import time
from datetime import datetime
from pathlib import Path
from typing import Optional

DB_PATH: Path = Path(__file__).parent.parent / "data" / "onion_sites.db"
MAX_RETRIES: int = 3
RETRY_DELAY: float = 0.5


class Database:
    def __init__(self) -> None:
        DB_PATH.parent.mkdir(parents=True, exist_ok=True)
        self._lock: threading.Lock = threading.Lock()
        self._conn: sqlite3.Connection = sqlite3.connect(str(DB_PATH), check_same_thread=False, timeout=10)
        self._conn.row_factory = sqlite3.Row
        self._conn.execute("PRAGMA journal_mode=WAL")
        self._conn.execute("PRAGMA busy_timeout=5000")
        self._conn.executescript("""
            CREATE TABLE IF NOT EXISTS sites (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                url TEXT UNIQUE NOT NULL,
                title TEXT DEFAULT '',
                status TEXT DEFAULT 'unknown',
                category TEXT DEFAULT 'uncategorized',
                language TEXT DEFAULT '',
                content_hash TEXT DEFAULT '',
                duplicate_of TEXT DEFAULT '',
                server_header TEXT DEFAULT '',
                powered_by TEXT DEFAULT '',
                content_type TEXT DEFAULT '',
                first_seen TEXT NOT NULL,
                last_checked TEXT,
                last_online TEXT,
                response_time_ms INTEGER DEFAULT 0,
                check_count INTEGER DEFAULT 0
            );
            CREATE INDEX IF NOT EXISTS idx_status ON sites(status);
            CREATE INDEX IF NOT EXISTS idx_category ON sites(category);
        """)
        self._conn.commit()
        self._migrate()

    def _migrate(self) -> None:
        cols: set[str] = {r[1] for r in self._conn.execute("PRAGMA table_info(sites)").fetchall()}
        new_cols: list[tuple[str, str]] = [
            ("language", "TEXT DEFAULT ''"), ("content_hash", "TEXT DEFAULT ''"),
            ("duplicate_of", "TEXT DEFAULT ''"), ("server_header", "TEXT DEFAULT ''"),
            ("powered_by", "TEXT DEFAULT ''"), ("content_type", "TEXT DEFAULT ''"),
        ]
        for col, ctype in new_cols:
            if col not in cols:
                self._conn.execute(f"ALTER TABLE sites ADD COLUMN {col} {ctype}")
        self._conn.commit()

    def _execute_safe(self, query: str, params: tuple = ()) -> Optional[sqlite3.Cursor]:
        for attempt in range(MAX_RETRIES):
            try:
                with self._lock:
                    cursor = self._conn.execute(query, params)
                    self._conn.commit()
                    return cursor
            except sqlite3.OperationalError as e:
                if "locked" in str(e) and attempt < MAX_RETRIES - 1:
                    time.sleep(RETRY_DELAY * (attempt + 1))
                else:
                    from core.log import error
                    error(f"DB error: {e}")
                    return None
        return None

    def add_site(self, url: str, **kw: object) -> bool:
        now: str = datetime.utcnow().isoformat()
        with self._lock:
            try:
                self._conn.execute(
                    "INSERT INTO sites (url,title,status,category,language,content_hash,duplicate_of,server_header,powered_by,content_type,first_seen,last_checked,last_online,response_time_ms,check_count) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,1)",
                    (url, kw.get("title", ""), kw.get("status", "unknown"), kw.get("category", "uncategorized"),
                     kw.get("language", ""), kw.get("content_hash", ""), kw.get("duplicate_of", ""),
                     kw.get("server_header", ""), kw.get("powered_by", ""), kw.get("content_type", ""),
                     now, now, now if kw.get("status") == "online" else None, kw.get("response_time_ms", 0)))
                self._conn.commit()
                return True
            except sqlite3.IntegrityError:
                return False
            except sqlite3.OperationalError as e:
                from core.log import error
                error(f"DB add error: {e}")
                return False

    def update_site(self, url: str, **kw: object) -> None:
        now: str = datetime.utcnow().isoformat()
        with self._lock:
            try:
                if not self._conn.execute("SELECT 1 FROM sites WHERE url=?", (url,)).fetchone():
                    return
                f: list[str] = ["last_checked=?", "check_count=check_count+1"]
                v: list[object] = [now]
                for k in ("title", "status", "category", "response_time_ms", "language",
                          "content_hash", "duplicate_of", "server_header", "powered_by", "content_type"):
                    if k in kw and kw[k] is not None:
                        f.append(f"{k}=?")
                        v.append(kw[k])
                if kw.get("status") == "online":
                    f.append("last_online=?")
                    v.append(now)
                v.append(url)
                self._conn.execute(f"UPDATE sites SET {','.join(f)} WHERE url=?", v)
                self._conn.commit()
            except sqlite3.OperationalError as e:
                from core.log import error
                error(f"DB update error: {e}")

    def find_by_hash(self, h: str) -> Optional[str]:
        if not h:
            return None
        with self._lock:
            try:
                r = self._conn.execute("SELECT url FROM sites WHERE content_hash=? AND duplicate_of='' LIMIT 1", (h,)).fetchone()
                return r["url"] if r else None
            except sqlite3.OperationalError:
                return None

    def site_exists(self, url: str) -> bool:
        with self._lock:
            try:
                return self._conn.execute("SELECT 1 FROM sites WHERE url=?", (url,)).fetchone() is not None
            except sqlite3.OperationalError:
                return False

    def get_stats(self) -> dict:
        with self._lock:
            try:
                r = self._conn.execute("SELECT COUNT(*) as total, SUM(CASE WHEN status='online' THEN 1 ELSE 0 END) as online, SUM(CASE WHEN status='offline' THEN 1 ELSE 0 END) as offline FROM sites").fetchone()
                return dict(r)
            except sqlite3.OperationalError:
                return {"total": 0, "online": 0, "offline": 0}

    def get_online_sites(self) -> list[dict]:
        with self._lock:
            try:
                return [dict(r) for r in self._conn.execute("SELECT * FROM sites WHERE status='online' ORDER BY last_checked DESC LIMIT 10000").fetchall()]
            except sqlite3.OperationalError:
                return []

    def export_json(self) -> list[dict]:
        with self._lock:
            try:
                return [dict(r) for r in self._conn.execute("SELECT * FROM sites ORDER BY last_checked DESC").fetchall()]
            except sqlite3.OperationalError:
                return []