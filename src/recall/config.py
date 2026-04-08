"""
config.py — Управление конфигурацией Recall.

Хранит настройки в JSON-файле (~/.recall/config.json).
Если файла нет — использует значения по умолчанию.
"""

import json
import logging
import os
from pathlib import Path
from typing import Any, Optional

# ─── Значения по умолчанию ─────────────────────────────────────────────────

DEFAULTS = {
    # Кэш
    "cache_db": "~/.recall/cache.db",
    "ttl": 86400,
    "threshold": 0.75,
    "embed_dim": 128,
    "ngram_range": [2, 4],
    "max_entries": None,
    "auto_cleanup": True,
    "auto_cleanup_interval": 3600,

    # Память ИИ
    "memory_db": "~/.recall/memory.db",
    "memory_enabled": True,
    "memory_similarity_threshold": 0.7,

    # Логирование
    "log_file": "~/.recall/recall.log",
    "log_level": "INFO",
    "log_max_bytes": 10 * 1024 * 1024,  # 10 MB

    # Экономика
    "economy_tracking": True,

    # Теги
    "tags_enabled": True,
}


class Config:
    """
    Менеджер конфигурации.

    Читает JSON-файл. Если ключа нет — возвращает дефолт.
    set() меняет в памяти. save() записывает на диск.
    """

    def __init__(self, path: Optional[str] = None):
        self.path = Path(path or os.path.join(
            os.path.expanduser("~"), ".recall", "config.json"
        ))
        self._data: dict[str, Any] = {}
        self._load()

    def _load(self) -> None:
        """Загружает конфиг из файла."""
        if self.path.exists():
            try:
                with open(self.path, "r", encoding="utf-8") as f:
                    self._data = json.load(f)
            except (json.JSONDecodeError, OSError) as e:
                # Файл повреждён — используем дефолты
                logging.getLogger("recall").warning(
                    f"Повреждённый конфиг {self.path}: {e}. Используются дефолты."
                )
                self._data = {}
        else:
            self._data = {}

    def get(self, key: str, default: Any = None) -> Any:
        """Получает значение. Ищет в: конфиг → дефолты → переданный default."""
        if key in self._data:
            return self._data[key]
        if key in DEFAULTS:
            return DEFAULTS[key]
        return default

    def set(self, key: str, value: Any) -> None:
        """Устанавливает значение в памяти."""
        self._data[key] = value

    def reset(self, key: Optional[str] = None) -> None:
        """Сбрасывает значение к дефолту."""
        if key:
            self._data.pop(key, None)
        else:
            self._data = {}

    def save(self) -> bool:
        """Сохраняет конфиг на диск. Создаёт папку если нужно."""
        try:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            with open(self.path, "w", encoding="utf-8") as f:
                json.dump(self._data, f, ensure_ascii=False, indent=2)
            return True
        except OSError as e:
            logging.getLogger("recall").error(f"Ошибка записи конфига: {e}")
            return False

    def list_all(self) -> dict[str, Any]:
        """Возвращает все настройки (конфиг + дефолты)."""
        result = dict(DEFAULTS)
        result.update(self._data)
        return result

    def __repr__(self) -> str:
        return f"Config(path='{self.path}')"
