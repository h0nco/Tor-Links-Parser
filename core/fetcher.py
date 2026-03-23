import time
import socket
import asyncio
from typing import Optional

import aiohttp
from aiohttp_socks import ProxyConnector

from core import config
from core import log
from core.pipeline import SiteData


def find_tor_port() -> Optional[int]:
    for port in config.get("tor", "ports", [9150, 9050]):
        try:
            s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            s.settimeout(3)
            r = s.connect_ex(("127.0.0.1", port))
            s.close()
            if r == 0:
                return port
        except OSError:
            continue
    return None


async def create_session(port: int) -> aiohttp.ClientSession:
    connector = ProxyConnector.from_url(f"socks5://127.0.0.1:{port}", rdns=True)
    timeout = aiohttp.ClientTimeout(total=config.get("tor", "timeout", 20))
    return aiohttp.ClientSession(
        connector=connector, timeout=timeout,
        headers={"User-Agent": "Mozilla/5.0 (Windows NT 10.0; rv:128.0) Gecko/20100101 Firefox/128.0"}
    )


async def test_tor(session: aiohttp.ClientSession) -> tuple[bool, str]:
    try:
        async with session.get("https://check.torproject.org/api/ip") as r:
            d = await r.json()
            if d.get("IsTor"):
                return True, f"Tor OK, IP: {d.get('IP', '?')}"
            return False, f"Not through Tor (IP: {d.get('IP', '?')})"
    except asyncio.TimeoutError:
        return False, "Timeout checking Tor"
    except aiohttp.ClientError as e:
        return False, f"Connection error: {e}"
    except Exception as e:
        return False, str(e)[:100]


async def fetch(url: str, session: aiohttp.ClientSession,
                retries: int = 2, retry_delay: int = 3) -> "SiteData":
    from core.pipeline import SiteData
    data = SiteData(url=url)

    for attempt in range(1, retries + 1):
        start: float = time.time()
        try:
            async with session.get(url, allow_redirects=True) as r:
                ms = int((time.time() - start) * 1000)
                data.response_time_ms = ms
                data.attempts = attempt
                data.status_code = r.status
                data.server_header = r.headers.get("Server", "")
                data.powered_by = r.headers.get("X-Powered-By", "")
                data.content_type = r.headers.get("Content-Type", "")
                if r.status < 500:
                    data.html = await r.text(errors="ignore")
                    data.is_online = True
                    return data
                data.error = f"HTTP {r.status}"
        except asyncio.TimeoutError:
            data.response_time_ms = int((time.time() - start) * 1000)
            data.error = "Timeout"
            data.attempts = attempt
        except aiohttp.ServerDisconnectedError:
            data.response_time_ms = int((time.time() - start) * 1000)
            data.error = "Server disconnected"
            data.attempts = attempt
        except aiohttp.ClientConnectorError:
            data.response_time_ms = int((time.time() - start) * 1000)
            data.error = "Connection refused"
            data.attempts = attempt
        except aiohttp.ClientError as e:
            data.response_time_ms = int((time.time() - start) * 1000)
            data.error = str(e)[:80]
            data.attempts = attempt
        except Exception as e:
            data.response_time_ms = int((time.time() - start) * 1000)
            data.error = f"{type(e).__name__}: {str(e)[:60]}"
            data.attempts = attempt
            log.debug(f"Fetch unexpected error {url}: {e}")

        if attempt < retries:
            await asyncio.sleep(retry_delay)

    return data


def renew_circuit(port: Optional[int] = None) -> bool:
    if port is None:
        port = find_tor_port()
    if port is None:
        return False
    cp: int = 9151 if port == 9150 else 9051
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
    except OSError:
        pass
    return False    