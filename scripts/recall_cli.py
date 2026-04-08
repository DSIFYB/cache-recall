#!/usr/bin/env python3
"""
Recall — CLI-инструмент для кэширования и памяти ИИ.

Кэш:
  ask "запрос"              — найти ответ в кэше
  save "вопрос" "ответ"     — сохранить ответ
  stats                     — статистика кэша
  economy                   — статистика экономии
  list [--tag X]            — список записей
  tags                      — все теги
  cleanup                   — удалить просроченные
  clear                     — очистить кэш

Память:
  remember "факт"           — запомнить факт
  recall "запрос"           — найти релевантные факты
  mem-list [категория]      — список фактов
  mem-update ID факт        — обновить факт
  mem-forget ID             — удалить факт
  mem-stats                 — статистика памяти
  mem-clear                 — очистить память

Конфиг:
  config get|set|list|reset — управление настройками
"""

import argparse
import json
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from recall.cache import PromptCache, setup_logging
from recall.config import Config
from recall.economy import EconomyTracker
from recall.memory import Memory

# Загружаем конфиг
config = Config()

# Убедимся что папка для БД существует
cache_db = os.path.normpath(os.path.expanduser(config.get("cache_db", "cache.db")))
memory_db = os.path.normpath(os.path.expanduser(config.get("memory_db", "memory.db")))
Path(cache_db).parent.mkdir(parents=True, exist_ok=True)
Path(memory_db).parent.mkdir(parents=True, exist_ok=True)

# Настраиваем логирование
log_file = config.get("log_file")
if log_file:
    log_file = os.path.normpath(os.path.expanduser(log_file))
    Path(log_file).parent.mkdir(parents=True, exist_ok=True)
setup_logging(log_file=log_file, level=config.get("log_level"))

cache = PromptCache(
    db_path=cache_db,
    ttl=config.get("ttl"),
    threshold=config.get("threshold"),
    tags_enabled=config.get("tags_enabled", True),
    economy_enabled=config.get("economy_tracking", True),
)
economy = EconomyTracker(cache_db)
memory = Memory(db_path=memory_db) if config.get("memory_enabled", True) else None


# ─── Кэш ──────────────────────────────────────────────────────────────────


def cmd_ask(args):
    result = cache.ask(args.query)
    if result is not None:
        print(f"[CACHE HIT] {result}")
    else:
        print("[CACHE MISS] Ответ не найден. Используйте 'save'.")


def cmd_save(args):
    tags = [t.strip() for t in args.tags.split(",")] if args.tags else []
    ok = cache.save(args.query, args.response, tags=tags or None)
    print("[SAVED] Ответ сохранён." if ok else "[ERROR] Не удалось сохранить.")


def cmd_stats(args):
    s = cache.stats()
    if s["total_entries"] == 0:
        print("Кэш пуст.")
        return
    print(f"Всего записей:    {s['total_entries']}")
    print(f"  Активных:       {s['valid_entries']}")
    print(f"  Просроченных:   {s['expired_entries']}")
    print(f"Размер БД:        {s['total_size']}")
    print(f"TTL:              {s['ttl']} сек ({s['ttl'] // 3600} ч)")
    print(f"Порог схожести:   {s['threshold']}")
    print(f"Теги:             {s['tag_count']}")


def cmd_economy(args):
    s = economy.get_stats()
    print(f"Всего запросов:   {s['total_requests']}")
    print(f"  HIT:            {s['total_hits']} ({s['hit_rate']})")
    print(f"    Точных:       {s['total_exact_hits']}")
    print(f"    Семантических:{s['total_semantic_hits']}")
    print(f"  MISS:           {s['total_misses']}")
    print(f"Токенов сэкономлено: ~{s['estimated_tokens_saved']}")
    print()
    print(f"Сегодня: {s['today']['hits']} HIT, {s['today']['misses']} MISS ({s['today']['hit_rate']})")
    if s["top_queries"]:
        print("\nТоп запросов:")
        for i, q in enumerate(s["top_queries"][:5], 1):
            print(f"  {i}. {q['query']} — {q['hits']} HIT")


