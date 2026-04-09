"""
test_cache.py — 100 тестов для Recall v1 (конфиг, экономика, теги, логи).
Запуск: python tests/test_cache.py
"""

import os, sys, json, shutil, time, math, tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent / "src"))
from recall.cache import PromptCache, TextEmbedder, is_expired, setup_logging, DEFAULT_TTL
from recall.config import Config, DEFAULTS
from recall.economy import EconomyTracker
from recall.memory import Memory, VALID_CATEGORIES

passed = failed = total = 0
errors = []
_temp_dirs = []
_temp_files = []

def tmp_db():
    d = tempfile.mkdtemp(prefix="ptest_")
    _temp_dirs.append(d)
    return os.path.join(d, "cache.db")

def tmp_file(name="tmp"):
    d = tempfile.mkdtemp(prefix=f"ptest_{name}_")
    _temp_files.append(d)
    return os.path.join(d, f"{name}.json")

def run_test(name, fn):
    global passed, failed, total
    total += 1
    try:
        fn()
        passed += 1
        print(f"  [{total:03d}] PASS  {name}")
    except AssertionError as e:
        failed += 1; errors.append((total, name, str(e)))
        print(f"  [{total:03d}] FAIL  {name}: {e}")
    except Exception as e:
        failed += 1; errors.append((total, name, f"ERR: {e}"))
        print(f"  [{total:03d}] ERR   {name}: {e}")

def T(name):
    def decorator(fn):
        fn._test_name = name
        return fn
    return decorator


# ===================== 1-15: Конфиг =====================

@T("Конфиг создаётся без файла")
def t01():
    c = Config(tmp_file("cfg"))
    assert c.get("ttl") == DEFAULTS["ttl"]

@T("Конфиг читает дефолты")
def t02():
    c = Config(tmp_file("cfg"))
    assert c.get("threshold") == DEFAULTS["threshold"]

@T("Конфиг сохраняет настройки")
def t03():
    path = tmp_file("cfg")
    c = Config(path)
    c.set("ttl", 3600)
    c.save()
    c2 = Config(path)
    assert c2.get("ttl") == 3600

@T("Конфиг создаёт папку")
def t04():
    path = os.path.join(tempfile.mkdtemp(), "new", "config.json")
    _temp_files.append(os.path.dirname(path))
    c = Config(path)
    c.set("ttl", 7200)
    assert c.save()

@T("Повреждённый конфиг → дефолты")
def t05():
    path = tmp_file("cfg")
    with open(path, "w") as f: f.write("{bad json}")
    c = Config(path)
    assert c.get("ttl") == DEFAULTS["ttl"]

@T("set/reset в памяти")
def t06():
    c = Config(tmp_file("cfg"))
    c.set("ttl", 100)
    assert c.get("ttl") == 100
    c.reset("ttl")
    assert c.get("ttl") == DEFAULTS["ttl"]

@T("list_all возвращает все")
def t07():
    c = Config(tmp_file("cfg"))
    c.set("ttl", 3600)
    a = c.list_all()
    assert a["ttl"] == 3600
    assert "threshold" in a

@T("get с кастомным default")
def t08():
    c = Config(tmp_file("cfg"))
    assert c.get("nonexistent", "fallback") == "fallback"

@T("reset всех настроек")
def t09():
    c = Config(tmp_file("cfg"))
    c.set("ttl", 100); c.set("threshold", 0.5)
    c.reset()
    assert c.get("ttl") == DEFAULTS["ttl"]
    assert c.get("threshold") == DEFAULTS["threshold"]

@T("JSON формат конфига")
def t10():
    path = tmp_file("cfg")
    c = Config(path)
    c.set("ttl", 3600); c.save()
    with open(path) as f:
        d = json.load(f)
    assert d["ttl"] == 3600


# ===================== 11-25: Экономика =====================

@T("EconomyTracker создаётся")
def t11():
    db = tmp_db()
    PromptCache(db)
    et = EconomyTracker(db)
    assert et is not None

@T("record_hit увеличивает счётчик")
def t12():
    db = tmp_db()
    PromptCache(db)
    et = EconomyTracker(db)
    et.record_hit("test query")
    s = et.get_stats()
    assert s["total_hits"] == 1

