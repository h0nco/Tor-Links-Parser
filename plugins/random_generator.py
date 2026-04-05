import random
import string
from core.plugins import SourcePlugin

BASE32_ALPHABET = "abcdefghijklmnopqrstuvwxyz234567"

class RandomOnionGenerator(SourcePlugin):
    name = "random_onion"
    description = "Generates random valid .onion v3 addresses (no network)"

    async def scrape(self, session):
        onions = set()
        for _ in range(5000):
            random_part = ''.join(random.choices(BASE32_ALPHABET, k=56))
            onions.add(f"http://{random_part}.onion")
        self._log(f"Generated {len(onions)} random addresses")
        return list(onions)