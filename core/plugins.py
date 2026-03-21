import importlib, importlib.util, re, asyncio
from pathlib import Path
from typing import List
from abc import ABC, abstractmethod
import aiohttp

PLUGINS_DIR = Path(__file__).parent.parent / "plugins"
ONION_RE = re.compile(r'[a-z2-7]{56}\.onion', re.IGNORECASE)


class SourcePlugin(ABC):
    name: str = "base"
    description: str = ""

    @abstractmethod
    async def scrape(self, session) -> List[str]:
        pass

    def extract_onions(self, text: str) -> List[str]:
        return list({f"http://{m.lower()}" for m in ONION_RE.findall(text)})

    async def _fetch(self, session, url):
        from core.log import debug
        try:
            to = aiohttp.ClientTimeout(total=60)
            async with session.get(url, timeout=to, allow_redirects=True) as r:
                if r.status >= 400:
                    debug(f"[{self.name}] {url} -> HTTP {r.status}")
                    return ""
                text = await r.text(errors="ignore")
                debug(f"[{self.name}] {url} -> {len(text)} bytes")
                return text
        except asyncio.TimeoutError:
            debug(f"[{self.name}] {url} -> timeout")
            return ""
        except Exception as e:
            debug(f"[{self.name}] {url} -> {e}")
            return ""

    async def _fetch_multi(self, session, urls):
        all_text = ""
        for url in urls:
            text = await self._fetch(session, url)
            all_text += text
            if not text:
                break
        return all_text


class AhmiaOnions(SourcePlugin):
    name = "ahmia_onions"
    description = "Fresh onions from Ahmia's known onion list"

    async def scrape(self, session):
        from core.log import info
        urls = [
            "http://juhanurmihxlp77nkq76byazcldy2hlmovfu2epvl5ankdibsot4csyd.onion/onions/",
        ]
        found = set()
        for url in urls:
            info(f"  [{self.name}] fetching {url[:60]}...")
            text = await self._fetch(session, url)
            if text:
                links = self.extract_onions(text)
                found.update(links)
                info(f"  [{self.name}] got {len(links)} addresses")
            else:
                info(f"  [{self.name}] no response from {url[:60]}")
        return list(found)


class TorLinks(SourcePlugin):
    name = "torlinks"
    description = "TorLinks .onion link directory"

    async def scrape(self, session):
        from core.log import info
        url = "http://torlinksge6enmcyyuxjpjhidqd2qzrj7bqat4ncqjolojz2bijlaid.onion"
        info(f"  [{self.name}] fetching {url[:60]}...")
        text = await self._fetch(session, url)
        if text:
            links = self.extract_onions(text)
            info(f"  [{self.name}] got {len(links)} addresses")
            return links
        info(f"  [{self.name}] no response")
        return []


class Donion(SourcePlugin):
    name = "donion"
    description = "Donion .onion directory"

    async def scrape(self, session):
        from core.log import info
        url = "http://donionsixbjtiohce24abfgsffo2l4tk26qx464wo2x7tuz6gkxqhqad.onion"
        info(f"  [{self.name}] fetching {url[:60]}...")
        text = await self._fetch(session, url)
        if text:
            links = self.extract_onions(text)
            info(f"  [{self.name}] got {len(links)} addresses")
            return links
        info(f"  [{self.name}] no response")
        return []


BUILTIN = [AhmiaOnions, TorLinks, Donion]
_plugins: List[SourcePlugin] = []


def load_plugins():
    global _plugins
    _plugins = [cls() for cls in BUILTIN]

    if PLUGINS_DIR.exists():
        for f in sorted(PLUGINS_DIR.glob("*.py")):
            if f.name.startswith("_"):
                continue
            try:
                spec = importlib.util.spec_from_file_location(f.stem, f)
                mod = importlib.util.module_from_spec(spec)
                spec.loader.exec_module(mod)
                for attr in dir(mod):
                    obj = getattr(mod, attr)
                    if isinstance(obj, type) and issubclass(obj, SourcePlugin) and obj is not SourcePlugin:
                        if obj not in BUILTIN:
                            _plugins.append(obj())
            except Exception as e:
                from core.log import warn
                warn(f"Plugin load error {f.name}: {e}")

    return _plugins


def get_plugins() -> List[SourcePlugin]:
    if not _plugins:
        load_plugins()
    return _plugins