@T("record_miss увеличивает счётчик")
def t13():
    db = tmp_db()
    PromptCache(db)
    et = EconomyTracker(db)
    et.record_miss()
    s = et.get_stats()
    assert s["total_misses"] == 1

@T("hit_rate == 100% при одних HIT")
def t14():
    db = tmp_db()
    PromptCache(db)
    et = EconomyTracker(db)
    for _ in range(5): et.record_hit("q")
    assert et.get_stats()["hit_rate"] == "100.0%"

@T("hit_rate == 50% при равных HIT/MISS")
def t15():
    db = tmp_db()
    PromptCache(db)
    et = EconomyTracker(db)
    et.record_hit("q"); et.record_miss()
    assert et.get_stats()["hit_rate"] == "50.0%"

@T("today статистика")
def t16():
    db = tmp_db()
    PromptCache(db)
    et = EconomyTracker(db)
    et.record_hit("q")
    s = et.get_stats()
    assert s["today"]["hits"] == 1

@T("top_queries обновляется")
def t17():
    db = tmp_db()
    PromptCache(db)
    et = EconomyTracker(db)
    for _ in range(10): et.record_hit("popular")
    et.record_hit("rare")
    top = et.get_stats()["top_queries"]
    assert top[0]["query"] == "popular"

@T("estimated_tokens_saved > 0")
def t18():
    db = tmp_db()
    PromptCache(db)
    et = EconomyTracker(db)
    for _ in range(5): et.record_hit("q")
    assert et.get_stats()["estimated_tokens_saved"] > 0

@T("reset сбрасывает экономику")
def t19():
    db = tmp_db()
    PromptCache(db)
    et = EconomyTracker(db)
    et.record_hit("q"); et.record_miss()
    et.reset()
    s = et.get_stats()
    assert s["total_hits"] == 0 and s["total_misses"] == 0

@T("total_requests == hits + misses")
def t20():
    db = tmp_db()
    PromptCache(db)
    et = EconomyTracker(db)
    for _ in range(3): et.record_hit("q")
    for _ in range(2): et.record_miss()
    s = et.get_stats()
    assert s["total_requests"] == 5


# ===================== 21-40: Теги =====================

@T("save с тегами")
def t21():
    c = PromptCache(tmp_db(), tags_enabled=True)
    c.save("q", "a", tags=["#python"])
    assert c.ask("q") == "a"

@T("get_all_tags возвращает теги")
def t22():
    c = PromptCache(tmp_db(), tags_enabled=True)
    c.save("q1", "a", tags=["#python"])
    c.save("q2", "a", tags=["#rust"])
    tags = c.get_all_tags()
    assert len(tags) == 2

@T("tag count считается верно")
def t23():
    c = PromptCache(tmp_db(), tags_enabled=True)
    c.save("q1", "a", tags=["#py"])
    c.save("q2", "a", tags=["#py"])
    c.save("q3", "a", tags=["#rs"])
    tags = c.get_all_tags()
    py = [t for t in tags if "py" in t["tag"]][0]
    assert py["count"] == 2

@T("list_by_tag фильтрует")
def t24():
    c = PromptCache(tmp_db(), tags_enabled=True)
    c.save("q1", "a1", tags=["#py"])
    c.save("q2", "a2", tags=["#rs"])
    entries = c.list_by_tag("#py")
    assert len(entries) == 1
    assert entries[0]["query"] == "q1"

@T("Теги без # добавляются автоматически")
def t25():
    c = PromptCache(tmp_db(), tags_enabled=True)
    c.save("q", "a", tags=["python"])
    tags = c.get_all_tags()
    assert tags[0]["tag"] == "#python"

@T("Пустые теги сохраняют без тегов")
def t26():
    c = PromptCache(tmp_db(), tags_enabled=True)
    c.save("q", "a")
    assert c.get_all_tags() == []

@T("Одинаковый тег не дублируется")
def t27():
    c = PromptCache(tmp_db(), tags_enabled=True)
    c.save("q1", "a", tags=["#py"])
    c.save("q2", "a", tags=["#py"])
    tags = c.get_all_tags()
    assert len(tags) == 1

