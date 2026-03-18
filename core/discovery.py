import re
import random
import requests
from typing import List

ONION_RE = re.compile(r'[a-z2-7]{56}\.onion', re.IGNORECASE)

SEED_SOURCES = [
    "https://ahmia.fi/search/?q=onion",
    "https://ahmia.fi/search/?q=hidden+service",
    "https://ahmia.fi/search/?q=tor+site",
    "https://ahmia.fi/search/?q=marketplace",
    "https://ahmia.fi/search/?q=forum",
    "https://ahmia.fi/search/?q=email",
    "https://ahmia.fi/search/?q=wiki",
    "https://ahmia.fi/search/?q=search+engine",
    "https://ahmia.fi/search/?q=hosting",
    "https://ahmia.fi/search/?q=blog",
    "https://ahmia.fi/search/?q=news",
    "https://ahmia.fi/search/?q=chat",
    "https://ahmia.fi/search/?q=crypto",
    "https://ahmia.fi/search/?q=privacy",
    "https://ahmia.fi/search/?q=anonymous",
    "https://ahmia.fi/search/?q=secure",
    "https://ahmia.fi/search/?q=free",
    "https://ahmia.fi/search/?q=index",
    "https://ahmia.fi/search/?q=directory",
    "https://ahmia.fi/search/?q=list",
]

ONION_DIRECTORIES = [
    "http://juhanurmihxlp77nkq76byazcldy2hlmovfu2epvl5ankdibsot4csyd.onion"
]

SEARCH_QUERIES = [
    "site", "index", "link", "directory", "onion", "hidden",
    "forum", "market", "email", "wiki", "blog", "chat",
    "hosting", "paste", "crypto", "news", "social", "tool",
    "privacy", "anonymous", "free", "service", "portal",
]


def discover_from_clearnet() -> List[str]:
    found = set()
    headers = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; rv:128.0) Gecko/20100101 Firefox/128.0"}

    for url in SEED_SOURCES:
        try:
            r = requests.get(url, timeout=15, headers=headers)
            matches = ONION_RE.findall(r.text)
            for m in matches:
                found.add(f"http://{m.lower()}")
        except Exception:
            continue

    for page in range(2, 6):
        for q in random.sample(SEARCH_QUERIES, min(5, len(SEARCH_QUERIES))):
            try:
                url = f"https://ahmia.fi/search/?q={q}&page={page}"
                r = requests.get(url, timeout=15, headers=headers)
                matches = ONION_RE.findall(r.text)
                for m in matches:
                    found.add(f"http://{m.lower()}")
            except Exception:
                continue

    return list(found)


def discover_from_tor(session) -> List[str]:
    found = set()

    for url in ONION_DIRECTORIES:
        try:
            r = session.get(url, timeout=30)
            matches = ONION_RE.findall(r.text)
            for m in matches:
                addr = f"http://{m.lower()}"
                if addr.rstrip("/") != url.rstrip("/"):
                    found.add(addr)
        except Exception:
            continue

    return list(found)


def discover_all(session=None) -> List[str]:
    all_found = set()

    clearnet = discover_from_clearnet()
    all_found.update(clearnet)

    if session:
        tor = discover_from_tor(session)
        all_found.update(tor)

    return list(all_found)