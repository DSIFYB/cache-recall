"""
economy.py — Статистика экономии кэша.

Отслеживает HIT/MISS по дням, считает сэкономленные токены,
находит самые популярные запросы.
"""

import json
import sqlite3
import time
from datetime import datetime, date
from typing import Optional

# Средняя оценка: 1 ответ ≈ 50 слов × 1.3 токена/слово
AVG_TOKENS_PER_HIT = 65


class EconomyTracker:
    """
    Трекер экономии.

    Хранит данные в отдельной таблице SQLite:
      - economy_daily: HIT/MISS по дням
      - top_queries: самые частые запросы
    """

    def __init__(self, db_path: str):
        self.db_path = db_path
        self._init_db()

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        return conn

    def _init_db(self) -> None:
        """Создаёт таблицы если их нет."""
        try:
            with self._connect() as conn:
                conn.execute("""
                    CREATE TABLE IF NOT EXISTS economy_daily (
                        id INTEGER PRIMARY KEY AUTOINCREMENT,
                        date TEXT NOT NULL UNIQUE,
                        exact_hits INTEGER DEFAULT 0,
                        semantic_hits INTEGER DEFAULT 0,
                        misses INTEGER DEFAULT 0
                    )
                """)
                conn.execute("""
                    CREATE TABLE IF NOT EXISTS top_queries (
                        id INTEGER PRIMARY KEY AUTOINCREMENT,
                        query TEXT NOT NULL UNIQUE,
                        hit_count INTEGER DEFAULT 0
                    )
                """)
                conn.execute("""
                    CREATE INDEX IF NOT EXISTS idx_economy_date ON economy_daily(date)
                """)
                conn.execute("""
                    CREATE INDEX IF NOT EXISTS idx_top_hits ON top_queries(hit_count DESC)
                """)
                conn.commit()
        except sqlite3.Error:
            pass  # Не критично — экономика продолжит работать

    def record_hit(self, query: str, is_semantic: bool = False) -> None:
        """Записывает HIT."""
        today = date.today().isoformat()
        try:
            with self._connect() as conn:
                # Дневная статистика
                existing = conn.execute(
                    "SELECT id FROM economy_daily WHERE date = ?", (today,)
                ).fetchone()
                if existing:
                    col = "semantic_hits" if is_semantic else "exact_hits"
                    conn.execute(
                        f"UPDATE economy_daily SET {col} = {col} + 1 WHERE date = ?",
                        (today,),
                    )
                else:
                    exact = 0 if is_semantic else 1
                    semantic = 1 if is_semantic else 0
                    conn.execute(
                        "INSERT INTO economy_daily (date, exact_hits, semantic_hits, misses) VALUES (?, ?, ?, 0)",
                        (today, exact, semantic),
                    )

                # Топ запросов
                conn.execute("""
                    INSERT INTO top_queries (query, hit_count) VALUES (?, 1)
                    ON CONFLICT(query) DO UPDATE SET hit_count = hit_count + 1
                """, (query,))
                conn.commit()
        except sqlite3.Error:
            pass

    def record_miss(self) -> None:
        """Записывает MISS."""
        today = date.today().isoformat()
        try:
            with self._connect() as conn:
                existing = conn.execute(
                    "SELECT id FROM economy_daily WHERE date = ?", (today,)
                ).fetchone()
                if existing:
                    conn.execute(
                        "UPDATE economy_daily SET misses = misses + 1 WHERE date = ?",
                        (today,),
                    )
                else:
                    conn.execute(
                        "INSERT INTO economy_daily (date, exact_hits, semantic_hits, misses) VALUES (?, 0, 0, 1)",
                        (today,),
                    )
                conn.commit()
        except sqlite3.Error:
            pass

    def get_stats(self) -> dict:
        """Возвращает полную статистику экономии."""
        try:
            with self._connect() as conn:
                # Общая статистика
                total = conn.execute(
                    "SELECT "
                    "  COALESCE(SUM(exact_hits), 0) as exact, "
                    "  COALESCE(SUM(semantic_hits), 0) as semantic, "
                    "  COALESCE(SUM(misses), 0) as misses "
                    "FROM economy_daily"
                ).fetchone()

                total_hits = total["exact"] + total["semantic"]
                total_all = total_hits + total["misses"]
                hit_rate = (total_hits / total_all * 100) if total_all > 0 else 0

                # Сегодня
                today = date.today().isoformat()
                today_row = conn.execute(
                    "SELECT * FROM economy_daily WHERE date = ?", (today,)
                ).fetchone()

                today_hits = (today_row["exact_hits"] + today_row["semantic_hits"]) if today_row else 0
                today_misses = today_row["misses"] if today_row else 0
                today_all = today_hits + today_misses
                today_rate = (today_hits / today_all * 100) if today_all > 0 else 0

                # Топ запросов
                top = conn.execute(
                    "SELECT query, hit_count FROM top_queries ORDER BY hit_count DESC LIMIT 10"
                ).fetchall()

                return {
                    "total_hits": total_hits,
                    "total_exact_hits": total["exact"],
                    "total_semantic_hits": total["semantic"],
                    "total_misses": total["misses"],
                    "total_requests": total_all,
                    "hit_rate": f"{hit_rate:.1f}%",
                    "today": {
                        "hits": today_hits,
                        "misses": today_misses,
                        "hit_rate": f"{today_rate:.1f}%",
                    },
                    "estimated_tokens_saved": total_hits * AVG_TOKENS_PER_HIT,
                    "top_queries": [
                        {"query": r["query"], "hits": r["hit_count"]}
                        for r in top
                    ],
                }
        except sqlite3.Error:
            return {
                "total_hits": 0,
                "total_exact_hits": 0,
                "total_semantic_hits": 0,
                "total_misses": 0,
                "total_requests": 0,
                "hit_rate": "0.0%",
                "today": {"hits": 0, "misses": 0, "hit_rate": "0.0%"},
                "estimated_tokens_saved": 0,
                "top_queries": [],
            }

    def reset(self) -> None:
        """Сбрасывает всю статистику."""
        try:
            with self._connect() as conn:
                conn.execute("DELETE FROM economy_daily")
                conn.execute("DELETE FROM top_queries")
                conn.commit()
        except sqlite3.Error:
            pass
