from core.plugins import SourcePlugin

class Donion(SourcePlugin):
    name = "donion"
    description = "Donion .onion directory"

    async def scrape(self, session):
        found = set()
        url = "http://donionsixbjtiohce24abfgsffo2l4tk26qx464wo2x7tuz6gkxqhqad.onion"
        try:
            async with session.get(url, timeout=30) as r:
                text = await r.text()
                found.update(self.extract_onions(text))
        except Exception:
            pass
        return list(found)