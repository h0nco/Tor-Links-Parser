import time, socket, asyncio
import aiohttp
from aiohttp_socks import ProxyConnector
from core import config


def find_tor_port():
    for port in config.get("tor", "ports", [9150, 9050]):
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


def make_connector(port):
    return ProxyConnector.from_url(f"socks5://127.0.0.1:{port}", rdns=True)


async def create_session(port):
    connector = make_connector(port)
    timeout = aiohttp.ClientTimeout(total=config.get("tor", "timeout", 20))
    session = aiohttp.ClientSession(
        connector=connector,
        timeout=timeout,
        headers={"User-Agent": "Mozilla/5.0 (Windows NT 10.0; rv:128.0) Gecko/20100101 Firefox/128.0"}
    )
    return session


async def test_tor(session):
    try:
        async with session.get("https://check.torproject.org/api/ip") as r:
            d = await r.json()
            if d.get("IsTor"):
                return True, f"Tor OK, IP: {d.get('IP','?')}"
            return False, f"Not through Tor (IP: {d.get('IP','?')})"
    except Exception as e:
        return False, str(e)[:100]


async def fetch(url, session, retries=2, retry_delay=3):
    from core.pipeline import SiteData
    data = SiteData(url=url)
    for attempt in range(1, retries + 1):
        start = time.time()
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
        except aiohttp.ClientError as e:
            data.response_time_ms = int((time.time() - start) * 1000)
            data.error = str(e)[:80]
            data.attempts = attempt
        except Exception as e:
            data.response_time_ms = int((time.time() - start) * 1000)
            data.error = str(e)[:80]
            data.attempts = attempt
        if attempt < retries:
            await asyncio.sleep(retry_delay)
    return data


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