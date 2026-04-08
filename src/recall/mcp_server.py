"""
mcp_server.py — MCP-сервер для Recall.

Инструменты кэша:
  ask(query)             — ищет ответ в кэше
  save(query, response)  — сохраняет ответ агента
  cache_stats()          — статистика кэша
  economy_stats()        — статистика экономии
  cache_list(tag)        — список записей (с фильтром по тегу)
  cache_cleanup()        — удалить просроченные
  cache_clear()          — очистить весь кэш
  config_get(key)        — получить настройку
  config_set(key, value) — изменить настройку
  tag_stats()            — статистика по тегам

Инструменты памяти:
  remember(fact)         — запомнить факт
  recall_memories(query) — найти релевантные факты
  list_memories(cat)     — список фактов
  update_memory(id)      — обновить факт
  forget_memory(id)      — удалить факт
  memory_stats()         — статистика памяти
"""

import json
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from mcp.server.fastmcp import FastMCP

from recall.cache import PromptCache, setup_logging
from recall.config import Config
from recall.economy import EconomyTracker
from recall.memory import Memory

# Загружаем конфиг
config = Config()

# Убедимся что папки существуют
cache_db = os.path.normpath(os.path.expanduser(config.get("cache_db", "cache.db")))
memory_db = os.path.normpath(os.path.expanduser(config.get("memory_db", "memory.db")))
Path(cache_db).parent.mkdir(parents=True, exist_ok=True)
Path(memory_db).parent.mkdir(parents=True, exist_ok=True)

log_file = config.get("log_file")
if log_file:
    log_file = os.path.normpath(os.path.expanduser(log_file))
    Path(log_file).parent.mkdir(parents=True, exist_ok=True)

# Настраиваем логирование
setup_logging(
    log_file=log_file,
    level=config.get("log_level", "INFO"),
    max_bytes=config.get("log_max_bytes", 10 * 1024 * 1024),
)

# Создаём MCP-сервер
mcp = FastMCP("recall")

# Инициализируем кэш (отдельная БД)
cache = PromptCache(
    db_path=cache_db,
    ttl=config.get("ttl"),
    threshold=config.get("threshold"),
    tags_enabled=config.get("tags_enabled", True),
    economy_enabled=config.get("economy_tracking", True),
)

# Трекер экономии (в cache.db)
economy = EconomyTracker(cache_db)

# Память ИИ (отдельная БД)
memory = Memory(db_path=memory_db) if config.get("memory_enabled", True) else None


# ─── Основные инструменты ─────────────────────────────────────────────────


@mcp.tool()
def ask(query: str) -> str:
    """
    Ищет ответ в кэше по запросу.

    Если найден — возвращает [CACHE HIT] + ответ.
    Если нет — возвращает [CACHE MISS]. Агент должен сам сгенерировать ответ
    и вызвать save().
    """
    result = cache.ask(query)
    if result is not None:
        return f"[CACHE HIT] {result}"
    return "[CACHE MISS]"


@mcp.tool()
def save(query: str, response: str, tags: str = "") -> str:
    """
    Сохраняет ответ агента в кэш.

    Args:
        query: Текст запроса.
        response: Ответ агента.
        tags: Теги через запятую (опционально), например: #python,#work
    """
    tag_list = [t.strip() for t in tags.split(",") if t.strip()] if tags else []
    if cache.save(query, response, tags=tag_list if tag_list else None):
        return f"[SAVED] Ответ сохранён для: {query[:60]}"
    return "[ERROR] Не удалось сохранить"


@mcp.tool()
def cache_stats() -> str:
    """Показать статистику кэша."""
    stats = cache.stats()
    return json.dumps(stats, ensure_ascii=False, indent=2)


@mcp.tool()
def cache_clear() -> str:
    """Очистить весь кэш."""
    cache.clear()
    economy.reset()
    return "Кэш очищен."


@mcp.tool()
def cache_list(tag: str = "") -> str:
    """Список закэшированных запросов. Можно фильтровать по тегу."""
    tag_filter = tag if tag else None
    entries = cache.list_entries(include_expired=False, tag=tag_filter)
    if not entries:
        return "Кэш пуст."
    return json.dumps(entries, ensure_ascii=False, indent=2)


@mcp.tool()
def cache_cleanup() -> str:
    """Удалить просроченные записи."""
    removed = cache.cleanup()
    return f"Удалено просроченных записей: {removed}"


# ─── Экономика ────────────────────────────────────────────────────────────


