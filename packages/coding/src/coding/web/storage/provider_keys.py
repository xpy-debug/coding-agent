"""API key storage for LLM providers."""

from __future__ import annotations

from coding.web.storage.database import Database


class ProviderKeyStore:
    """Manages provider API keys (and optional base URLs) in SQLite."""

    def __init__(self, db: Database) -> None:
        self._db = db

    async def _get_row(self, provider: str):
        cursor = await self._db.conn.execute(
            "SELECT api_key, base_url FROM provider_keys WHERE provider = ?", (provider,)
        )
        return await cursor.fetchone()

    async def get(self, provider: str) -> str | None:
        """Get API key for a provider."""
        row = await self._get_row(provider)
        return row["api_key"] if row else None

    async def get_base_url(self, provider: str) -> str | None:
        """Get the custom base URL for a provider, if any."""
        row = await self._get_row(provider)
        if row is None:
            return None
        return row["base_url"] or None

    async def exists(self, provider: str) -> bool:
        """Check whether a provider has been configured at all.

        A stored row counts even when the API key is empty: that is how a
        keyless local endpoint is registered.
        """
        cursor = await self._db.conn.execute(
            "SELECT 1 FROM provider_keys WHERE provider = ?", (provider,)
        )
        return await cursor.fetchone() is not None

    async def set(self, provider: str, api_key: str, base_url: str | None = None) -> None:
        """Set API key (and optionally base URL) for a provider.

        ``base_url`` semantics:
        - ``None``: keep the currently stored base URL.
        - ``""``: clear the stored base URL.
        - any other string: store it.
        An empty ``api_key`` keeps the currently stored key.
        """
        row = await self._get_row(provider)
        key_value = api_key or (row["api_key"] if row else "")
        base_url_value = (
            base_url if base_url is not None else (row["base_url"] if row else "")
        ) or ""

        await self._db.conn.execute(
            """INSERT INTO provider_keys (provider, api_key, base_url) VALUES (?, ?, ?)
               ON CONFLICT(provider) DO UPDATE SET
                   api_key=excluded.api_key,
                   base_url=excluded.base_url""",
            (provider, key_value, base_url_value),
        )
        await self._db.conn.commit()

    async def delete(self, provider: str) -> None:
        """Delete API key for a provider."""
        await self._db.conn.execute("DELETE FROM provider_keys WHERE provider = ?", (provider,))
        await self._db.conn.commit()

    async def get_all(self) -> dict[str, str]:
        """Get all stored provider keys (provider -> key)."""
        cursor = await self._db.conn.execute("SELECT provider, api_key FROM provider_keys")
        rows = await cursor.fetchall()
        return {row["provider"]: row["api_key"] for row in rows}

    async def get_base_urls(self) -> dict[str, str]:
        """Get all configured base URL overrides (provider -> base URL)."""
        cursor = await self._db.conn.execute(
            "SELECT provider, base_url FROM provider_keys WHERE base_url != ''"
        )
        rows = await cursor.fetchall()
        return {row["provider"]: row["base_url"] for row in rows}
