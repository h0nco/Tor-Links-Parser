CATEGORIES = {
    "forum": ["forum", "board", "discussion", "community", "talk", "chat", "thread", "bbs", "chan"],
    "marketplace": ["market", "shop", "store", "buy", "sell", "vendor", "product", "order", "trade"],
    "email": ["mail", "email", "inbox", "webmail", "protonmail", "tutanota", "message"],
    "social": ["social", "network", "profile", "friend", "follow", "feed", "blog"],
    "news": ["news", "press", "journal", "gazette", "times", "report", "headline", "media"],
    "search engine": ["search", "find", "index", "directory", "catalog", "explore", "engine"],
    "hosting": ["hosting", "host", "server", "upload", "storage", "file", "pastebin", "paste"],
    "crypto": ["bitcoin", "crypto", "btc", "monero", "xmr", "wallet", "exchange", "mixer"],
    "wiki": ["wiki", "encyclopedia", "knowledge", "library", "documentation", "guide"],
    "security": ["security", "privacy", "vpn", "encrypt", "pgp", "secure", "anonymous", "leak"],
    "tech": ["tech", "code", "developer", "programming", "software", "linux", "git", "open source"],
}

def categorize(title):
    if not title:
        return "uncategorized"
    t = title.lower()
    scores = {c: sum(1 for k in kw if k in t) for c, kw in CATEGORIES.items()}
    scores = {k: v for k, v in scores.items() if v > 0}
    return max(scores, key=scores.get) if scores else "uncategorized"