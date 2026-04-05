from core.plugins import SourcePlugin

class HiddenWikiZqktl(SourcePlugin):
    name = "hidden_wiki_zqktl"
    description = "The Hidden Wiki (zqktlwiuavvvqqt4ybvgvi7tyo4hjl5xgfuvpdf6otjiycgwqbym2qad.onion)"

    async def scrape(self, session):
        self._log("fetching Hidden Wiki...")
        url = "http://zqktlwiuavvvqqt4ybvgvi7tyo4hjl5xgfuvpdf6otjiycgwqbym2qad.onion/wiki/index.php/Main_Page"
        text = await self._fetch(session, url)
        if not text:
            return []
        links = self.extract_onions(text)
        self._log(f"found {len(links)} addresses")
        return links