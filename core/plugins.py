import importlib
import importlib.util
import re
import asyncio
from pathlib import Path
from typing import List
from abc import ABC, abstractmethod

import aiohttp

PLUGINS_DIR: Path = Path(__file__).parent.parent / "plugins"
ONION_RE: re.Pattern = re.compile(r'[a-z2-7]{56}\.onion', re.IGNORECASE)
FETCH_TIMEOUT: int = 60


class SourcePlugin(ABC):
    name: str = "base"
    description: str = ""

    @abstractmethod
    async def scrape(self, session: aiohttp.ClientSession) -> List[str]:
        pass

    def extract_onions(self, text: str) -> List[str]:
        return list({f"http://{m.lower()}" for m in ONION_RE.findall(text)})

    async def _fetch(self, session: aiohttp.ClientSession, url: str) -> str:
        from core.log import debug
        try:
            to = aiohttp.ClientTimeout(total=FETCH_TIMEOUT)
            async with session.get(url, timeout=to, allow_redirects=True) as r:
                if r.status >= 400:
                    debug(f"[{self.name}] {url[:60]} -> HTTP {r.status}")
                    return ""
                text: str = await r.text(errors="ignore")
                debug(f"[{self.name}] {url[:60]} -> {len(text)} bytes")
                return text
        except asyncio.TimeoutError:
            debug(f"[{self.name}] {url[:60]} -> timeout ({FETCH_TIMEOUT}s)")
            return ""
        except aiohttp.ClientError as e:
            debug(f"[{self.name}] {url[:60]} -> {e}")
            return ""
        except Exception as e:
            debug(f"[{self.name}] {url[:60]} -> {type(e).__name__}: {e}")
            return ""

    async def _fetch_pages(self, session: aiohttp.ClientSession, urls: List[str]) -> str:
        all_text: str = ""
        for url in urls:
            text = await self._fetch(session, url)
            if text:
                all_text += text
        return all_text

    def _log(self, msg: str) -> None:
        from core.log import info
        info(f"  [{self.name}] {msg}")


class AhmiaOnions(SourcePlugin):
    name = "ahmia_onions"
    description = "Fresh onions from Ahmia's known list"

    async def scrape(self, session: aiohttp.ClientSession) -> List[str]:
        self._log("fetching onion list...")
        text = await self._fetch(session, "http://juhanurmihxlp77nkq76byazcldy2hlmovfu2epvl5ankdibsot4csyd.onion/onions/")
        links = self.extract_onions(text)
        self._log(f"{len(links)} addresses" if links else "no response")
        return links


class TorLinks(SourcePlugin):
    name = "torlinks"
    description = "TorLinks directory"

    async def scrape(self, session: aiohttp.ClientSession) -> List[str]:
        self._log("fetching directory...")
        text = await self._fetch(session, "http://torlinksge6enmcyyuxjpjhidqd2qzrj7bqat4ncqjolojz2bijlaid.onion")
        links = self.extract_onions(text)
        self._log(f"{len(links)} addresses" if links else "no response")
        return links


class Donion(SourcePlugin):
    name = "donion"
    description = "Donion directory"

    async def scrape(self, session: aiohttp.ClientSession) -> List[str]:
        self._log("fetching directory...")
        text = await self._fetch(session, "http://donionsixbjtiohce24abfgsffo2l4tk26qx464wo2x7tuz6gkxqhqad.onion")
        links = self.extract_onions(text)
        self._log(f"{len(links)} addresses" if links else "no response")
        return links


class DarkDirOnion(SourcePlugin):
    name = "darkdir"
    description = "Dark.fail mirror directory"

    async def scrape(self, session: aiohttp.ClientSession) -> List[str]:
        urls: List[str] = [
            "http://darkfailenbsdla5mal2mxn2uz66od5vtzd5qozslagrfzachha3f3id.onion",
            "http://darkfailllnkf4vf.onion",
        ]
        found: set[str] = set()
        for url in urls:
            self._log(f"trying {url[:50]}...")
            text = await self._fetch(session, url)
            if text:
                found.update(self.extract_onions(text))
                self._log(f"+{len(self.extract_onions(text))} from {url[:30]}")
                break
        return list(found)


