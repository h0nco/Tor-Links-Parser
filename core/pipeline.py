from core.database import Database
import re
import hashlib
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

ONION_RE = re.compile(r'https?://[a-z2-7]{56}\.onion(?:/[^\s"\'<>]*)?', re.IGNORECASE)
BARE_RE = re.compile(r'[a-z2-7]{56}\.onion', re.IGNORECASE)
IGNORE_FILE: Path = Path(__file__).parent.parent / "ignore_titles.txt"
_ignore_cache: Optional[list[str]] = None

CATEGORIES: dict[str, list[str]] = {
    "forum": ["forum", "board", "discussion", "community", "talk", "chat", "thread", "bbs", "chan"],
    "marketplace": ["market", "shop", "store", "buy", "sell", "vendor", "product", "order", "trade"],
    "email": ["mail", "email", "inbox", "webmail", "protonmail", "tutanota", "message"],
    "social": ["social", "network", "profile", "friend", "follow", "feed", "blog"],
    "news": ["news", "press", "journal", "gazette", "times", "report", "headline", "media"],
    "search engine": ["search", "find", "index", "directory", "catalog", "explore", "engine"],
    "hosting": ["hosting", "host", "server", "upload", "storage", "file", "pastebin", "paste"],
    "crypto": ["bitcoin", "crypto", "btc", "monero", "xmr", "wallet", "exchange", "mixer"],
    "wiki": ["wiki", "encyclopedia", "knowledge", "library", "documentation", "guide"],
    "security": ["security", "privacy", "vpn", "encrypt", "pgp", "secure", "anonymous", "leak"],
    "tech": ["tech", "code", "developer", "programming", "software", "linux", "git", "open source"],
}

LANG_PATTERNS: dict[str, list[re.Pattern]] = {
    "ru": [re.compile(r'[а-яёА-ЯЁ]{3,}'), re.compile(r'\b(и|в|на|не|что|это|как|для)\b')],
    "en": [re.compile(r'\b(the|and|for|that|with|this|from|have|are|was)\b', re.I)],
    "de": [re.compile(r'\b(und|der|die|das|ist|nicht|ein|ich)\b', re.I)],
    "fr": [re.compile(r'\b(les|des|est|une|que|pas|pour|dans)\b', re.I)],
    "es": [re.compile(r'\b(que|los|las|por|una|para|con|del)\b', re.I)],
    "zh": [re.compile(r'[\u4e00-\u9fff]{2,}')],
    "ar": [re.compile(r'[\u0600-\u06ff]{3,}')],
    "ja": [re.compile(r'[\u3040-\u309f\u30a0-\u30ff]{2,}')],
}


@dataclass
class SiteData:
    url: str
    html: str = ""
    status_code: int = 0
    title: str = ""
    category: str = "uncategorized"
    language: str = ""
    content_hash: str = ""
    duplicate_of: str = ""
    server_header: str = ""
    powered_by: str = ""
    content_type: str = ""
    response_time_ms: int = 0
    attempts: int = 0
    found_links: list[str] = field(default_factory=list)
    is_online: bool = False
    is_ignored: bool = False
    error: str = ""


def _load_ignore() -> list[str]:
    global _ignore_cache
    if _ignore_cache is not None:
        return _ignore_cache
    if not IGNORE_FILE.exists():
        _ignore_cache = []
        return _ignore_cache
    try:
        _ignore_cache = [l.strip().lower() for l in IGNORE_FILE.read_text(encoding="utf-8").splitlines()
                         if l.strip() and not l.startswith("#")]
    except OSError:
        _ignore_cache = []
    return _ignore_cache


def step_parse(data: SiteData) -> SiteData:
    if not data.is_online or not data.html:
        return data
    try:
        from bs4 import BeautifulSoup
        soup = BeautifulSoup(data.html, "html.parser")
        if soup.title and soup.title.string:
            data.title = soup.title.string.strip()[:200]
    except ImportError:
        m = re.search(r"<title[^>]*>(.*?)</title>", data.html, re.I | re.DOTALL)
        if m:
            data.title = re.sub(r"<[^>]+>", "", m.group(1)).strip()[:200]
    except Exception:
        pass
    data.content_hash = hashlib.md5(data.html.encode("utf-8", errors="ignore")).hexdigest()
    links: set[str] = set()
    for match in ONION_RE.findall(data.html):
        parts = match.split("/")
        if len(parts) >= 3:
            base = parts[0] + "//" + parts[2]
            if base.endswith(".onion") and base.rstrip("/") != data.url.rstrip("/"):
                links.add(base)
    for match in BARE_RE.findall(data.html):
        link = "http://" + match
        if link.rstrip("/") != data.url.rstrip("/"):
            links.add(link)
    data.found_links = list(links)
    return data


def step_filter(data: SiteData) -> SiteData:
    if not data.is_online:
        return data
    if data.title:
        t: str = data.title.lower()
        if any(p in t for p in _load_ignore()):
            data.is_ignored = True
    return data


def step_categorize(data: SiteData) -> SiteData:
    if not data.is_online or data.is_ignored or not data.title:
        return data
    t: str = data.title.lower()
    scores: dict[str, int] = {c: sum(1 for k in kw if k in t) for c, kw in CATEGORIES.items()}
    scores = {k: v for k, v in scores.items() if v > 0}
    if scores:
        data.category = max(scores, key=scores.get)
    return data


def step_detect_language(data: SiteData) -> SiteData:
    if not data.is_online or data.is_ignored or not data.html or len(data.html) < 20:
        return data
    text: str = re.sub(r'<[^>]+>', '', data.html)[:5000]
    scores: dict[str, int] = {l: sum(len(p.findall(text)) for p in ps) for l, ps in LANG_PATTERNS.items()}
    scores = {k: v for k, v in scores.items() if v >= 3}
    if scores:
        data.language = max(scores, key=scores.get)
    return data


def step_deduplicate(data: SiteData, db: "  Database") -> SiteData:
    if not data.is_online or data.is_ignored:
        return data
    existing: Optional[str] = db.find_by_hash(data.content_hash)
    if existing and existing != data.url:
        data.duplicate_of = existing
    return data


def step_store(data: SiteData, db: "Database") -> SiteData:
    if data.is_ignored:
        return data
    kw: dict = dict(
        title=data.title, status="online" if data.is_online else "offline",
        category=data.category, response_time_ms=data.response_time_ms,
        language=data.language, content_hash=data.content_hash,
        duplicate_of=data.duplicate_of, server_header=data.server_header,
        powered_by=data.powered_by, content_type=data.content_type,
    )
    if db.site_exists(data.url):
        db.update_site(data.url, **kw)
    else:
        db.add_site(data.url, **kw)
    return data


def run_pipeline(data: SiteData, db: "Database") -> SiteData:
    data = step_parse(data)
    data = step_filter(data)
    data = step_categorize(data)
    data = step_detect_language(data)
    data = step_deduplicate(data, db)
    data = step_store(data, db)
    return data