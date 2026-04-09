# Cache-Recall

Semantic cache and long-term memory for AI agents.

Cache-Recall helps AI assistants remember answers and facts about the user — so they don't answer the same question twice and can provide personalized responses.

---

## English

### Features

| Feature | Description |
|---|---|
| **Answer Cache** | Semantic search + keyword fallback — finds similar even with low semantic score |
| **Auto-Caching** | auto_save option — answers are saved automatically |
| **AI Memory** | Long-term facts about the user (skills, projects, preferences) |
| **TTL** | Auto-expiration of cached answers |
| **Tags** | Organize entries by categories |
| **Economy** | Statistics: how many requests were saved |
| **MCP Server** | 19 tools for MCP clients (Qwen, Claude Desktop) |
| **Local** | All data stays on your computer, nothing leaves to the cloud |

### Installation

```bash
pip install cache-recall
```

### Quick Start

#### 1. First Run

On first use, Recall automatically creates `~/.recall/`:

```
~/.recall/
├── cache.db      ← Answer cache (temporary, safe to delete)
├── memory.db     ← AI memory (permanent, don't touch)
├── recall.log    ← Logs
└── config.json   ← Settings (created when changed)
```

No setup required — works out of the box.

#### 2. CLI Usage

```bash
# Find an answer in cache
recall ask "What is Python?"

# Save an answer with tags
recall save "What is Go?" "A language by Google" --tags go,programming

# Remember a fact about the user
recall remember "User knows Python" --category skills --importance 7

# Find relevant facts
recall recall "what languages does the user know?"

# Statistics
recall stats
recall economy
recall mem-stats

# List entries
recall list
recall mem-list skills

# Settings
recall config list
recall config set ttl 3600
```

#### 3. Connect as MCP Server

Add to your MCP client settings (e.g., `~/.qwen/settings.json`):

```json
{
  "mcpServers": {
    "cache-recall": {
      "command": "python",
      "args": ["-m", "recall.mcp_server"]
    }
  }
}
```

After connecting, the AI assistant gets 19 tools: `ask`, `answer_and_save`, `save`, `remember`, `recall_memories`, `cache_stats`, `economy_stats`, `memory_stats`, `config_get/set`, `tag_stats`, `cache_list`, `list_memories`, `cache_cleanup`, `cache_clear`, `update_memory`, `forget_memory`.

### Configuration

Settings stored in `~/.recall/config.json`. Defaults on first run:

```json
{
  "cache_db": "~/.recall/cache.db",
  "memory_db": "~/.recall/memory.db",
  "ttl": 86400,
  "threshold": 0.55,
  "embed_dim": 256,
  "auto_save": false,
  "keyword_fallback": true,
  "log_file": "~/.recall/recall.log",
  "log_level": "INFO",
  "tags_enabled": true,
  "economy_tracking": true,
  "memory_enabled": true
}
```

### As a Library

```python
from recall.cache import PromptCache
from recall.memory import Memory

cache = PromptCache(ttl=3600)
answer = cache.ask("What is Python?")
if answer is None:
    answer = "Python is a programming language..."
    cache.save("What is Python?", answer, tags=["#python"])

memory = Memory()
memory.remember("User knows Python", category="skills", importance=7)
facts = memory.recall_memories("what languages does the user know?")
```

### Development

```bash
git clone https://github.com/DSIFYB/cache-recall.git
cd cache-recall
pip install -r requirements.txt
python tests/test_cache.py
```

---

## Русский

### Возможности

| Функция | Описание |
|---|---|
| **Кэш ответов** | Семантический поиск + keyword fallback — находит даже при низком semantic score |
| **Авто-кэширование** | Опция auto_save — ответы сохраняются автоматически |
| **Память ИИ** | Долговременные факты о пользователе (навыки, проекты, предпочтения) |
| **TTL** | Автоустаревание кэшированных ответов |
| **Теги** | Группировка записей по категориям |
| **Экономика** | Статистика: сколько запросов сэкономлено |
| **MCP-сервер** | 19 инструментов для MCP-клиентов (Qwen, Claude Desktop) |
| **Локальный** | Все данные на твоём компьютере, ничего не уходит в облако |

### Установка

```bash
pip install cache-recall
```

### Быстрый старт

#### 1. Первый запуск

При первом использовании Recall автоматически создаёт `~/.recall/`:

```
~/.recall/
├── cache.db      ← Кэш ответов (временный, можно удалять)
├── memory.db     ← Память ИИ (постоянная, не трогать)
├── recall.log    ← Логи
└── config.json   ← Настройки (создаётся при изменении)
```

Ничего настраивать не нужно — работает из коробки.

#### 2. Использование через CLI

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

#### 3. Подключение как MCP-сервер

Добавь в настройки MCP-клиента (`~/.qwen/settings.json`):

```json
{
  "mcpServers": {
    "cache-recall": {
      "command": "python",
      "args": ["-m", "recall.mcp_server"]
    }
  }
}
```

После подключения ИИ-ассистент получит 19 инструментов: `ask`, `answer_and_save`, `save`, `remember`, `recall_memories`, `cache_stats`, `economy_stats`, `memory_stats`, `config_get/set`, `tag_stats`, `cache_list`, `list_memories`, `cache_cleanup`, `cache_clear`, `update_memory`, `forget_memory`.

### Конфигурация

Настройки хранятся в `~/.recall/config.json`. При первом запуске — дефолтные значения:

```json
{
  "cache_db": "~/.recall/cache.db",
  "memory_db": "~/.recall/memory.db",
  "ttl": 86400,
  "threshold": 0.55,
  "embed_dim": 256,
  "auto_save": false,
  "keyword_fallback": true,
  "log_file": "~/.recall/recall.log",
  "log_level": "INFO",
  "tags_enabled": true,
  "economy_tracking": true,
  "memory_enabled": true
}
```

### Как использовать как библиотеку

```python
from recall.cache import PromptCache
from recall.memory import Memory

cache = PromptCache(ttl=3600)
answer = cache.ask("Что такое Python?")
if answer is None:
    answer = "Python — язык программирования..."
    cache.save("Что такое Python?", answer, tags=["#python"])

memory = Memory()
memory.remember("Пользователь владеет Python", category="skills", importance=7)
facts = memory.recall_memories("какие языки знает?")
```

### Разработка

```bash
git clone https://github.com/DSIFYB/cache-recall.git
cd cache-recall
pip install -r requirements.txt
python tests/test_cache.py
```

---

## License

MIT

---

## Publishing to PyPI

```bash
# 1. Install build tools
pip install build twine

# 2. Build package
python -m build

# 3. Upload to PyPI
twine upload dist/*

# Or test on TestPyPI first
twine upload --repository testpypi dist/*
```