@mcp.tool()
def economy_stats() -> str:
    """Статистика экономии: HIT/MISS, hit_rate, сэкономленные токены."""
    stats = economy.get_stats()
    return json.dumps(stats, ensure_ascii=False, indent=2)


# ─── Конфиг ───────────────────────────────────────────────────────────────


@mcp.tool()
def config_get(key: str = "") -> str:
    """Получить настройку конфига. Без ключа — все настройки."""
    if key:
        value = config.get(key)
        return json.dumps({key: value}, ensure_ascii=False, indent=2)
    return json.dumps(config.list_all(), ensure_ascii=False, indent=2)


@mcp.tool()
def config_set(key: str, value: str) -> str:
    """Изменить настройку конфига. Значение — строка (числа/булевы парсятся)."""
    try:
        parsed = json.loads(value)
    except json.JSONDecodeError:
        parsed = value

    config.set(key, parsed)
    if config.save():
        return f"[OK] {key} = {parsed}"
    return f"[ERROR] Не удалось сохранить конфиг"


# ─── Теги ─────────────────────────────────────────────────────────────────


@mcp.tool()
def tag_stats() -> str:
    """Статистика по тегам: какие есть, сколько записей у каждого."""
    tags = cache.get_all_tags()
    if not tags:
        return "Теги не используются."
    return json.dumps(tags, ensure_ascii=False, indent=2)


# ─── Память ИИ ────────────────────────────────────────────────────────────


@mcp.tool()
def remember(
    fact: str,
    category: str = "context",
    importance: int = 5,
    verified: bool = False,
) -> str:
    """
    Запомнить факт о пользователе.

    Args:
        fact: Сжатый факт ("Пользователь владеет Python").
        category: skills, projects, environment, preferences, goals, context.
        importance: Важность 1-10.
        verified: Подтверждено ли пользователем.
    """
    if memory is None:
        return "[ERROR] Память отключена в конфиге."
    result = memory.remember(fact, category, importance, verified)
    if result is not None:
        return f"[SAVED] Факт #{result}: {fact[:60]}"
    return "[DUPLICATE] Факт уже существует"


@mcp.tool()
def recall_memories(query: str, limit: int = 5) -> str:
    """
    Найти релевантные факты по запросу.

    Args:
        query: Текст для семантического поиска.
        limit: Максимальное количество результатов.
    """
    if memory is None:
        return "[ERROR] Память отключена."
    results = memory.recall_memories(query, limit)
    if not results:
        return "Нет релевантных фактов."
    return json.dumps(results, ensure_ascii=False, indent=2)


@mcp.tool()
def list_memories(category: str = "") -> str:
    """Список всех фактов. Можно фильтровать по категории."""
    if memory is None:
        return "[ERROR] Память отключена."
    cat = category if category else None
    entries = memory.list_memories(category=cat)
    if not entries:
        return "Память пуста."
    return json.dumps(entries, ensure_ascii=False, indent=2)


@mcp.tool()
def update_memory(
    fact_id: int,
    fact: str = "",
    category: str = "",
    importance: int = 0,
    verified: bool = False,
) -> str:
    """Обновить существующий факт."""
    if memory is None:
        return "[ERROR] Память отключена."
    kwargs = {}
    if fact:
        kwargs["fact"] = fact
    if category:
        kwargs["category"] = category
    if importance > 0:
        kwargs["importance"] = importance
    kwargs["verified"] = verified
    if memory.update_memory(fact_id, **kwargs):
        return f"[OK] Факт #{fact_id} обновлён."
    return f"[ERROR] Факт #{fact_id} не найден."


@mcp.tool()
def forget_memory(fact_id: int) -> str:
    """Удалить факт из памяти."""
    if memory is None:
        return "[ERROR] Память отключена."
    if memory.forget_memory(fact_id):
        return f"[OK] Факт #{fact_id} удалён."
    return f"[ERROR] Факт #{fact_id} не найден."


@mcp.tool()
def memory_stats() -> str:
    """Статистика памяти: количество фактов по категориям."""
    if memory is None:
        return "[ERROR] Память отключена."
    stats = memory.memory_stats()
    return json.dumps(stats, ensure_ascii=False, indent=2)


# ─── Ресурс ───────────────────────────────────────────────────────────────


@mcp.resource("cache://stats")
def cache_stats_resource() -> str:
    """Read-only статистика кэша (JSON)."""
    return json.dumps(cache.stats(), ensure_ascii=False, indent=2)


# ─── Запуск ───────────────────────────────────────────────────────────────


def main():
    mcp.run(transport="stdio")


if __name__ == "__main__":
    main()