@T("Теги при overwrite обновляются")
def t28():
    c = PromptCache(tmp_db(), tags_enabled=True)
    c.save("q", "a1", tags=["#py"])
    c.save("q", "a2", tags=["#rs"])
    entries = c.list_by_tag("#rs")
    assert len(entries) == 1
    assert c.list_by_tag("#py") == []

@T("Тег отключён — get_all_tags пуст")
def t29():
    c = PromptCache(tmp_db(), tags_enabled=False)
    c.save("q", "a", tags=["#py"])
    assert c.get_all_tags() == []

@T("list_entries с тегом фильтрует")
def t30():
    c = PromptCache(tmp_db(), tags_enabled=True)
    c.save("q1", "a1", tags=["#py"])
    c.save("q2", "a2", tags=["#rs"])
    entries = c.list_entries(tag="#py")
    assert len(entries) == 1

@T("Список тегов в entry")
def t31():
    c = PromptCache(tmp_db(), tags_enabled=True)
    c.save("q", "a", tags=["#py", "#work"])
    entries = c.list_entries()
    tags_in_entry = entries[0].get("tags", [])
    assert len(tags_in_entry) == 2

@T("Несколько тегов на запись")
def t32():
    c = PromptCache(tmp_db(), tags_enabled=True)
    c.save("q", "a", tags=["#py", "#work", "#learning"])
    tags = c.get_all_tags()
    assert len(tags) == 3


# ===================== 31-50: Базовые операции =====================

@T("Создаётся SQLite файл")
def t33():
    c = PromptCache(tmp_db())
    assert os.path.exists(c.db_path)

@T("default_ttl == 86400")
def t34():
    assert PromptCache(tmp_db()).ttl == DEFAULT_TTL

@T("Пустой кэш: total_entries == 0")
def t35():
    assert PromptCache(tmp_db()).stats()["total_entries"] == 0

@T("ask несуществующего == None")
def t36():
    assert PromptCache(tmp_db()).ask("nope") is None

@T("save + ask: один запрос")
def t37():
    c = PromptCache(tmp_db()); c.save("hello", "world")
    assert c.ask("hello") == "world"

@T("save + ask: два запроса")
def t38():
    c = PromptCache(tmp_db())
    c.save("q1", "a1"); c.save("q2", "a2")
    assert c.ask("q1") == "a1" and c.ask("q2") == "a2"

@T("Пустой запрос → None")
def t39():
    assert PromptCache(tmp_db()).ask("") is None

@T("save с пустым → False")
def t40():
    c = PromptCache(tmp_db())
    assert c.save("", "ans") is False
    assert c.save("q", "") is False

@T("Кириллица")
def t41():
    c = PromptCache(tmp_db()); c.save("Привет", "ответ")
    assert c.ask("Привет") == "ответ"

@T("Эмодзи")
def t42():
    c = PromptCache(tmp_db()); c.save("🚀", "ok")
    assert c.ask("🚀") == "ok"

@T("Длинный запрос (10К)")
def t43():
    c = PromptCache(tmp_db()); q = "x" * 10000
    c.save(q, "ok"); assert c.ask(q) == "ok"

@T("Длинный ответ (50К)")
def t44():
    c = PromptCache(tmp_db()); c.save("q", "a" * 50000)
    assert len(c.ask("q")) == 50000


# ===================== 41-55: TTL =====================

@T("Запись не истекла сразу")
def t45():
    c = PromptCache(tmp_db()); c.save("q", "a")
    assert c.ask("q") == "a"

@T("Запись истекает через TTL")
def t46():
    c = PromptCache(tmp_db(), ttl=1)
    c.save("q", "a")
    time.sleep(1.1)
    assert c.ask("q") is None

@T("cleanup() удаляет просроченные")
def t47():
    c = PromptCache(tmp_db(), ttl=1)
    c.save("q1", "a"); c.save("q2", "a")
    time.sleep(1.1)
    assert c.cleanup() == 2

@T("cleanup() == 0 если нет просроченных")
def t48():
    c = PromptCache(tmp_db(), ttl=3600)
    c.save("q", "a")
    assert c.cleanup() == 0

@T("expired_entries >= 1 после истечения")
def t49():
    c = PromptCache(tmp_db(), ttl=1)
    c.save("q", "a")
    time.sleep(1.1)
    assert c.stats()["expired_entries"] >= 1