def cmd_config(args):
    action = args.config_action
    if action == "get":
        if args.key:
            print(json.dumps({args.key: config.get(args.key)}, indent=2))
        else:
            print(json.dumps(config.list_all(), indent=2))
    elif action == "set":
        if not args.key or not args.value:
            print("Использование: config set КЛЮЧ ЗНАЧЕНИЕ")
            return
        try:
            parsed = json.loads(args.value)
        except json.JSONDecodeError:
            parsed = args.value
        config.set(args.key, parsed)
        if config.save():
            print(f"[OK] {args.key} = {parsed}")
        else:
            print("[ERROR] Не удалось сохранить")
    elif action == "list":
        print(json.dumps(config.list_all(), indent=2))
    elif action == "reset":
        if args.key:
            config.reset(args.key)
        else:
            config.reset()
        config.save()
        print("[OK] Сброшено")


def cmd_clear(args):
    cache.clear()
    economy.reset()
    print("Кэш очищен.")


def cmd_list(args):
    entries = cache.list_entries(
        include_expired=args.all,
        tag=args.tag,
    )
    if not entries:
        print("Кэш пуст.")
        return
    label = f"тег: {args.tag}" if args.tag else ("всего" if args.all else "активных")
    print(f"Записей ({label}): {len(entries)}\n")
    for i, e in enumerate(entries, 1):
        status = "⏰" if e.get("expired") else "✓"
        tags = " ".join(e.get("tags", []))
        print(f"  {i}. [{status}] {e['query']}")
        if tags:
            print(f"     {tags}")
        print(f"     TTL: {e['ttl']}с | Доступов: {e['access_count']}")


def cmd_tags(args):
    tags = cache.get_all_tags()
    if not tags:
        print("Теги не используются.")
        return
    print(f"Тегов: {len(tags)}\n")
    for t in tags:
        print(f"  {t['tag']} — {t['count']} записей")


def cmd_cleanup(args):
    removed = cache.cleanup()
    print(f"Удалено просроченных: {removed}" if removed else "Просроченных нет.")


# ─── Память ───────────────────────────────────────────────────────────────


def cmd_remember(args):
    if memory is None:
        print("[ERROR] Память отключена.")
        return
    result = memory.remember(
        args.fact,
        category=args.category,
        importance=args.importance,
        verified=args.verified,
    )
    if result is not None:
        print(f"[SAVED] Факт #{result}: {args.fact}")
    else:
        print("[DUPLICATE] Факт уже существует.")


def cmd_recall(args):
    if memory is None:
        print("[ERROR] Память отключена.")
        return
    results = memory.recall_memories(args.query, limit=args.limit)
    if not results:
        print("Нет релевантных фактов.")
        return
    print(f"Найдено {len(results)} фактов:\n")
    for i, r in enumerate(results, 1):
        print(f"  {i}. [{r['similarity']:.2f}] [{r['category']}] {r['fact']}")
        print(f"     Важность: {r['importance']}/10 | Проверен: {'✓' if r['verified'] else '✗'}")


def cmd_mem_list(args):
    if memory is None:
        print("[ERROR] Память отключена.")
        return
    entries = memory.list_memories(
        category=args.category if args.category else None,
        min_importance=args.min_importance,
    )
    if not entries:
        print("Память пуста.")
        return
    print(f"Фактов: {len(entries)}\n")
    for i, e in enumerate(entries, 1):
        status = "✓" if e["verified"] else "○"
        print(f"  {i}. [{status}] [{e['category']}] [{e['importance']}/10] {e['fact']}")
        print(f"     ID: {e['id']} | Доступов: {e['access_count']}")


def cmd_mem_update(args):
    if memory is None:
        print("[ERROR] Память отключена.")
        return
    kwargs = {}
    if args.fact:
        kwargs["fact"] = args.fact
    if args.category:
        kwargs["category"] = args.category
    if args.importance > 0:
        kwargs["importance"] = args.importance
    kwargs["verified"] = args.verified
    if memory.update_memory(args.id, **kwargs):
        print(f"[OK] Факт #{args.id} обновлён.")
    else:
        print(f"[ERROR] Факт #{args.id} не найден.")


def cmd_mem_forget(args):
    if memory is None:
        print("[ERROR] Память отключена.")
        return
    if memory.forget_memory(args.id):
        print(f"[OK] Факт #{args.id} удалён.")
    else:
        print(f"[ERROR] Факт #{args.id} не найден.")


