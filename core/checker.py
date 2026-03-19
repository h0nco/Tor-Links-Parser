import re
import time
import socket
import hashlib
from dataclasses import dataclass, field
from typing import List

import requests
import socks

ONION_RE = re.compile(r'https?://[a-z2-7]{56}\.onion(?:/[^\s"\'<>]*)?', re.IGNORECASE)
BARE_RE = re.compile(r'[a-z2-7]{56}\.onion', re.IGNORECASE)


@dataclass
class CheckResult:
    url: str
    is_online: bool
    title: str
    response_time_ms: int
    error: str
    attempts: int
    content_hash: str = ""
    found_links: List[str] = field(default_factory=list)
    html: str = ""
    server_header: str = ""
    powered_by: str = ""
    content_type: str = ""


def find_tor_port(ports=None):
    for port in (ports or [9150, 9050]):
        try:
            s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            s.settimeout(3)
            r = s.connect_ex(("127.0.0.1", port))
            s.close()
            if r == 0:
                return port
        except Exception:
            continue
    return None


def make_session(port):
    s = requests.Session()
    s.proxies = {"http": f"socks5h://127.0.0.1:{port}", "https": f"socks5h://127.0.0.1:{port}"}
    s.headers["User-Agent"] = "Mozilla/5.0 (Windows NT 10.0; rv:128.0) Gecko/20100101 Firefox/128.0"
    return s


def test_tor_connection(session):
    try:
        r = session.get("https://check.torproject.org/api/ip", timeout=20)
        d = r.json()
        if d.get("IsTor"):
            return True, f"Tor OK, IP: {d.get('IP','?')}"
        return False, f"Not through Tor (IP: {d.get('IP','?')})"
    except Exception as e:
        return False, str(e)[:100]


def renew_circuit(port=None):
    if port is None:
        port = find_tor_port()
    cp = 9151 if port == 9150 else 9051
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        s.settimeout(5)
        s.connect(("127.0.0.1", cp))
        s.send(b'AUTHENTICATE ""\r\n')
        if b"250" in s.recv(256):
            s.send(b"SIGNAL NEWNYM\r\n")
            ok = b"250" in s.recv(256)
            s.close()
            return ok
        s.close()
    except Exception:
        pass
    return False


def check_site(url, session, timeout=20, retries=2, retry_delay=3):
    last_error = ""
    ms = 0
    for attempt in range(1, retries + 1):
        start = time.time()
        try:
            r = session.get(url, timeout=timeout, allow_redirects=True)
            ms = int((time.time() - start) * 1000)
            if r.status_code < 500:
                html = r.text
                title = _extract_title(html)
                ch = hashlib.md5(html.encode("utf-8", errors="ignore")).hexdigest()
                links = _extract_links(html, url)
                srv = r.headers.get("Server", "")
                pwb = r.headers.get("X-Powered-By", "")
                ct = r.headers.get("Content-Type", "")
                return CheckResult(url, True, title, ms, "", attempt, ch, links, html, srv, pwb, ct)
            last_error = f"HTTP {r.status_code}"
        except requests.exceptions.Timeout:
            ms = int((time.time() - start) * 1000)
            last_error = "Timeout"
        except requests.exceptions.ConnectionError:
            ms = int((time.time() - start) * 1000)
            last_error = "Connection refused"
        except Exception as e:
            ms = int((time.time() - start) * 1000)
            last_error = str(e)[:80]
        if attempt < retries:
            time.sleep(retry_delay)
    return CheckResult(url, False, "", ms, last_error, retries)


def _extract_title(html):
    try:
        from bs4 import BeautifulSoup
        soup = BeautifulSoup(html, "html.parser")
        if soup.title and soup.title.string:
            return soup.title.string.strip()[:200]
    except ImportError:
        pass
    m = re.search(r"<title[^>]*>(.*?)</title>", html, re.IGNORECASE | re.DOTALL)
    return re.sub(r"<[^>]+>", "", m.group(1)).strip()[:200] if m else ""


def _extract_links(html, source):
    links = set()
    for match in ONION_RE.findall(html):
        parts = match.split("/")
        if len(parts) >= 3:
            base = parts[0] + "//" + parts[2]
            if base.endswith(".onion") and base.rstrip("/") != source.rstrip("/"):
                links.add(base)
    for match in BARE_RE.findall(html):
        link = "http://" + match
        if link.rstrip("/") != source.rstrip("/"):
            links.add(link)
    return list(links)