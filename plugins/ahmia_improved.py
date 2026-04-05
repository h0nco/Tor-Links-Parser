from core.plugins import SourcePlugin

class AhmiaImproved(SourcePlugin):
    name = "ahmia_improved"
    description = "Ahmia.fi .onion index (full list)"

    async def scrape(self, session):
        self._log("fetching Ahmia onion list...")
        url = "http://juhanurmihxlp77nkq76byazcldy2hlmovfu2epvl5ankdibsot4csyd.onion/onions/"
        text = await self._fetch(session, url)
        if not text:
            return []
        links = self.extract_onions(text)
        self._log(f"found {len(links)} addresses")
        return links