def cmd_mem_stats(args):
    if memory is None:
        print("[ERROR] Память отключена.")
        return
    s = memory.memory_stats()
    print(f"Всего фактов:     {s['total_memories']}")
    print(f"Подтверждённых:   {s['verified_count']}")
    print(f"Ср. важность:     {s['avg_importance']}/10")
    if s["by_category"]:
        print("\nПо категориям:")
        for cat, count in sorted(s["by_category"].items()):
            print(f"  {cat}: {count}")


def cmd_mem_clear(args):
    if memory is None:
        print("[ERROR] Память отключена.")
        return
    memory.clear()
    print("Память очищена.")


# ─── Главная ──────────────────────────────────────────────────────────────


def main():
    parser = argparse.ArgumentParser(description="Recall — кэш и память ИИ-агента v1")
    sub = parser.add_subparsers(dest="command", help="Команды")

    # Кэш
    p = sub.add_parser("ask", help="Найти ответ")
    p.add_argument("query")
    p.set_defaults(func=cmd_ask)

    p = sub.add_parser("save", help="Сохранить ответ")
    p.add_argument("query")
    p.add_argument("response")
    p.add_argument("--tags", help="Теги через запятую")
    p.set_defaults(func=cmd_save)

    sub.add_parser("stats", help="Статистика кэша").set_defaults(func=cmd_stats)
    sub.add_parser("economy", help="Статистика экономии").set_defaults(func=cmd_economy)

    p = sub.add_parser("list", help="Список записей")
    p.add_argument("--all", action="store_true")
    p.add_argument("--tag", help="Фильтр по тегу")
    p.set_defaults(func=cmd_list)

    sub.add_parser("tags", help="Все теги").set_defaults(func=cmd_tags)
    sub.add_parser("clear", help="Очистить кэш").set_defaults(func=cmd_clear)
    sub.add_parser("cleanup", help="Удалить просроченные").set_defaults(func=cmd_cleanup)

    p = sub.add_parser("config", help="Настройки")
    sp = p.add_subparsers(dest="config_action")
    sp.add_parser("list", help="Все настройки").set_defaults(func=cmd_config)
    g = sp.add_parser("get", help="Получить настройку")
    g.add_argument("key", nargs="?")
    g.set_defaults(func=cmd_config)
    s = sp.add_parser("set", help="Изменить настройку")
    s.add_argument("key")
    s.add_argument("value")
    s.set_defaults(func=cmd_config)
    r = sp.add_parser("reset", help="Сбросить")
    r.add_argument("key", nargs="?")
    r.set_defaults(func=cmd_config)

    # Память
    p = sub.add_parser("remember", help="Запомнить факт")
    p.add_argument("fact", help="Текст факта")
    p.add_argument("--category", default="context", help="Категория")
    p.add_argument("--importance", type=int, default=5, help="Важность 1-10")
    p.add_argument("--verified", action="store_true", help="Подтверждено")
    p.set_defaults(func=cmd_remember)

    p = sub.add_parser("recall", help="Найти релевантные факты")
    p.add_argument("query", help="Текст для поиска")
    p.add_argument("--limit", type=int, default=5, help="Максимум результатов")
    p.set_defaults(func=cmd_recall)

    p = sub.add_parser("mem-list", help="Список фактов")
    p.add_argument("category", nargs="?", help="Фильтр по категории")
    p.add_argument("--min-importance", type=int, default=0, help="Мин. важность")
    p.set_defaults(func=cmd_mem_list)

    p = sub.add_parser("mem-update", help="Обновить факт")
    p.add_argument("id", type=int, help="ID факта")
    p.add_argument("fact", nargs="?", default="", help="Новый текст")
    p.add_argument("--category", default="", help="Новая категория")
    p.add_argument("--importance", type=int, default=0, help="Новая важность")
    p.add_argument("--verified", action="store_true", help="Подтвердить")
    p.set_defaults(func=cmd_mem_update)

    p = sub.add_parser("mem-forget", help="Удалить факт")
    p.add_argument("id", type=int, help="ID факта")
    p.set_defaults(func=cmd_mem_forget)

    sub.add_parser("mem-stats", help="Статистика памяти").set_defaults(func=cmd_mem_stats)
    sub.add_parser("mem-clear", help="Очистить память").set_defaults(func=cmd_mem_clear)

    args = parser.parse_args()
    if not args.command:
        parser.print_help()
        sys.exit(1)
    args.func(args)


if __name__ == "__main__":
    main()
