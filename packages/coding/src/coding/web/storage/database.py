"""SQLite database connection manager using aiosqlite."""

from __future__ import annotations

import aiosqlite

from coding.web.storage.schema import SCHEMA_SQL


class Database:
    """Async SQLite connection manager."""

    def __init__(self, db_path: str) -> None:
        self._db_path = db_path
        self._conn: aiosqlite.Connection | None = None

    async def connect(self) -> None:
        """Open database connection and ensure schema exists."""
        self._conn = await aiosqlite.connect(self._db_path)
        self._conn.row_factory = aiosqlite.Row
        await self._conn.executescript(SCHEMA_SQL)
        await self._migrate()
        await self._conn.commit()

    async def _migrate(self) -> None:
        """Apply additive migrations for databases created by older versions."""
        conn = self.conn
        cursor = await conn.execute("PRAGMA table_info(provider_keys)")
        columns = {row["name"] for row in await cursor.fetchall()}
        if "base_url" not in columns:
            await conn.execute(
                "ALTER TABLE provider_keys ADD COLUMN base_url TEXT NOT NULL DEFAULT ''"
            )

    async def close(self) -> None:
        """Close database connection."""
        if self._conn:
            await self._conn.close()
            self._conn = None

    @property
    def conn(self) -> aiosqlite.Connection:
        if self._conn is None:
            raise RuntimeError("Database not connected. Call connect() first.")
        return self._conn