# ===================== 51-65: Эмбеддинги и семантика =====================

@T("Embedder создаётся")
def t50():
    e = TextEmbedder(); assert e.dim == 256

@T("Вектор правильной размерности")
def t51():
    e = TextEmbedder(dim=64); assert len(e.embed("hello")) == 64

@T("Одинаковые тексты → 1.0")
def t52():
    e = TextEmbedder()
    assert abs(e.cosine_similarity("abc", "abc") - 1.0) < 0.001

@T("Разные тексты → низкая")
def t53():
    e = TextEmbedder()
    assert e.cosine_similarity("abcdef", "123456") < 0.5

@T("Похожие тексты → высокая")
def t54():
    e = TextEmbedder()
    s = e.cosine_similarity("как работает дефрагментация диска", "как работает дефрагментация")
    assert s > 0.5

@T("Точный регистр не важен")
def t55():
    c = PromptCache(tmp_db()); c.save("Python", "ответ")
    assert c.ask("python") == "ответ"

@T("Семантический HIT")
def t56():
    c = PromptCache(tmp_db(), threshold=0.7)
    c.save("как работает дефрагментация диска?", "ответ")
    assert c.ask("как работает дефрагментация") == "ответ"

@T("Семантический MISS")
def t57():
    c = PromptCache(tmp_db(), threshold=0.75)
    c.save("погода?", "солнечно")
    assert c.ask("сколько стоит bitcoin?") is None

@T("Вектор нормализован")
def t58():
    e = TextEmbedder(); v = e.embed("test text")
    assert abs(math.sqrt(sum(x*x for x in v)) - 1.0) < 0.001


# ===================== 56-70: Обработка ошибок =====================

@T("ask при недоступной БД → None")
def t59():
    assert PromptCache("/nonexistent/db.db").ask("q") is None

@T("save при недоступной БД → False")
def t60():
    assert PromptCache("/nonexistent/db.db").save("q", "a") is False

@T("stats не падает")
def t61():
    c = PromptCache(tmp_db()); c.save("q", "a")
    assert "total_entries" in c.stats()

@T("clear на пустой БД")
def t62():
    PromptCache(tmp_db()).clear()

@T("Несколько инстансов — одна БД")
def t63():
    db = tmp_db()
    c1 = PromptCache(db); c2 = PromptCache(db)
    c1.save("q", "a"); assert c2.ask("q") == "a"

@T("1000 записей — без ошибок")
def t64():
    c = PromptCache(tmp_db())
    for i in range(1000): c.save(f"q{i}", f"a{i}")
    assert c.stats()["total_entries"] == 1000

@T("close() не падает")
def t65():
    PromptCache(tmp_db()).close()


# ===================== 66-80: Интеграция =====================

@T("Полный цикл: MISS → save → HIT")
def t66():
    c = PromptCache(tmp_db())
    q = "Что такое Rust?"
    assert c.ask(q) is None
    c.save(q, "Rust — язык программирования")
    assert c.ask(q) == "Rust — язык программирования"

@T("Повторный запрос — hit")
def t67():
    c = PromptCache(tmp_db()); c.save("q", "ответ")
    assert c.ask("q") is not None

@T("Разные запросы → разные записи")
def t68():
    c = PromptCache(tmp_db()); c.save("a", "1"); c.save("b", "2")
    assert c.stats()["total_entries"] == 2

@T("Одинаковый запрос → одна запись")
def t69():
    c = PromptCache(tmp_db()); c.save("x", "1"); c.save("x", "2")
    assert c.stats()["total_entries"] == 1

@T("Unicode не конфликтует")
def t70():
    c = PromptCache(tmp_db())
    c.save("café", "fr"); c.save("кофе", "ru")
    assert c.ask("café") == "fr" and c.ask("кофе") == "ru"

@T("100 одинаковых → 1 запись")
def t71():
    c = PromptCache(tmp_db())
    for _ in range(100): c.save("same", "ans")
    assert c.stats()["total_entries"] == 1

@T("Агент: несколько вопросов подряд")
def t72():
    c = PromptCache(tmp_db())
    qa = [("Python?", "Язык"), ("Rust?", "Системный"), ("Go?", "От Google")]
    for q, a in qa:
        if c.ask(q) is None: c.save(q, a)
    assert c.ask("Python?") == "Язык"

