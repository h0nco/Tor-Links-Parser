import re
import time
import socket
import hashlib
from dataclasses import dataclass, field
from typing import Optional, Tuple, List

import requests
import socks


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


ONION_REGEX = re.compile(r'https?://[a-z2-7]{56}\.onion(?:/[^\s"\'<>]*)?', re.IGNORECASE)
BARE_ONION_REGEX = re.compile(r'[a-z2-7]{56}\.onion', re.IGNORECASE)


def find_tor_port():
    for port in (9150, 9050):
        try:
            s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            s.settimeout(3)
            result = s.connect_ex(("127.0.0.1", port))
            s.close()
            if result == 0:
                return port
        except Exception:
            continue
    return None


def make_session(port):
    session = requests.Session()
    proxy_url = f"socks5h://127.0.0.1:{port}"
    session.proxies = {"http": proxy_url, "https": proxy_url}
    session.headers["User-Agent"] = "Mozilla/5.0 (Windows NT 10.0; rv:128.0) Gecko/20100101 Firefox/128.0"
    return session


def test_tor_connection(session):
    try:
        r = session.get("https://check.torproject.org/api/ip", timeout=20)
        data = r.json()
        if data.get("IsTor"):
            return True, f"Tor OK, IP: {data.get('IP', '???')}"
        return False, f"Not through Tor (IP: {data.get('IP', '???')})"
    except requests.exceptions.ConnectionError as e:
        return False, f"Connection error: {e}"
    except requests.exceptions.Timeout:
        return False, "Timeout (20s)"
    except Exception as e:
        return False, str(e)


def connect_tor():
    port = find_tor_port()
    if port is None:
        return None, "Tor not found. Start Tor Browser or Tor Expert Bundle (port 9150/9050)."
    session = make_session(port)
    ok, msg = test_tor_connection(session)
    if ok:
        return session, f"Connected via port {port}. {msg}"
    return None, f"Port {port} open but Tor not working: {msg}"


def renew_circuit(port=None):
    if port is None:
        port = find_tor_port()
    control_port = 9151 if port == 9150 else 9051
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        s.settimeout(5)
        s.connect(("127.0.0.1", control_port))
        s.send(b'AUTHENTICATE ""\r\n')
        resp = s.recv(256)
        if b"250" in resp:
            s.send(b"SIGNAL NEWNYM\r\n")
            resp = s.recv(256)
            s.close()
            if b"250" in resp:
                return True
        s.close()
    except Exception:
        pass
    return False


def check_site(url, session, timeout=30, retries=3, retry_delay=2):
    last_error = ""
    total_ms = 0

    for attempt in range(1, retries + 1):
        start = time.time()
        try:
            r = session.get(url, timeout=timeout, allow_redirects=True)
            ms = int((time.time() - start) * 1000)
            total_ms = ms

            if r.status_code < 500:
                html = r.text
                title = _extract_title(html)
                content_hash = hashlib.md5(html.encode("utf-8", errors="ignore")).hexdigest()
                found_links = _extract_onion_links(html, url)
                return CheckResult(url, True, title, ms, "", attempt, content_hash, found_links, html)
            last_error = f"HTTP {r.status_code}"

        except requests.exceptions.Timeout:
            total_ms = int((time.time() - start) * 1000)
            last_error = "Timeout"
        except requests.exceptions.ConnectionError:
            total_ms = int((time.time() - start) * 1000)
            last_error = "Connection refused"
        except Exception as e:
            total_ms = int((time.time() - start) * 1000)
            last_error = str(e)[:80]

        if attempt < retries:
            time.sleep(retry_delay)

    return CheckResult(url, False, "", total_ms, last_error, retries)


def _extract_title(html):
    try:
        from bs4 import BeautifulSoup
        soup = BeautifulSoup(html, "html.parser")
        if soup.title and soup.title.string:
            return soup.title.string.strip()[:200]
    except ImportError:
        pass
    m = re.search(r"<title[^>]*>(.*?)</title>", html, re.IGNORECASE | re.DOTALL)
    if m:
        return re.sub(r"<[^>]+>", "", m.group(1)).strip()[:200]
    return ""


def _extract_onion_links(html, source_url):
    links = set()
    for match in ONION_REGEX.findall(html):
        base = match.split("/")[0] + "//" + match.split("/")[2]
        if base.endswith(".onion"):
            base = base.rstrip("/")
            if base != source_url.rstrip("/"):
                links.add(base if base.startswith("http") else "http://" + base)
    for match in BARE_ONION_REGEX.findall(html):
        link = "http://" + match
        if link.rstrip("/") != source_url.rstrip("/"):
            links.add(link)
    return list(links)