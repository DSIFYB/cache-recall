"""
Recall — Семантический кэш ответов для ИИ-агента.

Возможности:
  • Агент-first — агент генерирует, кэш хранит
  • Эмбеддинги — n-gram hashing, cosine similarity
  • SQLite — быстрый поиск при любом объёме
  • TTL — автоустаревание записей
  • Теги — группировка по категориям
  • Статистика экономии — видно сколько сэкономлено
  • Память ИИ — долговременные факты о пользователе
"""

__version__ = "1.0.0"
__author__ = "Recall contributors"

from recall.cache import PromptCache
from recall.config import Config, DEFAULTS
from recall.economy import EconomyTracker
from recall.memory import Memory

__all__ = [
    "PromptCache",
    "Config",
    "EconomyTracker",
    "Memory",
    "DEFAULTS",
]
