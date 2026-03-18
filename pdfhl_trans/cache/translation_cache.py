"""SQLite-backed translation cache to avoid duplicate API calls."""

from __future__ import annotations

import sqlite3
import threading
from pathlib import Path

from pdfhl_trans.utils.logger import get_logger

logger = get_logger("cache.translation_cache")

_SCHEMA = """
CREATE TABLE IF NOT EXISTS translations (
    text_hash   TEXT NOT NULL,
    target_lang TEXT NOT NULL,
    translation TEXT NOT NULL,
    created_at  TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    PRIMARY KEY (text_hash, target_lang)
);
"""


class TranslationCache:
    """Persistent cache for translated text backed by SQLite.

    The cache key is a combination of the source text and target
    language. Matching translations are returned immediately without
    calling the translation API.

    The database is stored at ``<cache_dir>/cache.db`` and created
    automatically if it does not exist.
    """

    def __init__(self, cache_dir: Path | None = None) -> None:
        """Initialise the translation cache.

        Args:
            cache_dir: Directory for the SQLite database. Defaults to
                       ``~/.pdfhl_trans``.
        """
        if cache_dir is None:
            cache_dir = Path.home() / ".pdfhl_trans"

        cache_dir.mkdir(parents=True, exist_ok=True)
        db_path = cache_dir / "cache.db"

        self._conn = sqlite3.connect(str(db_path), check_same_thread=False)
        self._conn.execute("PRAGMA journal_mode=WAL")
        self._conn.execute(_SCHEMA)
        self._conn.commit()

        self._hits = 0
        self._lock = threading.Lock()
        logger.debug("Cache database opened at %s", db_path)

    @property
    def hits(self) -> int:
        """Number of cache hits since initialisation."""
        return self._hits

    def get(self, text: str, target_language: str) -> str | None:
        """Look up a cached translation.

        Args:
            text: The original source text.
            target_language: Target language code.

        Returns:
            The cached translation, or ``None`` if not found.
        """
        with self._lock:
            cursor = self._conn.execute(
                "SELECT translation FROM translations WHERE text_hash = ? AND target_lang = ?",
                (text, target_language),
            )
            row = cursor.fetchone()
            if row:
                self._hits += 1
                logger.debug("Cache hit for: %.50s… → %s", text, target_language)
                return str(row[0])
        return None

    def put(self, text: str, target_language: str, translation: str) -> None:
        """Store a translation in the cache.

        Args:
            text: The original source text.
            target_language: Target language code.
            translation: The translated text.
        """
        with self._lock:
            self._conn.execute(
                "INSERT OR REPLACE INTO translations (text_hash, target_lang, translation) "
                "VALUES (?, ?, ?)",
                (text, target_language, translation),
            )
            self._conn.commit()
        logger.debug("Cached translation for: %.50s… → %s", text, target_language)

    def clear(self) -> int:
        """Remove all cached translations.

        Returns:
            The number of entries removed.
        """
        cursor = self._conn.execute("DELETE FROM translations")
        self._conn.commit()
        count = cursor.rowcount
        logger.info("Cleared %d cached translations", count)
        return count

    def close(self) -> None:
        """Close the database connection."""
        self._conn.close()
