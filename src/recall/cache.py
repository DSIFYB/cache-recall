"""
cache.py — Семантический кэш на SQLite с эмбеддингами, тегами и логированием.

Архитектура: агент-first.
  ask(query)   — только поиск. Возвращает ответ или None.
  save(q, r)   — агент сохраняет свой ответ.

Никакого внешнего API. Эмбеддинги вычисляются локально (n-gram hashing).
"""

import hashlib
import json
import logging
import logging.handlers
import math
import os
import re
import sqlite3
import time
from datetime import date
from pathlib import Path
from typing import Optional

# ─── Константы ────────────────────────────────────────────────────────────

DEFAULT_TTL = 86400           # 24 часа
SIMILARITY_THRESHOLD = 0.75   # Порог cosine similarity
EMBED_DIM = 128               # Размерность вектора эмбеддинга
NGRAM_RANGE = (2, 4)          # Диапазон n-gram: 2, 3, 4 символа

# ─── Логгер ───────────────────────────────────────────────────────────────

logger = logging.getLogger("recall")


def setup_logging(
    log_file: Optional[str] = None,
    level: str = "INFO",
    max_bytes: int = 10 * 1024 * 1024,
) -> None:
    """
    Настраивает логирование: файл + консоль.
    Файл ротируется при превышении max_bytes.
    """
    root = logging.getLogger("recall")
    if root.handlers:
        return  # Уже настроено

    root.setLevel(getattr(logging, level.upper(), logging.INFO))

    fmt = logging.Formatter(
        "%(asctime)s [%(levelname)s] %(name)s: %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )

    # Консоль (WARNING+)
    console = logging.StreamHandler()
    console.setLevel(logging.WARNING)
    console.setFormatter(fmt)
    root.addHandler(console)

    # Файл (весь уровень)
    if log_file:
        try:
            path = Path(log_file).expanduser()
            path.parent.mkdir(parents=True, exist_ok=True)
            fh = logging.handlers.RotatingFileHandler(
                path, maxBytes=max_bytes, backupCount=3, encoding="utf-8"
            )
            fh.setLevel(getattr(logging, level.upper(), logging.INFO))
            fh.setFormatter(fmt)
            root.addHandler(fh)
            logger.info(f"Логирование в {path}")
        except OSError as e:
            logger.error(f"Не удалось настроить логирование: {e}")


# ─── Эмбеддер ─────────────────────────────────────────────────────────────


class TextEmbedder:
    """
    Эмбеддер на основе хэширования символьных n-грамм.
    """

    def __init__(self, dim: int = EMBED_DIM, ngram_range: tuple = NGRAM_RANGE):
        self.dim = dim
        self.ngram_range = ngram_range

    def _ngrams(self, text: str) -> list[str]:
        text = re.sub(r'[^\w\s]', '', text.lower())
        text = re.sub(r'\s+', ' ', text).strip()
        ngrams = []
        for n in range(self.ngram_range[0], self.ngram_range[1] + 1):
            for i in range(len(text) - n + 1):
                ngrams.append(text[i:i + n])
        return ngrams

    def embed(self, text: str) -> list[float]:
        if not text:
            return [0.0] * self.dim

        vec = [0.0] * self.dim
        ngrams = self._ngrams(text)
        if not ngrams:
            return vec

        for ngram in ngrams:
            h = int(hashlib.md5(ngram.encode()).hexdigest(), 16)
            idx = h % self.dim
            sign = 1.0 if (h >> 1) & 1 else -1.0
            vec[idx] += sign

        norm = math.sqrt(sum(v * v for v in vec))
        if norm > 0:
            vec = [v / norm for v in vec]
        return vec

    def cosine_similarity(self, a: str, b: str) -> float:
        va = self.embed(a)
        vb = self.embed(b)
        dot = sum(x * y for x, y in zip(va, vb))
        return max(-1.0, min(1.0, dot))

    def similarity_from_embedding(
        self, query_vec: list[float], entry_vec: list[float]
    ) -> float:
        dot = sum(x * y for x, y in zip(query_vec, entry_vec))
        return max(-1.0, min(1.0, dot))


# ─── Утилиты ──────────────────────────────────────────────────────────────


def is_expired(timestamp: float, ttl: float, now: Optional[float] = None) -> bool:
    return ((now or time.time()) - timestamp) > ttl


# ─── Класс кэша ───────────────────────────────────────────────────────────


class PromptCache:
    """
    Семантический кэш на SQLite с тегами и экономикой.
    """

    def __init__(
        self,
        db_path: str = "recall.db",
        ttl: int = DEFAULT_TTL,
        threshold: float = SIMILARITY_THRESHOLD,
        tags_enabled: bool = True,
        economy_enabled: bool = True,
    ):
        self.ttl = ttl
        self.threshold = threshold
        self.tags_enabled = tags_enabled
        self.economy_enabled = economy_enabled
        self.embedder = TextEmbedder()
        self.db_path = db_path
        self._init_db()

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.db_path)
        conn.execute("PRAGMA journal_mode=WAL")  # Быстрее для concurrent
        conn.row_factory = sqlite3.Row
        return conn

    def _init_db(self) -> None:
        try:
            with self._connect() as conn:
                # Основная таблица
                conn.execute("""
                    CREATE TABLE IF NOT EXISTS entries (
                        id INTEGER PRIMARY KEY AUTOINCREMENT,
                        query TEXT NOT NULL,
                        response TEXT NOT NULL,
                        embedding TEXT NOT NULL,
                        timestamp REAL NOT NULL,
                        ttl REAL NOT NULL,
                        access_count INTEGER DEFAULT 1,
                        last_access REAL NOT NULL
                    )
                """)
                conn.execute("""
                    CREATE INDEX IF NOT EXISTS idx_timestamp ON entries(timestamp)
                """)
                conn.execute("""
                    CREATE INDEX IF NOT EXISTS idx_access ON entries(last_access)
                """)

                # Теги
                if self.tags_enabled:
                    conn.execute("""
                        CREATE TABLE IF NOT EXISTS tags (
                            id INTEGER PRIMARY KEY AUTOINCREMENT,
                            name TEXT UNIQUE NOT NULL
                        )
                    """)
                    conn.execute("""
                        CREATE TABLE IF NOT EXISTS entry_tags (
                            entry_id INTEGER NOT NULL,
                            tag_id INTEGER NOT NULL,
                            PRIMARY KEY (entry_id, tag_id),
                            FOREIGN KEY (entry_id) REFERENCES entries(id),
                            FOREIGN KEY (tag_id) REFERENCES tags(id)
                        )
                    """)
                    conn.execute("""
                        CREATE INDEX IF NOT EXISTS idx_entry_tags ON entry_tags(tag_id)
                    """)

                conn.commit()
            logger.info(f"БД инициализирована: {self.db_path}")
        except sqlite3.Error as e:
            logger.error(f"Ошибка инициализации БД: {e}")

    # ── Теги ─────────────────────────────────────────────────────────────

    def _save_tags(self, conn: sqlite3.Connection, entry_id: int, tags: list[str]) -> None:
        """Сохраняет теги для записи."""
        if not tags:
            return
        for tag in tags:
            tag = tag.strip().lower()
            if not tag.startswith("#"):
                tag = "#" + tag

            # Находим или создаём тег
            existing = conn.execute(
                "SELECT id FROM tags WHERE name = ?", (tag,)
            ).fetchone()
            if existing:
                tag_id = existing["id"]
            else:
                cursor = conn.execute(
                    "INSERT INTO tags (name) VALUES (?)", (tag,)
                )
                tag_id = cursor.lastrowid

            # Привязываем к записи
            conn.execute(
                "INSERT OR IGNORE INTO entry_tags (entry_id, tag_id) VALUES (?, ?)",
                (entry_id, tag_id),
            )

    def _get_entry_tags(self, conn: sqlite3.Connection, entry_id: int) -> list[str]:
        """Получает теги записи."""
        rows = conn.execute("""
            SELECT t.name FROM tags t
            JOIN entry_tags et ON t.id = et.tag_id
            WHERE et.entry_id = ?
        """, (entry_id,)).fetchall()
        return [r["name"] for r in rows]

    def get_all_tags(self) -> list[dict]:
        """Возвращает все теги с количеством записей."""
        if not self.tags_enabled:
            return []
        try:
            with self._connect() as conn:
                rows = conn.execute("""
                    SELECT t.name, COUNT(et.entry_id) as count
                    FROM tags t
                    LEFT JOIN entry_tags et ON t.id = et.tag_id
                    GROUP BY t.id
                    ORDER BY count DESC
                """).fetchall()
                return [{"tag": r["name"], "count": r["count"]} for r in rows]
        except sqlite3.Error:
            return []

    def list_by_tag(self, tag: str) -> list[dict]:
        """Возвращает записи с определённым тегом."""
        if not self.tags_enabled:
            return []
        tag = tag.strip().lower()
        if not tag.startswith("#"):
            tag = "#" + tag
        try:
            with self._connect() as conn:
                rows = conn.execute("""
                    SELECT e.* FROM entries e
                    JOIN entry_tags et ON e.id = et.entry_id
                    JOIN tags t ON et.tag_id = t.id
                    WHERE t.name = ?
                    ORDER BY e.last_access DESC
                """, (tag,)).fetchall()
                return [dict(r) for r in rows]
        except sqlite3.Error:
            return []

    # ── Основные методы ──────────────────────────────────────────────────

    def ask(self, query: str, tags: Optional[list[str]] = None) -> Optional[str]:
        """
        Ищет ответ в кэше.

        1. Если указаны теги — сначала ищет в них (приоритет).
        2. Точное совпадение по тексту запроса.
        3. Семантический поиск через эмбеддинги.

        Возвращает ответ или None.
        """
        if not query:
            return None

        now = time.time()

        try:
            with self._connect() as conn:
                # Если теги включены — приоритетный поиск в теге
                if self.tags_enabled and tags:
                    for tag in tags:
                        tag = tag.strip().lower()
                        if not tag.startswith("#"):
                            tag = "#" + tag

                        tag_id_row = conn.execute(
                            "SELECT id FROM tags WHERE name = ?", (tag,)
                        ).fetchone()
                        if tag_id_row:
                            # Ищем в рамках тега
                            tagged_rows = conn.execute("""
                                SELECT e.* FROM entries e
                                JOIN entry_tags et ON e.id = et.entry_id
                                WHERE et.tag_id = ?
                                ORDER BY e.last_access DESC
                            """, (tag_id_row["id"],)).fetchall()

                            for row in tagged_rows:
                                if is_expired(row["timestamp"], row["ttl"], now):
                                    conn.execute(
                                        "DELETE FROM entries WHERE id = ?",
                                        (row["id"],),
                                    )
                                    continue

                                if row["query"].lower().strip() == query.lower().strip():
                                    self._touch(conn, row["id"], now)
                                    conn.commit()
                                    logger.info(
                                        f"Точный HIT (тег {tag}): '{query[:40]}'"
                                    )
                                    self._record_economy(False)
                                    return row["response"]

                # 1. Точное совпадение (по всей базе)
                row = conn.execute(
                    "SELECT * FROM entries WHERE query = ? ORDER BY last_access DESC LIMIT 1",
                    (query,),
                ).fetchone()

                if row and not is_expired(row["timestamp"], row["ttl"], now):
                    self._touch(conn, row["id"], now)
                    conn.commit()
                    logger.info(f"Точный HIT: '{query[:50]}'")
                    self._record_economy(False)
                    return row["response"]

                # Удаляем просроченное точное совпадение
                if row and is_expired(row["timestamp"], row["ttl"], now):
                    conn.execute("DELETE FROM entries WHERE id = ?", (row["id"],))
                    conn.commit()

                # 2. Семантический поиск
                query_vec = self.embedder.embed(query)
                all_rows = conn.execute(
                    "SELECT * FROM entries ORDER BY last_access DESC"
                ).fetchall()

                best_row = None
                best_score = 0.0

                for row in all_rows:
                    if is_expired(row["timestamp"], row["ttl"], now):
                        conn.execute("DELETE FROM entries WHERE id = ?", (row["id"],))
                        continue

                    entry_vec = json.loads(row["embedding"])
                    score = self.embedder.similarity_from_embedding(
                        query_vec, entry_vec
                    )
                    if score > best_score:
                        best_score = score
                        best_row = row

                conn.commit()

                if best_row and best_score >= self.threshold:
                    self._touch(conn, best_row["id"], now)
                    conn.commit()
                    logger.info(
                        f"Семантический HIT ({best_score:.2f}): "
                        f"'{query[:40]}' ≈ '{best_row['query'][:40]}'"
                    )
                    self._record_economy(True)
                    return best_row["response"]

                # MISS
                logger.info(f"MISS: '{query[:50]}'")
                self._record_economy(None)
                return None

        except sqlite3.Error as e:
            logger.error(f"Ошибка запроса к БД: {e}")
            return None

    def save(
        self,
        query: str,
        response: str,
        tags: Optional[list[str]] = None,
    ) -> bool:
        """
        Сохраняет ответ агента в кэш.

        Args:
            query: Текст запроса.
            response: Ответ агента.
            tags: Список тегов (опционально).
        """
        if not query or not response:
            return False

        now = time.time()
        embedding = self.embedder.embed(query)

        try:
            with self._connect() as conn:
                existing = conn.execute(
                    "SELECT id FROM entries WHERE query = ?", (query,)
                ).fetchone()

                if existing:
                    conn.execute(
                        """
                        UPDATE entries
                        SET response = ?, embedding = ?, timestamp = ?,
                            ttl = ?, access_count = 1, last_access = ?
                        WHERE id = ?
                        """,
                        (
                            response,
                            json.dumps(embedding),
                            now,
                            self.ttl,
                            now,
                            existing["id"],
                        ),
                    )
                    entry_id = existing["id"]
                    # Обновляем теги
                    if self.tags_enabled and tags:
                        conn.execute(
                            "DELETE FROM entry_tags WHERE entry_id = ?",
                            (entry_id,),
                        )
                else:
                    cursor = conn.execute(
                        """
                        INSERT INTO entries (query, response, embedding, timestamp, ttl, access_count, last_access)
                        VALUES (?, ?, ?, ?, ?, 1, ?)
                        """,
                        (
                            query,
                            response,
                            json.dumps(embedding),
                            now,
                            self.ttl,
                            now,
                        ),
                    )
                    entry_id = cursor.lastrowid

                # Сохраняем теги
                if self.tags_enabled and tags:
                    self._save_tags(conn, entry_id, tags)

                conn.commit()
                logger.info(f"SAVED: '{query[:50]}' (теги: {tags or 'нет'})")
                return True

        except sqlite3.Error as e:
            logger.error(f"Ошибка сохранения в БД: {e}")
            return False

    def stats(self) -> dict:
        """Возвращает статистику кэша."""
        now = time.time()
        try:
            with self._connect() as conn:
                total = conn.execute(
                    "SELECT COUNT(*) as cnt FROM entries"
                ).fetchone()["cnt"]

                all_rows = conn.execute(
                    "SELECT timestamp, ttl FROM entries"
                ).fetchall()

                valid = sum(
                    1 for r in all_rows
                    if not is_expired(r["timestamp"], r["ttl"], now)
                )
                expired = total - valid

                db_size = os.path.getsize(self.db_path) if os.path.exists(self.db_path) else 0
                if db_size < 1024:
                    size_str = f"{db_size} Б"
                elif db_size < 1024 * 1024:
                    size_str = f"{db_size / 1024:.2f} КБ"
                else:
                    size_str = f"{db_size / (1024 * 1024):.2f} МБ"

                return {
                    "total_entries": total,
                    "valid_entries": valid,
                    "expired_entries": expired,
                    "total_size": size_str,
                    "ttl": self.ttl,
                    "threshold": self.threshold,
                    "db_path": self.db_path,
                    "tags_enabled": self.tags_enabled,
                    "tag_count": len(self.get_all_tags()) if self.tags_enabled else 0,
                }

        except (sqlite3.Error, OSError) as e:
            logger.error(f"Ошибка статистики: {e}")
            return {
                "total_entries": 0,
                "valid_entries": 0,
                "expired_entries": 0,
                "total_size": "0 Б",
                "ttl": self.ttl,
                "threshold": self.threshold,
                "db_path": self.db_path,
                "tags_enabled": self.tags_enabled,
                "tag_count": 0,
            }

    def list_entries(self, include_expired: bool = False, tag: Optional[str] = None) -> list[dict]:
        """Возвращает список записей."""
        if tag and self.tags_enabled:
            entries = self.list_by_tag(tag)
            if not include_expired:
                now = time.time()
                entries = [e for e in entries if not is_expired(e["timestamp"], e["ttl"], now)]
            return entries

        now = time.time()
        try:
            with self._connect() as conn:
                rows = conn.execute(
                    "SELECT * FROM entries ORDER BY last_access DESC"
                ).fetchall()

                entries = []
                for row in rows:
                    is_exp = is_expired(row["timestamp"], row["ttl"], now)
                    if not include_expired and is_exp:
                        continue

                    entry_dict = dict(row)
                    entry_dict["expired"] = is_exp

                    # Добавляем теги
                    if self.tags_enabled:
                        entry_dict["tags"] = self._get_entry_tags(conn, row["id"])

                    entries.append(entry_dict)
                return entries

        except sqlite3.Error as e:
            logger.error(f"Ошибка получения записей: {e}")
            return []

    def clear(self) -> None:
        """Удаляет все записи и теги."""
        try:
            with self._connect() as conn:
                conn.execute("DELETE FROM entries")
                if self.tags_enabled:
                    conn.execute("DELETE FROM entry_tags")
                    conn.execute("DELETE FROM tags")
                conn.commit()
                logger.info("Кэш очищен")
        except sqlite3.Error as e:
            logger.error(f"Ошибка очистки: {e}")

    def cleanup(self) -> int:
        """Удаляет просроченные записи."""
        now = time.time()
        try:
            with self._connect() as conn:
                rows = conn.execute("SELECT id, timestamp, ttl FROM entries").fetchall()
                ids_to_delete = [
                    r["id"] for r in rows
                    if is_expired(r["timestamp"], r["ttl"], now)
                ]
                if ids_to_delete:
                    placeholders = ",".join("?" * len(ids_to_delete))
                    conn.execute(
                        f"DELETE FROM entries WHERE id IN ({placeholders})",
                        ids_to_delete,
                    )
                    # Удаляем сиротские теги
                    if self.tags_enabled:
                        conn.execute("""
                            DELETE FROM entry_tags WHERE entry_id NOT IN (SELECT id FROM entries)
                        """)
                        conn.execute("""
                            DELETE FROM tags WHERE id NOT IN (SELECT tag_id FROM entry_tags)
                        """)
                    conn.commit()
                    logger.info(f"cleanup: удалено {len(ids_to_delete)} просроченных")
                return len(ids_to_delete)
        except sqlite3.Error as e:
            logger.error(f"Ошибка очистки просроченных: {e}")
            return 0

    def close(self) -> None:
        pass

    # ── Внутренние методы ──────────────────────────────────────────────

    def _touch(self, conn: sqlite3.Connection, entry_id: int, now: float) -> None:
        conn.execute(
            """
            UPDATE entries
            SET access_count = access_count + 1, last_access = ?
            WHERE id = ?
            """,
            (now, entry_id),
        )

    def _record_economy(self, is_semantic: Optional[bool]) -> None:
        """Записывает HIT/MISS в экономику."""
        if not self.economy_enabled:
            return
        try:
            from recall.economy import EconomyTracker
            tracker = EconomyTracker(self.db_path)
            if is_semantic is None:
                tracker.record_miss()
            else:
                tracker.record_hit("", is_semantic)  # query обновится отдельно
        except Exception:
            pass