@T("Семантика экономит сохранение")
def t73():
    c = PromptCache(tmp_db(), threshold=0.7)
    c.save("Как работает дефрагментация диска?", "ответ")
    assert c.ask("как работает дефрагментация") == "ответ"


# ===================== 71-80: Статистика =====================

@T("list_entries длина == 1")
def t74():
    c = PromptCache(tmp_db()); c.save("q", "a")
    assert len(c.list_entries()) == 1

@T("total_size — строка")
def t75():
    c = PromptCache(tmp_db()); c.save("q", "a")
    assert isinstance(c.stats()["total_size"], str)

@T("threshold в stats")
def t76():
    assert PromptCache(tmp_db()).stats()["threshold"] == 0.55

@T("access_count при создании = 1")
def t77():
    c = PromptCache(tmp_db()); c.save("q", "a")
    assert c.list_entries()[0]["access_count"] == 1

@T("access_count растёт при ask")
def t78():
    c = PromptCache(tmp_db()); c.save("q", "a")
    c.ask("q"); c.ask("q")
    assert c.list_entries()[0]["access_count"] == 3


# ===================== 81-90: Логирование =====================

@T("setup_logging не падает")
def t79():
    log_path = os.path.join(tempfile.mkdtemp(), "test.log")
    _temp_files.append(os.path.dirname(log_path))
    setup_logging(log_file=log_path, level="DEBUG")

@T("Лог создаётся")
def t80():
    import logging
    # Очищаем handlers чтобы setup_logging сработал
    root = logging.getLogger("recall")
    root.handlers = []
    log_dir = tempfile.mkdtemp()
    _temp_files.append(log_dir)
    log_path = os.path.join(log_dir, "app.log")
    setup_logging(log_file=log_path, level="INFO")
    root.info("Test log message")
    time.sleep(0.1)
    assert os.path.exists(log_path)


# ===================== 91-110: Краевые случаи =====================

@T("clear пустого")
def t81():
    PromptCache(tmp_db()).clear()

@T("stats пустого")
def t82():
    assert PromptCache(tmp_db()).stats()["total_entries"] == 0

@T("Тройной clear")
def t83():
    c = PromptCache(tmp_db()); c.save("q", "a")
    c.clear(); c.clear(); c.clear()
    assert c.stats()["total_entries"] == 0

@T("is_expired: свежая запись")
def t84():
    assert not is_expired(time.time(), ttl=3600)

@T("list_entries пустого — []")
def t85():
    assert PromptCache(tmp_db()).list_entries() == []

@T("Повреждение embedding не ломает ask")
def t86():
    import sqlite3
    db = tmp_db(); c = PromptCache(db); c.save("q", "a")
    conn = sqlite3.connect(db)
    conn.execute("UPDATE entries SET embedding = '!!!'")
    conn.commit(); conn.close()
    c.ask("q")  # не упасть

@T("Повторное сохранение — одна запись")
def t87():
    c = PromptCache(tmp_db())
    c.save("q", "v1"); c.save("q", "v2")
    assert c.ask("q") == "v2"
    assert c.stats()["total_entries"] == 1

@T("default db_path параметр = recall.db")
def t89():
    # Проверяем что по умолчанию в сигнатуре стоит recall.db
    import inspect
    sig = inspect.signature(PromptCache.__init__)
    assert sig.parameters["db_path"].default == "recall.db"


# ===================== 90-100: MCP-сервер =====================

@T("mcp_server импортируется")
def t90():
    try: from recall import mcp_server; ok = True
    except Exception: ok = False
    assert ok

@T("mcp_server имеет ask")
def t90():
    from recall import mcp_server
    assert hasattr(mcp_server, "ask")

@T("mcp_server имеет save")
def t91():
    from recall import mcp_server
    assert hasattr(mcp_server, "save")

@T("mcp_server имеет economy_stats")
def t92():
    from recall import mcp_server
    assert hasattr(mcp_server, "economy_stats")

@T("mcp_server имеет config_get")
def t93():
    from recall import mcp_server
    assert hasattr(mcp_server, "config_get")

