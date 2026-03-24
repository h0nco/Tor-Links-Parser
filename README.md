<div align="center">


## Возможности

- **Async движок** — aiohttp + aiohttp-socks, semaphore-конкурентность, 10-50 параллельных проверок
- **8 встроенных плагинов-источников** — Ahmia, TorLinks, Donion, Dark.fail, OnionTree, Tor.Taxi, Hidden Wiki, OnionLinks
- **Система плагинов** — кинь `.py` файл в `plugins/` и он подхватится автоматически
- **Pipeline обработки** — fetch -> parse -> filter -> categorize -> detect language -> deduplicate -> store
- **Краулинг** — извлекает `.onion` ссылки с каждой найденной страницы, добавляет в очередь
- **Rate limiter** — token bucket алгоритм, настраиваемый req/s
- **Детектор дубликатов** — MD5 хеш контента, помечает зеркала одного сайта
- **Определение языка** — 8 языков (en, ru, de, fr, es, zh, ar, ja)
- **Автокатегоризация** — 11 категорий по ключевым словам в заголовке
- **Фильтр заголовков** — пропускает мусорные страницы (404, дефолтные, запаркованные)
- **HTTP заголовки** — Server, X-Powered-By, Content-Type сохраняются для каждого сайта
- **Мониторинг** — периодическая перепроверка онлайн-сайтов, алерты при изменении статуса
- **Telegram бот** — уведомления о находках + удалённое управление (/status, /stop, /stats)
- **Graceful shutdown** — обработка SIGINT/SIGTERM, авто-экспорт при выходе
- **Авто-экспорт** — JSON дамп всей базы при каждом завершении
- **Логирование** — ежедневная ротация лог-файлов + вывод в консоль
- **i18n** — интерфейс на английском и русском
- **SQLite** — WAL режим, потокобезопасность, авто-миграция схемы

## Быстрый старт

```bash
# 1. Клонировать
git clone https://github.com/h0nco/Tor-Links-Parser/
cd Tor-Links-Parser

# 2. Установить зависимости
pip install -r requirements.txt

# 3. Запустить Tor Browser или Tor Expert Bundle
#    Дождаться полного подключения

# 4. Запустить
python main.py
```

При первом запуске выбери язык (1 = English, 2 = Русский), затем:

```
  1  Подключиться к Tor     <- сначала подключение
  3  Поиск сайтов           <- запустить поиск
```
## Архитектура

```
                    ┌─────────────┐
                    │   Плагины   │  встроенных + кастомные
                    │ (источники) │
                    └──────┬──────┘
                           │ .onion URL-ы
                           ▼
┌──────────┐     ┌──────────────────┐      ┌───────────┐
│  links   │────>│   Async движок    │────>│  Telegram │
│  .txt    │     │ (aiohttp + socks) │     │    бот    │
└──────────┘     │   rate limiter   │      └───────────┘
                 │   semaphore      │
                 └────────┬─────────┘
                          │ HTML + заголовки
                          ▼
              ┌───────────────────────┐
              │      Pipeline         │
              │                       │
              │  parse --> filter     │
              │  categorize --> lang  │
              │  deduplicate --> store│
              └───────────┬───────────┘
                          │
                ┌─────────┴─────────┐
                │                   │
                ▼                   ▼
          ┌──────────┐      ┌────────────┐
          │  SQLite   │     │  Очередь   │
          │   база    │     │ краулинга  │
          └──────────┘      └────────────┘
```


Создай файл в папке `plugins/`:

```python
from core.plugins import SourcePlugin

class MySource(SourcePlugin):
    name = "my_source"
    description = "ресурс onion v3 ссылок"

    async def scrape(self, session):
        text = await self._fetch(session, "http://example.onion/links")
        return self.extract_onions(text)
```

Кинь в `plugins/` — подхватится автоматически при следующем подключении.

**Доступные методы в SourcePlugin:**
- `self._fetch(session, url)` — async запрос с таймаутом 60с, возвращает текст или ""
- `self._fetch_pages(session, urls)` — запросить несколько URL, объединить текст
- `self.extract_onions(text)` — regex-извлечение всех .onion адресов из текста
- `self._log(msg)` — лог с именем плагина

## Telegram бот

### Настройка

Отредактируй `config.json`:

```json
{
  "telegram": {
    "token": "123456:ABC-DEF...",
    "chat_id": "987654321"
  }
}
```

### Уведомления

Каждый найденный сайт отправляется JSON-сообщением:

```json
{
  "type": "site_found",
  "url": "http://xxxxx.onion",
  "title": "Example Site",
  "category": "forum",
  "language": "en",
  "ping_ms": 2340,
  "server": "nginx",
  "checked_at": "2026-03-24 12:00:00 UTC"
}
```

Каждые 10 сайтов — батч-репорт со сводкой.

### Удалённое управление

| Команда | Действие |
|---------|----------|
| `/status` | Статус сканера, БД, версия |
| `/stats` | Детальная статистика |
| `/stop` | Остановить текущее сканирование |
| `/help` | Список команд |


| Параметр | По умолчанию | Описание |
|----------|-------------|----------|
| `tor.threads` | 20 | Параллельные сессии через Tor |
| `tor.timeout` | 20 | Таймаут запроса (секунды) |
| `tor.retries` | 2 | Количество попыток на сайт |
| `rate_limit.requests_per_second` | 10 | Макс. запросов в секунду |
| `discovery.rescan_interval` | 120 | Ожидание перед повторным сканированием источников (сек) |
| `monitor.interval` | 300 | Интервал перепроверки мониторинга (сек) |

## Фильтр заголовков

Редактируй `ignore_titles.txt` для пропуска мусорных сайтов:

```
404 not found
403 forbidden
default web page
coming soon
parked domain
```




- Python 3.10+
- Tor Browser или Tor Expert Bundle (запущенный)
- Зависимости: `aiohttp`, `aiohttp-socks`, `beautifulsoup4`, `requests`, `PySocks`
