import re
import requests
from typing import List

from core import config

ONION_RE = re.compile(r'[a-z2-7]{56}\.onion', re.IGNORECASE)
UA = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; rv:128.0) Gecko/20100101 Firefox/128.0"}


def _is_onion(url):
    return ".onion" in url


def _scrape(url, session=None, timeout=30):
    found = set()
    try:
        if _is_onion(url) and session:
            r = session.get(url, timeout=timeout)
        else:
            r = requests.get(url, timeout=timeout, headers=UA)
        for m in ONION_RE.findall(r.text):
            found.add(f"http://{m.lower()}")
    except Exception:
        pass
    return list(found)


def get_sources():
    return config.get("discovery", "sources", [])


def discover(session=None, timeout=30) -> List[str]:
    sources = get_sources()
    if not sources:
        return []
    all_found = set()
    for url in sources:
        from core.log import info
        info(f"Scraping: {url[:70]}...")
        links = _scrape(url, session, timeout)
        all_found.update(links)
        for src_onion in [u for u in links if _is_onion(u)]:
            all_found.discard(src_onion)
            all_found.add(src_onion)
        if links:
            info(f"  +{len(links)} addresses")
    return list(all_found)


def deep_crawl_page(url, session, timeout=30) -> List[str]:
    return _scrape(url, session, timeout)