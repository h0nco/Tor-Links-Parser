from core.plugins import SourcePlugin

class TorLinks(SourcePlugin):
    name = "torlinks"
    description = "TorLinks .onion directory"

    async def scrape(self, session):
        found = set()
        url = "http://torlinksge6enmcyyuxjpjhidqd2qzrj7bqat4ncqjolojz2bijlaid.onion"
        try:
            async with session.get(url, timeout=30) as r:
                text = await r.text()
                found.update(self.extract_onions(text))
        except Exception:
            pass
        return list(found)