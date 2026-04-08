# Recall

Семантический кэш и долговременная память для ИИ-агентов.

Recall помогает ИИ-ассистентам запоминать ответы и факты о пользователе — чтобы не отвечать на одно и то же дважды и давать персонализированные ответы.

## Возможности

| Функция | Описание |
|---|---|
| **Кэш ответов** | Семантический поиск — находит похожие вопросы, не только точные совпадения |
| **Память ИИ** | Долговременные факты о пользователе (навыки, проекты, предпочтения) |
| **TTL** | Автоустаревание кэшированных ответов |
| **Теги** | Группировка записей по категориям |
| **Экономика** | Статистика: сколько запросов сэкономлено |
| **MCP-сервер** | 17 инструментов для MCP-клиентов (Qwen, Claude Desktop) |
| **Локальный** | Все данные на твоём компьютере, ничего не уходит в облако |

## Установка

```bash
pip install recall-ai
```

## Быстрый старт

### 1. Первый запуск

При первом использовании Recall автоматически создаёт папку `~/.recall/`:

```
~/.recall/
├── cache.db      ← Кэш ответов (временный, можно удалять)
├── memory.db     ← Память ИИ (постоянная, не трогать)
├── recall.log    ← Логи
└── config.json   ← Настройки (создаётся при изменении)
```

Ничего настраивать не нужно — работает из коробки.

### 2. Использование через CLI

```bash
# Найти ответ в кэше
recall ask "Что такое Python?"

# Сохранить ответ с тегами
recall save "Что такое Go?" "Язык от Google" --tags go,programming

# Запомнить факт о пользователе
recall remember "Пользователь владеет Python" --category skills --importance 7

# Найти релевантные факты
recall recall "какие языки знает пользователь?"

# Статистика
recall stats
recall economy
recall mem-stats

# Список записей
recall list
recall mem-list skills

# Настройки
recall config list
recall config set ttl 3600
```

### 3. Подключение как MCP-сервер

Добавь в настройки MCP-клиента (например, `~/.qwen/settings.json`):

```json
{
  "mcpServers": {
    "recall": {
      "command": "python",
      "args": ["-m", "recall.mcp_server"]
    }
  }
}
```

После подключения ИИ-ассистент получит 17 инструментов:

| Инструмент | Что делает |
|---|---|
| `ask(query)` | Ищет ответ в кэше |
| `save(query, response, tags)` | Сохраняет ответ |
| `remember(fact, category)` | Запоминает факт |
| `recall_memories(query)` | Находит релевантные факты |
| `cache_stats()` | Статистика кэша |
| `economy_stats()` | HIT/MISS, экономия токенов |
| `memory_stats()` | Статистика памяти |
| `config_get/set()` | Управление настройками |
| `tag_stats()` | Статистика по тегам |
| `cache_list(tag)` | Список записей |
| `list_memories(category)` | Список фактов |
| `cache_cleanup()` | Удалить просроченные |
| `cache_clear()` | Очистить кэш |
| `update_memory(id)` | Обновить факт |
| `forget_memory(id)` | Удалить факт |

## Конфигурация

Настройки хранятся в `~/.recall/config.json`. При первом запуске — дефолтные значения.

```json
{
  "cache_db": "~/.recall/cache.db",
  "memory_db": "~/.recall/memory.db",
  "ttl": 86400,
  "threshold": 0.75,
  "log_file": "~/.recall/recall.log",
  "log_level": "INFO",
  "tags_enabled": true,
  "economy_tracking": true,
  "memory_enabled": true
}
```

| Настройка | По умолчанию | Описание |
|---|---|---|
| `ttl` | 86400 (24ч) | Время жизни кэшированных ответов |
| `threshold` | 0.75 | Порог семантического сходства |
| `tags_enabled` | true | Включить теги |
| `memory_enabled` | true | Включить память ИИ |

## Как использовать как библиотеку

```python
from recall.cache import PromptCache
from recall.memory import Memory

# Кэш
cache = PromptCache(ttl=3600)
answer = cache.ask("Что такое Python?")
if answer is None:
    answer = "Python — язык программирования..."
    cache.save("Что такое Python?", answer, tags=["#python"])

# Память
memory = Memory()
memory.remember("Пользователь владеет Python", category="skills", importance=7)
facts = memory.recall_memories("какие языки знает?")
```

## Структура проекта

```
recall/
├── src/
│   └── recall/
│       ├── __init__.py
│       ├── cache.py          # Ядро кэша: SQLite, эмбеддинги, теги
│       ├── memory.py         # Долговременная память ИИ
│       ├── config.py         # JSON-конфиг с дефолтами
│       ├── economy.py        # Трекер экономии (HIT/MISS)
│       └── mcp_server.py     # MCP-сервер (17 инструментов)
├── scripts/
│   └── recall_cli.py         # CLI-инструмент
├── tests/
│   └── test_cache.py         # 128 тестов
├── pyproject.toml
├── README.md
└── LICENSE
```

## Разработка

```bash
# Клонировать репозиторий
git clone https://github.com/YOUR_USERNAME/recall.git
cd recall

# Установить зависимости
pip install -r requirements.txt

# Запустить тесты
python tests/test_cache.py

# Собрать пакет
pip install build
python -m build

# Установить локально
pip install -e .
```

## Публикация на PyPI

```bash
# Установить инструменты
pip install build twine

# Собрать пакет
python -m build

# Опубликовать (нужен токен с pypi.org)
python -m twine upload dist/*
```

## Лицензия

MIT
