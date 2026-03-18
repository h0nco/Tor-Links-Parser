import sqlite3
import threading
from datetime import datetime
from pathlib import Path

DB_PATH = Path(__file__).parent.parent / "data" / "onion_sites.db"


class Database:
    def __init__(self, db_path=None):
        self.db_path = db_path or DB_PATH
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.Lock()
        self._conn = sqlite3.connect(str(self.db_path), check_same_thread=False)
        self._conn.row_factory = sqlite3.Row
        self._conn.execute("PRAGMA journal_mode=WAL")
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

    def _migrate(self):
        cols = {row[1] for row in self._conn.execute("PRAGMA table_info(sites)").fetchall()}
        for col, ctype in [("language", "TEXT DEFAULT ''"), ("content_hash", "TEXT DEFAULT ''"), ("duplicate_of", "TEXT DEFAULT ''")]:
            if col not in cols:
                self._conn.execute(f"ALTER TABLE sites ADD COLUMN {col} {ctype}")
        self._conn.commit()
        try:
            self._conn.execute("CREATE INDEX IF NOT EXISTS idx_hash ON sites(content_hash)")
            self._conn.commit()
        except Exception:
            pass

    def add_site(self, url, title="", status="unknown", category="uncategorized",
                 response_time_ms=0, language="", content_hash="", duplicate_of=""):
        now = datetime.utcnow().isoformat()
        with self._lock:
            try:
                self._conn.execute(
                    "INSERT INTO sites (url,title,status,category,language,content_hash,duplicate_of,first_seen,last_checked,last_online,response_time_ms,check_count) VALUES (?,?,?,?,?,?,?,?,?,?,?,1)",
                    (url, title, status, category, language, content_hash, duplicate_of, now, now, now if status == "online" else None, response_time_ms)
                )
                self._conn.commit()
                return True
            except sqlite3.IntegrityError:
                return False

    def update_site(self, url, **kwargs):
        now = datetime.utcnow().isoformat()
        with self._lock:
            if not self._conn.execute("SELECT 1 FROM sites WHERE url = ?", (url,)).fetchone():
                return
            fields = ["last_checked = ?", "check_count = check_count + 1"]
            values = [now]
            for key in ("title", "status", "category", "response_time_ms", "language", "content_hash", "duplicate_of"):
                if key in kwargs and kwargs[key] is not None:
                    fields.append(f"{key} = ?")
                    values.append(kwargs[key])
            if kwargs.get("status") == "online":
                fields.append("last_online = ?")
                values.append(now)
            values.append(url)
            self._conn.execute(f"UPDATE sites SET {', '.join(fields)} WHERE url = ?", values)
            self._conn.commit()

    def find_by_hash(self, content_hash):
        if not content_hash:
            return None
        with self._lock:
            row = self._conn.execute("SELECT url FROM sites WHERE content_hash = ? AND duplicate_of = '' LIMIT 1", (content_hash,)).fetchone()
        return row["url"] if row else None

    def search(self, query="", status="", category="", limit=500):
        conds, params = [], []
        if query:
            conds.append("(url LIKE ? OR title LIKE ?)")
            params.extend([f"%{query}%", f"%{query}%"])
        if status:
            conds.append("status = ?")
            params.append(status)
        if category:
            conds.append("category = ?")
            params.append(category)
        where = f"WHERE {' AND '.join(conds)}" if conds else ""
        with self._lock:
            rows = self._conn.execute(f"SELECT * FROM sites {where} ORDER BY last_checked DESC LIMIT ?", params + [limit]).fetchall()
        return [dict(r) for r in rows]

    def get_stats(self):
        with self._lock:
            row = self._conn.execute("SELECT COUNT(*) as total, SUM(CASE WHEN status='online' THEN 1 ELSE 0 END) as online, SUM(CASE WHEN status='offline' THEN 1 ELSE 0 END) as offline FROM sites").fetchone()
        return dict(row)

    def get_online_sites(self):
        return self.search(status="online", limit=10000)

    def site_exists(self, url):
        with self._lock:
            return self._conn.execute("SELECT 1 FROM sites WHERE url = ?", (url,)).fetchone() is not None

    def export_json(self):
        with self._lock:
            rows = self._conn.execute("SELECT * FROM sites ORDER BY last_checked DESC").fetchall()
        return [dict(r) for r in rows]