@T("mcp_server имеет config_set")
def t94():
    from recall import mcp_server
    assert hasattr(mcp_server, "config_set")

@T("mcp_server имеет tag_stats")
def t95():
    from recall import mcp_server
    assert hasattr(mcp_server, "tag_stats")

@T("mcp_server имеет cache_stats")
def t96():
    from recall import mcp_server
    assert hasattr(mcp_server, "cache_stats")

@T("mcp_server имеет cache_cleanup")
def t98():
    from recall import mcp_server
    assert hasattr(mcp_server, "cache_cleanup")

# ===================== 99-100: Интеграция всех фич =====================

@T("Конфиг + кэш: кастомный TTL")
def t99():
    db = tmp_db()
    c = PromptCache(db, ttl=3600)
    c.save("q", "a")
    assert c.stats()["ttl"] == 3600

@T("Теги + экономика: save с тегами → HIT")
def t100():
    db = tmp_db()
    c = PromptCache(db, tags_enabled=True, economy_enabled=True)
    c.save("q", "a", tags=["#test"])
    assert c.ask("q") == "a"
    tags = c.get_all_tags()
    assert len(tags) == 1

@T("Полный цикл: ask miss → save → ask hit + экономика")
def t99():
    db = tmp_db()
    c = PromptCache(db, tags_enabled=True, economy_enabled=True)
    assert c.ask("новый вопрос") is None
    c.save("новый вопрос", "ответ", tags=["#new"])
    assert c.ask("новый вопрос") == "ответ"
    tags = c.get_all_tags()
    assert tags[0]["tag"] == "#new"
    assert tags[0]["count"] == 1


# ===================== 101-130: Память ИИ =====================

@T("Memory создаётся")
def t101():
    db = tmp_db()
    PromptCache(db)
    m = Memory(db)
    assert m is not None

@T("remember сохраняет факт")
def t102():
    db = tmp_db()
    PromptCache(db)
    m = Memory(db)
    fid = m.remember("Пользователь владеет Python", "skills", 7)
    assert fid is not None

@T("recall_memories находит факт")
def t103():
    db = tmp_db()
    PromptCache(db)
    m = Memory(db)
    m.remember("Пользователь владеет Python", "skills", 7)
    results = m.recall_memories("программирование на Python")
    assert len(results) >= 1

@T("Пустой факт → None")
def t104():
    db = tmp_db()
    PromptCache(db)
    m = Memory(db)
    assert m.remember("") is None
    assert m.remember("   ") is None

@T("Неизвестная категория → context")
def t105():
    db = tmp_db()
    PromptCache(db)
    m = Memory(db)
    fid = m.remember("факт", "неизвестная")
    entries = m.list_memories()
    assert entries[0]["category"] == "context"

@T("Важность ограничена 1-10")
def t106():
    db = tmp_db()
    PromptCache(db)
    m = Memory(db)
    fid = m.remember("факт", importance=99)
    entries = m.list_memories()
    assert entries[0]["importance"] == 10

@T("Дубликаты не сохраняются")
def t107():
    db = tmp_db()
    PromptCache(db)
    m = Memory(db)
    m.remember("Python разработчик", "skills", 7)
    fid2 = m.remember("Python разработчик", "skills", 7)
    assert fid2 is None

@T("list_memories фильтрует по категории")
def t108():
    db = tmp_db()
    PromptCache(db)
    m = Memory(db)
    m.remember("Python", "skills", 7)
    m.remember("Windows", "environment", 5)
    skills = m.list_memories(category="skills")
    assert len(skills) == 1
    assert skills[0]["fact"] == "Python"

@T("update_memory обновляет факт")
def t109():
    db = tmp_db()
    PromptCache(db)
    m = Memory(db)
    fid = m.remember("Python junior", "skills", 3)
    m.update_memory(fid, fact="Python middle", importance=6)
    entries = m.list_memories()
    assert entries[0]["fact"] == "Python middle"
    assert entries[0]["importance"] == 6

@T("forget_memory удаляет факт")
def t110():
    db = tmp_db()
    PromptCache(db)
    m = Memory(db)
    fid = m.remember("удали меня", "context", 1)
    assert m.forget_memory(fid) is True
    assert m.list_memories() == []

