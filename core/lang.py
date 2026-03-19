LANG = "en"

S = {
    "pick_lang": "Language / Язык:\n  1  English\n  2  Русский",
    "en": {
        "title": "ghTor", "connecting": "Connecting to Tor...", "port_found": "Port: {}",
        "tor_ok": "{}", "tor_not_found": "ERROR: Tor not found.", "tor_error": "ERROR: {}",
        "threads_ask": "Threads [{}]: ", "creating": "Creating {} sessions...", "ready": "Ready. {} threads.",
        "connect_first": "Connect to Tor first.", "timeout_ask": "Timeout (sec) [{}]: ",
        "retries_ask": "Retries [{}]: ", "stopped": "Stopped.", "bye": "Bye.",
        "stats_fmt": "Checked: {} | Found: {} | Online: {} | Offline: {} | DB: {} | Queue: {} | Mon: {}",
        "online_fmt": "[{}] ONLINE {}ms [{}] [{}] {}", "offline_fmt": "[{}] OFFLINE {} {}ms (x{})",
        "dup_fmt": " [DUP {}]", "crawled": "[{}] +{} crawled",
        "crawl_round": "--- crawl #{}: {} links ---", "circuit": "[circuit] Rotated #{}",
        "exported": "Exported {} sites to {}", "ignored": "Ignored: {}",
        "menu_1": "Connect to Tor", "menu_2": "Scan from file",
        "menu_3": "Discover .onion sites", "menu_4": "Monitor on/off", "menu_0": "Exit",
        "file_info": "File: {} links, {} in DB, {} new", "file_empty": "File empty: {}",
        "check_new_all": "[n]ew or [a]ll? (n/a): ", "nothing": "Nothing to check.",
        "crawl_ask": "Crawl links? (y/n) [y]: ", "threads_info": "Threads: {}, Timeout: {}s, Retries: {}",
        "checking": "Checking {} URLs...", "on": "on", "off": "off",
        "connected": "connected", "not_connected": "not connected",
        "monitor_ask": "Interval (sec) [{}]: ", "mon_started": "Monitor started ({}s).", "mon_stopped": "Monitor stopped.",
        "phase1": "Phase 1: Scraping {} sources...", "phase2": "Phase 2: Checking {} sites + crawling...",
        "collected": "Collected: {}, New: {}", "rescraping": "Queue empty. Re-scraping...",
        "no_new": "No new addresses. Waiting {}s...", "stop_hint": "Ctrl+C to stop",
    },
    "ru": {
        "title": "ghTor", "connecting": "Подключение к Tor...", "port_found": "Порт: {}",
        "tor_ok": "{}", "tor_not_found": "ОШИБКА: Tor не найден.", "tor_error": "ОШИБКА: {}",
        "threads_ask": "Потоков [{}]: ", "creating": "Создаю {} сессий...", "ready": "Готово. {} потоков.",
        "connect_first": "Сначала подключитесь к Tor.", "timeout_ask": "Таймаут (сек) [{}]: ",
        "retries_ask": "Попыток [{}]: ", "stopped": "Остановлено.", "bye": "Пока.",
        "stats_fmt": "Проверено: {} | Найдено: {} | Онлайн: {} | Офлайн: {} | БД: {} | Очередь: {} | Мон: {}",
        "online_fmt": "[{}] ОНЛАЙН {}мс [{}] [{}] {}", "offline_fmt": "[{}] ОФЛАЙН {} {}мс (x{})",
        "dup_fmt": " [ДУБ {}]", "crawled": "[{}] +{} найдено",
        "crawl_round": "--- краулинг #{}: {} ссылок ---", "circuit": "[circuit] Ротация #{}",
        "exported": "Экспорт: {} сайтов в {}", "ignored": "Игнорирован: {}",
        "menu_1": "Подключиться к Tor", "menu_2": "Сканировать из файла",
        "menu_3": "Поиск .onion сайтов", "menu_4": "Мониторинг вкл/выкл", "menu_0": "Выход",
        "file_info": "Файл: {} ссылок, {} в базе, {} новых", "file_empty": "Файл пуст: {}",
        "check_new_all": "[n]овые или [a]все? (n/a): ", "nothing": "Нечего проверять.",
        "crawl_ask": "Краулить ссылки? (y/n) [y]: ", "threads_info": "Потоки: {}, Таймаут: {}с, Попытки: {}",
        "checking": "Проверяю {} URL...", "on": "вкл", "off": "выкл",
        "connected": "подключён", "not_connected": "не подключён",
        "monitor_ask": "Интервал (сек) [{}]: ", "mon_started": "Мониторинг запущен ({}с).", "mon_stopped": "Мониторинг остановлен.",
        "phase1": "Фаза 1: Парсинг {} источников...", "phase2": "Фаза 2: Проверка {} сайтов + краулинг...",
        "collected": "Собрано: {}, Новых: {}", "rescraping": "Очередь пуста. Перепарсинг...",
        "no_new": "Нет новых. Ожидание {}с...", "stop_hint": "Ctrl+C для остановки",
    },
}

def set_lang(code):
    global LANG
    LANG = code

def t(key, *a):
    s = S.get(LANG, S["en"]).get(key, key)
    return s.format(*a) if a else s