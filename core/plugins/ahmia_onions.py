from core.plugins import SourcePlugin

class AhmiaOnions(SourcePlugin):
    name = "ahmia_onions"
    description = "Fresh onions from Ahmia's known list"

    async def scrape(self, session):
        found = set()
        url = "http://juhanurmihxlp77nkq76byazcldy2hlmovfu2epvl5ankdibsot4csyd.onion/onions/"
        try:
            async with session.get(url, timeout=30) as r:
                text = await r.text()
                found.update(self.extract_onions(text))
        except Exception:
            pass
        return list(found)