@T("forget_memory несуществующего → False")
def t111():
    db = tmp_db()
    PromptCache(db)
    m = Memory(db)
    assert m.forget_memory(9999) is False

@T("memory_stats возвращает данные")
def t112():
    db = tmp_db()
    PromptCache(db)
    m = Memory(db)
    m.remember("Python", "skills", 7)
    m.remember("Rust", "skills", 5)
    m.remember("Windows", "environment", 3)
    s = m.memory_stats()
    assert s["total_memories"] == 3
    assert s["by_category"]["skills"] == 2
    assert s["by_category"]["environment"] == 1

@T("recall_memories сортирует по similarity")
def t113():
    db = tmp_db()
    PromptCache(db)
    m = Memory(db)
    m.remember("Python разработчик", "skills", 7)
    m.remember("Люблю кофе", "preferences", 2)
    results = m.recall_memories("программирование", min_similarity=0.0)
    assert results[0]["fact"] == "Python разработчик"

@T("recall_memories limit работает")
def t114():
    db = tmp_db()
    PromptCache(db)
    m = Memory(db)
    for i in range(10):
        m.remember(f"факт {i}", "context", 5)
    results = m.recall_memories("факт", limit=3)
    assert len(results) <= 3

@T("recall_memories пустой запрос → []")
def t115():
    db = tmp_db()
    PromptCache(db)
    m = Memory(db)
    assert m.recall_memories("") == []

@T("update_memory несуществующего → False")
def t116():
    db = tmp_db()
    PromptCache(db)
    m = Memory(db)
    assert m.update_memory(9999, fact="new") is False

@T("clear очищает память")
def t117():
    db = tmp_db()
    PromptCache(db)
    m = Memory(db)
    m.remember("факт 1", "skills")
    m.remember("факт 2", "projects")
    m.clear()
    assert m.list_memories() == []

@T("verified флаг сохраняется")
def t118():
    db = tmp_db()
    PromptCache(db)
    m = Memory(db)
    m.remember("факт", "skills", verified=True)
    entries = m.list_memories()
    assert entries[0]["verified"] is True

@T("access_count растёт при recall")
def t119():
    db = tmp_db()
    PromptCache(db)
    m = Memory(db)
    m.remember("Python", "skills", 7)
    m.recall_memories("Python")
    m.recall_memories("Python")
    entries = m.list_memories()
    assert entries[0]["access_count"] == 2

@T("source_query сохраняется")
def t120():
    db = tmp_db()
    PromptCache(db)
    m = Memory(db)
    m.remember("Python", "skills", source_query="Я пишу на Python")
    results = m.recall_memories("Python")
    assert results[0].get("source_query") == "Я пишу на Python"

@T("Семантический поиск находит похожие")
def t121():
    db = tmp_db()
    PromptCache(db)
    m = Memory(db)
    m.remember("Пользователь работает на Windows 11", "environment", 7)
    results = m.recall_memories("какая операционная система", min_similarity=0.0)
    assert len(results) >= 1

@T("Категории валидны")
def t122():
    assert "skills" in VALID_CATEGORIES
    assert "projects" in VALID_CATEGORIES
    assert "environment" in VALID_CATEGORIES
    assert "preferences" in VALID_CATEGORIES
    assert "goals" in VALID_CATEGORIES
    assert "context" in VALID_CATEGORIES

@T("memory_stats для пустой памяти")
def t123():
    db = tmp_db()
    PromptCache(db)
    m = Memory(db)
    s = m.memory_stats()
    assert s["total_memories"] == 0
    assert s["by_category"] == {}

@T("list_memories с min_importance")
def t124():
    db = tmp_db()
    PromptCache(db)
    m = Memory(db)
    m.remember("важный", "skills", 9)
    m.remember("неважный", "context", 2)
    entries = m.list_memories(min_importance=5)
    assert len(entries) == 1
    assert entries[0]["fact"] == "важный"

@T("avg_importance считается верно")
def t125():
    db = tmp_db()
    PromptCache(db)
    m = Memory(db)
    m.remember("a", "context", 3)
    m.remember("b", "context", 7)
    s = m.memory_stats()
    assert abs(s["avg_importance"] - 5.0) < 0.1

