import re

LANG_PATTERNS = {
    "ru": [
        re.compile(r'[а-яёА-ЯЁ]{3,}'),
        re.compile(r'\b(и|в|на|не|что|это|как|для|или)\b'),
    ],
    "en": [
        re.compile(r'\b(the|and|for|that|with|this|from|have|are|was|not|but)\b', re.IGNORECASE),
    ],
    "de": [
        re.compile(r'\b(und|der|die|das|ist|nicht|ein|ich|mit|auf|den|sich)\b', re.IGNORECASE),
        re.compile(r'[äöüßÄÖÜ]'),
    ],
    "fr": [
        re.compile(r'\b(les|des|est|une|que|pas|pour|dans|par|sur|avec|sont)\b', re.IGNORECASE),
        re.compile(r'[àâçéèêëîïôùûüÿœæ]'),
    ],
    "es": [
        re.compile(r'\b(que|los|las|por|una|para|con|del|son|esta|como)\b', re.IGNORECASE),
        re.compile(r'[áéíóúñ¿¡]'),
    ],
    "pt": [
        re.compile(r'\b(que|para|com|uma|por|mais|como|dos|das|não|são)\b', re.IGNORECASE),
        re.compile(r'[ãõçáéíóú]'),
    ],
    "zh": [
        re.compile(r'[\u4e00-\u9fff]{2,}'),
    ],
    "ar": [
        re.compile(r'[\u0600-\u06ff]{3,}'),
    ],
    "ja": [
        re.compile(r'[\u3040-\u309f\u30a0-\u30ff]{2,}'),
    ],
    "ko": [
        re.compile(r'[\uac00-\ud7af]{2,}'),
    ],
}


def detect_language(text):
    if not text or len(text) < 20:
        return ""

    text_clean = re.sub(r'<[^>]+>', '', text)
    text_clean = re.sub(r'https?://\S+', '', text_clean)
    text_clean = text_clean[:5000]

    scores = {}
    for lang, patterns in LANG_PATTERNS.items():
        score = 0
        for p in patterns:
            matches = p.findall(text_clean)
            score += len(matches)
        if score > 0:
            scores[lang] = score

    if not scores:
        return ""

    best = max(scores, key=scores.get)
    if scores[best] < 3:
        return ""

    return best