class OnionTreePlugin(SourcePlugin):
    name = "oniontree"
    description = "OnionTree tagged services"

    async def scrape(self, session: aiohttp.ClientSession) -> List[str]:
        self._log("fetching oniontree...")
        urls: List[str] = [
            "http://onions53ehmf4q75.onion",
            "http://oniontreeqbqtt2a5577xvnmvfor3cmll6hbjhsco6kv3v6gixqoqd.onion",
        ]
        found: set[str] = set()
        for url in urls:
            text = await self._fetch(session, url)
            if text:
                found.update(self.extract_onions(text))
                break
        self._log(f"{len(found)} addresses" if found else "no response")
        return list(found)


class TorTaxiPlugin(SourcePlugin):
    name = "tortaxi"
    description = "Tor.Taxi link aggregator"

    async def scrape(self, session: aiohttp.ClientSession) -> List[str]:
        self._log("fetching tor.taxi...")
        text = await self._fetch(session, "http://tortaxi2dev6xjwbaydqzla77rrnth7yn2oqadup4wkhbh6gp7reh3yd.onion")
        links = self.extract_onions(text)
        self._log(f"{len(links)} addresses" if links else "no response")
        return links


class HiddenWikiPlugin(SourcePlugin):
    name = "hiddenwiki"
    description = "The Hidden Wiki mirror"

    async def scrape(self, session: aiohttp.ClientSession) -> List[str]:
        self._log("fetching hidden wiki...")
        urls: List[str] = [
            "http://zqktlwiuavvvqqt4ybvgvi7tyo4hjl5xgfuvpdf6otjiycgwqbym2qad.onion",
            "http://s4k4ceiapber4o5v5qpdfg3cuykqko3eeyloe5ki6gn3qkxfcdbmwoad.onion",
        ]
        found: set[str] = set()
        for url in urls:
            text = await self._fetch(session, url)
            if text:
                found.update(self.extract_onions(text))
                if found:
                    break
        self._log(f"{len(found)} addresses" if found else "no response")
        return list(found)


class OnionLinksPlugin(SourcePlugin):
    name = "onionlinks"
    description = "Various onion link aggregation pages"

    async def scrape(self, session: aiohttp.ClientSession) -> List[str]:
        self._log("fetching link pages...")
        urls: List[str] = [
            "http://megalzwink435kangsseahebpbp3teedi4jjt64ne2g6d3oqy3qlweid.onion",
            "http://catalogpwwlccc5nyp3m3xng6pdx3rdcknul57x6raxwf4enpw3nymqd.onion",
        ]
        found: set[str] = set()
        for url in urls:
            text = await self._fetch(session, url)
            if text:
                new = self.extract_onions(text)
                found.update(new)
                if new:
                    self._log(f"+{len(new)} from {url[:40]}")
        self._log(f"total: {len(found)}" if found else "no results")
        return list(found)


BUILTIN: list[type[SourcePlugin]] = [
    AhmiaOnions, TorLinks, Donion, DarkDirOnion,
    OnionTreePlugin, TorTaxiPlugin, HiddenWikiPlugin, OnionLinksPlugin,
]

_plugins: List[SourcePlugin] = []


def load_plugins() -> List[SourcePlugin]:
    global _plugins
    _plugins = [cls() for cls in BUILTIN]

    if PLUGINS_DIR.exists():
        for f in sorted(PLUGINS_DIR.glob("*.py")):
            if f.name.startswith("_"):
                continue
            try:
                spec = importlib.util.spec_from_file_location(f.stem, f)
                if spec and spec.loader:
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