@T("Факты разных категорий не пересекаются")
def t126():
    db = tmp_db()
    PromptCache(db)
    m = Memory(db)
    m.remember("Python", "skills")
    m.remember("VS Code", "environment")
    skills = m.list_memories(category="skills")
    env = m.list_memories(category="environment")
    assert len(skills) == 1 and len(env) == 1

@T("Обновление verified флага")
def t127():
    db = tmp_db()
    PromptCache(db)
    m = Memory(db)
    fid = m.remember("факт", "context", verified=False)
    m.update_memory(fid, verified=True)
    entries = m.list_memories()
    assert entries[0]["verified"] is True

@T("recall_memories с фильтром категории")
def t128():
    db = tmp_db()
    PromptCache(db)
    m = Memory(db)
    m.remember("Python", "skills", 7)
    m.remember("Windows", "environment", 5)
    results = m.recall_memories("технология", category="skills")
    assert all(r["category"] == "skills" for r in results)

@T("Несколько фактов — recall находит все релевантные")
def t129():
    db = tmp_db()
    PromptCache(db)
    m = Memory(db)
    m.remember("Python разработчик", "skills", 8)
    m.remember("Go разработчик", "skills", 6)
    m.remember("Люблю гулять", "preferences", 3)
    results = m.recall_memories("разработка языки", limit=5)
    dev_results = [r for r in results if "разработчик" in r["fact"]]
    assert len(dev_results) >= 2

@T("Полный цикл: remember → recall → update → forget")
def t130():
    db = tmp_db()
    PromptCache(db)
    m = Memory(db)
    fid = m.remember("Junior Python", "skills", 3, source_query="я новичок")
    assert fid is not None
    results = m.recall_memories("Python")
    assert len(results) == 1
    m.update_memory(fid, fact="Middle Python", importance=6, verified=True)
    entries = m.list_memories()
    assert entries[0]["fact"] == "Middle Python"
    assert m.forget_memory(fid) is True
    assert m.list_memories() == []


# ===================== 131-145: Auto-save =====================

@T("ask_and_save: MISS сохраняет ответ")
def t131():
    c = PromptCache(tmp_db(), auto_save=True)
    was_cached, answer = c.ask_and_save("новый вопрос", "мой ответ")
    assert was_cached is False
    assert answer == "мой ответ"
    assert c.ask("новый вопрос") == "мой ответ"

@T("ask_and_save: HIT возвращает кэш")
def t132():
    c = PromptCache(tmp_db(), auto_save=True)
    c.save("вопрос", "кэшированный ответ")
    was_cached, answer = c.ask_and_save("вопрос", "новый ответ")
    assert was_cached is True
    assert answer == "кэшированный ответ"

@T("ask_and_save: auto_save=False не сохраняет")
def t133():
    c = PromptCache(tmp_db(), auto_save=False)
    c.ask_and_save("вопрос", "ответ")
    assert c.ask("вопрос") is None

@T("auto_save параметр в конструкторе")
def t134():
    c = PromptCache(tmp_db(), auto_save=True)
    assert c.auto_save is True
    c2 = PromptCache(tmp_db(), auto_save=False)
    assert c2.auto_save is False

@T("Конфиг: auto_save по умолчанию False")
def t135():
    from recall.config import Config, DEFAULTS
    assert "auto_save" in DEFAULTS
    assert DEFAULTS["auto_save"] is False


# ===================== ЗАПУСК =====================

if __name__ == "__main__":
    print("=" * 60)
    print("  Recall v1 — 135 тестов (конфиг+экономика+теги+auto-save)")
    print("=" * 60)
    tests = [(v._test_name, v) for k, v in sorted(globals().items())
             if k.startswith("t") and callable(v) and hasattr(v, "_test_name")]
    for name, fn in tests:
        run_test(name, fn)
    print()
    print("=" * 60)
    print(f"  ИТОГО: {total} | PASS: {passed} | FAIL: {failed}")
    print("=" * 60)
    if errors:
        print("\nFAILED:")
        for n, name, err in errors:
            print(f"  [{n:03d}] {name}: {err}")
    for d in _temp_dirs + _temp_files:
        try: shutil.rmtree(d, ignore_errors=True)
        except: pass
    sys.exit(0 if failed == 0 else 1)
