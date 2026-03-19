import re

P = {
    "ru": [re.compile(r'[а-яёА-ЯЁ]{3,}'), re.compile(r'\b(и|в|на|не|что|это|как|для|или)\b')],
    "en": [re.compile(r'\b(the|and|for|that|with|this|from|have|are|was|not|but)\b', re.I)],
    "de": [re.compile(r'\b(und|der|die|das|ist|nicht|ein|ich|mit|auf)\b', re.I)],
    "fr": [re.compile(r'\b(les|des|est|une|que|pas|pour|dans|par|sur)\b', re.I)],
    "es": [re.compile(r'\b(que|los|las|por|una|para|con|del|son)\b', re.I)],
    "zh": [re.compile(r'[\u4e00-\u9fff]{2,}')],
    "ar": [re.compile(r'[\u0600-\u06ff]{3,}')],
    "ja": [re.compile(r'[\u3040-\u309f\u30a0-\u30ff]{2,}')],
}

def detect_language(text):
    if not text or len(text) < 20:
        return ""
    t = re.sub(r'<[^>]+>', '', text)[:5000]
    scores = {l: sum(len(p.findall(t)) for p in ps) for l, ps in P.items()}
    scores = {k: v for k, v in scores.items() if v > 0}
    if not scores:
        return ""
    best = max(scores, key=scores.get)
    return best if scores[best] >= 3 else ""    