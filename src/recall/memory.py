"""
memory.py — Система долговременной памяти ИИ-агента.

Хранит сжатые факты о пользователе (навыки, проекты, предпочтения).
Не кэш ответов — а контекстная память для персонализации.

Правила отбора:
  ✅ Сохранять: подтверждённые навыки, проекты, среда, предпочтения, цели
  ❌ НЕ сохранять: временные действия, намерения без действия, банальности
"""

import json
import logging
import os
import sqlite3
import time
from typing import Optional

from recall.cache import TextEmbedder

logger = logging.getLogger("recall.memory")

# Допустимые категории
VALID_CATEGORIES = {
    "skills",       # Технические навыки
    "projects",     # Текущие/прошлые проекты
    "environment",  # ОС, инструменты, версии
    "preferences",  # Стиль, язык, формат ответов
    "goals",        # Подтверждённые цели
    "context",      # Работа, роль, опыт
}

# Минимальная важность для сохранения
MIN_IMPORTANCE = 1
MAX_IMPORTANCE = 10


class Memory:
    """
    Система долговременной памяти.

    Хранит факты в SQLite с эмбеддингами для семантического поиска.
    Каждый факт имеет категорию, важность и статус верификации.
    """

    def __init__(self, db_path: str = "recall.db"):
        self.db_path = db_path
        self.embedder = TextEmbedder()
        self._init_db()

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.db_path)
        conn.execute("PRAGMA journal_mode=WAL")
        conn.row_factory = sqlite3.Row
        return conn

    def _init_db(self) -> None:
        """Создаёт таблицу memories если её нет."""
        try:
            with self._connect() as conn:
                conn.execute("""
                    CREATE TABLE IF NOT EXISTS memories (
                        id INTEGER PRIMARY KEY AUTOINCREMENT,
                        fact TEXT NOT NULL,
                        category TEXT NOT NULL DEFAULT 'context',
                        embedding TEXT NOT NULL,
                        importance INTEGER NOT NULL DEFAULT 5,
                        verified INTEGER NOT NULL DEFAULT 0,
                        created_at REAL NOT NULL,
                        last_access REAL NOT NULL,
                        access_count INTEGER NOT NULL DEFAULT 0,
                        source_query TEXT
                    )
                """)
                conn.execute("""
                    CREATE INDEX IF NOT EXISTS idx_memory_category
                    ON memories(category)
                """)
                conn.execute("""
                    CREATE INDEX IF NOT EXISTS idx_memory_importance
                    ON memories(importance DESC)
                """)
                conn.execute("""
                    CREATE INDEX IF NOT EXISTS idx_memory_verified
                    ON memories(verified)
                """)
                conn.commit()
            logger.info(f"Память инициализирована: {self.db_path}")
        except sqlite3.Error as e:
            logger.error(f"Ошибка инициализации памяти: {e}")

    # ─── Основные методы ──────────────────────────────────────────────

    def remember(
        self,
        fact: str,
        category: str = "context",
        importance: int = 5,
        verified: bool = False,
        source_query: Optional[str] = None,
    ) -> Optional[int]:
        """
        Сохраняет факт в память.

        Args:
            fact: Текст факта (сжатый, конкретный).
            category: Категория факта.
            importance: Важность 1-10.
            verified: Подтверждено ли пользователем.
            source_query: Исходный запрос (для контекста).

        Returns:
            ID сохранённого факта или None при ошибке/дубликате.
        """
        if not fact or not fact.strip():
            return None

        # Валидация категории
        if category not in VALID_CATEGORIES:
            logger.warning(f"Неизвестная категория: {category}. Используем 'context'.")
            category = "context"

        # Валидация важности
        importance = max(MIN_IMPORTANCE, min(MAX_IMPORTANCE, importance))

        # Проверка на дубликаты (точный + семантический)
        existing = self._find_duplicate(fact)
        if existing is not None:
            logger.info(f"Дубликат факта (id={existing}): '{fact[:50]}'")
            return None

        now = time.time()
        embedding = self.embedder.embed(fact)

        try:
            with self._connect() as conn:
                cursor = conn.execute(
                    """
                    INSERT INTO memories (fact, category, embedding, importance, verified,
                                         created_at, last_access, access_count, source_query)
                    VALUES (?, ?, ?, ?, ?, ?, ?, 0, ?)
                    """,
                    (
                        fact.strip(),
                        category,
                        json.dumps(embedding),
                        importance,
                        1 if verified else 0,
                        now,
                        now,
                        source_query,
                    ),
                )
                conn.commit()
                fact_id = cursor.lastrowid
                logger.info(
                    f"Запомнил: '{fact[:50]}' [{category}] importance={importance}"
                )
                return fact_id
        except sqlite3.Error as e:
            logger.error(f"Ошибка сохранения в память: {e}")
            return None

    def recall_memories(
        self, query: str, limit: int = 5, category: Optional[str] = None
    ) -> list[dict]:
        """
        Находит релевантные факты по запросу.

        Args:
            query: Текст запроса для семантического поиска.
            limit: Максимальное количество результатов.
            category: Фильтр по категории (опционально).

        Returns:
            Список фактов, отсортированный по релевантности.
        """
        if not query:
            return []

        query_vec = self.embedder.embed(query)

        try:
            with self._connect() as conn:
                # Строим запрос с опциональным фильтром
                cat_filter = ""
                params: list = []
                if category:
                    cat_filter = "WHERE category = ?"
                    params.append(category)

                rows = conn.execute(
                    f"SELECT * FROM memories {cat_filter} ORDER BY importance DESC, last_access DESC",
                    params,
                ).fetchall()

                results = []
                for row in rows:
                    entry_vec = json.loads(row["embedding"])
                    score = self.embedder.similarity_from_embedding(
                        query_vec, entry_vec
                    )

                    # Обновляем счётчик доступа
                    conn.execute(
                        """
                        UPDATE memories
                        SET access_count = access_count + 1, last_access = ?
                        WHERE id = ?
                        """,
                        (time.time(), row["id"]),
                    )

                    results.append({
                        "id": row["id"],
                        "fact": row["fact"],
                        "category": row["category"],
                        "importance": row["importance"],
                        "verified": bool(row["verified"]),
                        "similarity": round(score, 3),
                        "source_query": row["source_query"],
                    })

                conn.commit()

                # Сортируем по similarity (убывание)
                results.sort(key=lambda x: x["similarity"], reverse=True)
                return results[:limit]

        except sqlite3.Error as e:
            logger.error(f"Ошибка поиска в памяти: {e}")
            return []

    def update_memory(
        self,
        fact_id: int,
        fact: Optional[str] = None,
        category: Optional[str] = None,
        importance: Optional[int] = None,
        verified: Optional[bool] = None,
    ) -> bool:
        """
        Обновляет существующий факт.

        Returns:
            True при успехе.
        """
        try:
            with self._connect() as conn:
                existing = conn.execute(
                    "SELECT * FROM memories WHERE id = ?", (fact_id,)
                ).fetchone()
                if not existing:
                    return False

                new_fact = fact if fact is not None else existing["fact"]
                new_cat = category if category is not None else existing["category"]
                new_imp = importance if importance is not None else existing["importance"]
                new_ver = (
                    1 if verified is not None else existing["verified"]
                )

                # Валидация
                if new_cat not in VALID_CATEGORIES:
                    new_cat = existing["category"]
                new_imp = max(MIN_IMPORTANCE, min(MAX_IMPORTANCE, new_imp))

                # Обновляем эмбеддинг если факт изменился
                if fact is not None and fact != existing["fact"]:
                    embedding = json.dumps(self.embedder.embed(new_fact))
                else:
                    embedding = existing["embedding"]
                    # Убедимся что это строка
                    if not isinstance(embedding, str):
                        embedding = json.dumps(embedding)

                conn.execute(
                    """
                    UPDATE memories
                    SET fact = ?, category = ?, embedding = ?,
                        importance = ?, verified = ?
                    WHERE id = ?
                    """,
                    (new_fact, new_cat, embedding, new_imp, new_ver, fact_id),
                )
                conn.commit()
                logger.info(f"Обновил память id={fact_id}")
                return True
        except sqlite3.Error as e:
            logger.error(f"Ошибка обновления памяти: {e}")
            return False

    def forget_memory(self, fact_id: int) -> bool:
        """
        Удаляет факт из памяти.

        Returns:
            True если удалён.
        """
        try:
            with self._connect() as conn:
                cursor = conn.execute(
                    "DELETE FROM memories WHERE id = ?", (fact_id,)
                )
                conn.commit()
                if cursor.rowcount > 0:
                    logger.info(f"Забыл факт id={fact_id}")
                    return True
                return False
        except sqlite3.Error as e:
            logger.error(f"Ошибка удаления из памяти: {e}")
            return False

    def list_memories(
        self, category: Optional[str] = None, min_importance: int = 0
    ) -> list[dict]:
        """
        Список фактов с фильтрацией.

        Args:
            category: Фильтр по категории.
            min_importance: Минимальная важность.
        """
        try:
            with self._connect() as conn:
                conditions = []
                params: list = []

                if category:
                    conditions.append("category = ?")
                    params.append(category)
                if min_importance > 0:
                    conditions.append("importance >= ?")
                    params.append(min_importance)

                where = ""
                if conditions:
                    where = "WHERE " + " AND ".join(conditions)

                rows = conn.execute(
                    f"SELECT * FROM memories {where} ORDER BY importance DESC, created_at DESC",
                    params,
                ).fetchall()

                return [
                    {
                        "id": r["id"],
                        "fact": r["fact"],
                        "category": r["category"],
                        "importance": r["importance"],
                        "verified": bool(r["verified"]),
                        "created_at": r["created_at"],
                        "access_count": r["access_count"],
                    }
                    for r in rows
                ]
        except sqlite3.Error as e:
            logger.error(f"Ошибка получения записей: {e}")
            return []

    def memory_stats(self) -> dict:
        """Статистика памяти."""
        try:
            with self._connect() as conn:
                total = conn.execute(
                    "SELECT COUNT(*) as cnt FROM memories"
                ).fetchone()["cnt"]

                by_category = {}
                for cat in VALID_CATEGORIES:
                    count = conn.execute(
                        "SELECT COUNT(*) as cnt FROM memories WHERE category = ?",
                        (cat,),
                    ).fetchone()["cnt"]
                    if count > 0:
                        by_category[cat] = count

                verified = conn.execute(
                    "SELECT COUNT(*) as cnt FROM memories WHERE verified = 1"
                ).fetchone()["cnt"]

                avg_importance = conn.execute(
                    "SELECT AVG(importance) as avg FROM memories"
                ).fetchone()["avg"] or 0

                return {
                    "total_memories": total,
                    "by_category": by_category,
                    "verified_count": verified,
                    "avg_importance": round(avg_importance, 1),
                }
        except sqlite3.Error as e:
            logger.error(f"Ошибка статистики: {e}")
            return {
                "total_memories": 0,
                "by_category": {},
                "verified_count": 0,
                "avg_importance": 0,
            }

    def clear(self) -> None:
        """Удаляет все факты из памяти."""
        try:
            with self._connect() as conn:
                conn.execute("DELETE FROM memories")
                conn.commit()
                logger.info("Память очищена")
        except sqlite3.Error as e:
            logger.error(f"Ошибка очистки памяти: {e}")

    # ─── Внутренние методы ──────────────────────────────────────────

    def _find_duplicate(self, fact: str) -> Optional[int]:
        """
        Ищет дубликат факта (точный + семантический с высоким порогом).

        Returns:
            ID дубликата или None.
        """
        try:
            with self._connect() as conn:
                # 1. Точный поиск
                existing = conn.execute(
                    "SELECT id FROM memories WHERE fact = ?", (fact.strip(),)
                ).fetchone()
                if existing:
                    return existing["id"]

                # 2. Семантический поиск с высоким порогом (0.9)
                fact_vec = self.embedder.embed(fact)
                all_rows = conn.execute("SELECT id, embedding FROM memories").fetchall()

                for row in all_rows:
                    entry_vec = json.loads(row["embedding"])
                    score = self.embedder.similarity_from_embedding(
                        fact_vec, entry_vec
                    )
                    if score >= 0.9:
                        return row["id"]

                return None
        except (sqlite3.Error, json.JSONDecodeError):
            return None
