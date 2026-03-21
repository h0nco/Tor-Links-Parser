LANG = "en"
S = {
    "pick": "Language / Язык:\n  1  English\n  2  Русский",
    "en": {
        "title":"ghTor","conn":"Connecting to Tor...","port":"Port: {}","ok":"{}",
        "nf":"ERROR: Tor not found.","err":"ERROR: {}","thr":"Threads [{}]: ",
        "creating":"Creating {} sessions...","ready":"Ready. {} threads.","first":"Connect to Tor first.",
        "to":"Timeout [{}]: ","ret":"Retries [{}]: ","stop":"Stopped.","bye":"Bye.",
        "st":"Checked: {} | Found: {} | Online: {} | Offline: {} | DB: {} | Queue: {} | Mon: {}",
        "on_fmt":"[{}] ONLINE {}ms [{}] [{}] {}","off_fmt":"[{}] OFFLINE {} {}ms (x{})",
        "dup":" [DUP {}]","cr":"[{}] +{} crawled","crr":"--- crawl #{}: {} links ---",
        "circ":"[circuit] #{}","exp":"Exported {} -> {}","ign":"Ignored: {}",
        "m1":"Connect to Tor","m2":"Scan from file","m3":"Discover sites","m4":"Monitor on/off","m0":"Exit",
        "fi":"File: {} links, {} in DB, {} new","fe":"File empty: {}",
        "na":"[n]ew/[a]ll? ","no":"Nothing.","ca":"Crawl? (y/n) [y]: ",
        "ti":"Threads: {}, Timeout: {}s, Retries: {}","ck":"Checking {}...",
        "on":"on","off":"off","co":"connected","nc":"not connected",
        "mi":"Interval [{}]: ","ms":"Monitor started ({}s).","mt":"Monitor stopped.",
        "p1":"Phase 1: {} plugins scraping...","p2":"Phase 2: {} sites + crawling...",
        "coll":"Collected: {}, New: {}","resc":"Queue empty. Re-scraping...",
        "nn":"No new. Waiting {}s...","sh":"Ctrl+C to stop","pl":"Loaded {} plugins: {}",
    },
    "ru": {
        "title":"ghTor","conn":"Подключение к Tor...","port":"Порт: {}","ok":"{}",
        "nf":"ОШИБКА: Tor не найден.","err":"ОШИБКА: {}","thr":"Потоков [{}]: ",
        "creating":"Создаю {} сессий...","ready":"Готово. {} потоков.","first":"Сначала подключитесь.",
        "to":"Таймаут [{}]: ","ret":"Попыток [{}]: ","stop":"Остановлено.","bye":"Пока.",
        "st":"Проверено: {} | Найдено: {} | Онлайн: {} | Офлайн: {} | БД: {} | Очередь: {} | Мон: {}",
        "on_fmt":"[{}] ОНЛАЙН {}мс [{}] [{}] {}","off_fmt":"[{}] ОФЛАЙН {} {}мс (x{})",
        "dup":" [ДУБ {}]","cr":"[{}] +{} найдено","crr":"--- краулинг #{}: {} ---",
        "circ":"[circuit] #{}","exp":"Экспорт: {} -> {}","ign":"Игнор: {}",
        "m1":"Подключиться к Tor","m2":"Из файла","m3":"Поиск сайтов","m4":"Мониторинг","m0":"Выход",
        "fi":"Файл: {}, в базе: {}, новых: {}","fe":"Пуст: {}",
        "na":"[n]овые/[a]все? ","no":"Нечего.","ca":"Краулить? (y/n) [y]: ",
        "ti":"Потоки: {}, Таймаут: {}с, Попытки: {}","ck":"Проверяю {}...",
        "on":"вкл","off":"выкл","co":"подключён","nc":"нет",
        "mi":"Интервал [{}]: ","ms":"Мониторинг ({}с).","mt":"Мониторинг выкл.",
        "p1":"Фаза 1: {} плагинов...","p2":"Фаза 2: {} сайтов + краулинг...",
        "coll":"Собрано: {}, Новых: {}","resc":"Пусто. Перепарсинг...",
        "nn":"Нет новых. Жду {}с...","sh":"Ctrl+C стоп","pl":"Загружено {} плагинов: {}",
    },
}
def set_lang(c): global LANG; LANG = c
def t(k, *a):
    s = S.get(LANG, S["en"]).get(k, k)
    return s.format(*a) if a else s