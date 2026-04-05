from core.plugins import SourcePlugin

class RedditOnionWiki(SourcePlugin):
    name = "reddit_wiki"
    description = "Reddit /r/onions wiki page"

    async def scrape(self, session):
        self._log("fetching Reddit onion wiki...")
        # Без www, правильный домен
        url = "http://reddittorjg6rue252oqsxryoxengawnmo46qy4kyii5wtqnwfj4ooad.onion/r/onions/wiki/index"
        text = await self._fetch(session, url)
        if not text:
            return []
        links = self.extract_onions(text)
        self._log(f"found {len(links)} addresses")
        return links